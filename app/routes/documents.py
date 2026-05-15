import os
import logging
import uuid

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)
from werkzeug.utils import secure_filename

from ocr.batch import BatchProcessor
from ocr import process_document

from app.extensions import db
from app.models.client import Client
from app.models.document import Document
from app.models.firm import Firm

from app.services.drive_service import (
    FOLDER_ID,
    get_or_create_folder,
    upload_file_to_folder,
)
from app.services.folder_service import build_folder_structure
from app.services.client_matcher import match_client
from app.services.whatsapp_document_workflow import process_local_document

from app.utils.access_control import login_required

from config import Config

logger = logging.getLogger(__name__)

documents_bp = Blueprint("documents", __name__)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _build_metadata(ocr_result: dict) -> dict:
    """Normalize an OCR result dict into a standard metadata dict."""
    ids = ocr_result.get("important_ids", {})
    return {
        "document_type": ocr_result.get("document_type"),
        "assessment_year": ocr_result.get("year", {}).get("value"),
        "confidence_score": ocr_result.get("document_confidence", 0),
        "summary": ocr_result.get("summary", ""),
        "important_ids": {
            "pan": ids.get("pan", {}).get("value"),
            "aadhaar": ids.get("aadhaar", {}).get("value"),
            "gstin": ids.get("gstin", {}).get("value"),
            "tan": ids.get("tan", {}).get("value"),
        },
        "name": ocr_result.get("detected_name", {}).get("value"),
        "ocr_score": ocr_result.get("ocr_score", 0),
    }


def _resolve_status(metadata: dict, client, ambiguous: bool) -> str:
    """
    Determine document status based on metadata and client match.

    Rules (in priority order):
      1. Unknown document type → always pending_review
      2. Client matched, unambiguous, and confidence thresholds met → auto_classified
      3. Everything else → pending_review
    """
    if metadata.get("document_type") == "Other":
        return "pending_review"

    if (
        client
        and not ambiguous
        and metadata.get("confidence_score", 0) >= 70
        and metadata.get("ocr_score", 0) >= 25
    ):
        return "auto_classified"

    return "pending_review"


def _build_drive_folders(
    firm,
    client,
    document_type: str,
    assessment_year=None,
) -> dict:
    """
    Create (or fetch) the Drive folder hierarchy and return their IDs.
    Also updates client.google_drive_folder_id if a client is provided.
    """
    folder_structure = build_folder_structure(
        firm=firm,
        client=client,
        document_type=document_type,
        assessment_year=assessment_year,
    )
    logger.debug("Folder structure: %s", folder_structure)

    firm_folder_id = get_or_create_folder(
        folder_structure["firm_folder"],
        parent_id=FOLDER_ID,
    )
    client_folder_id = get_or_create_folder(
        folder_structure["client_folder"],
        parent_id=firm_folder_id,
    )
    document_folder_id = get_or_create_folder(
        folder_structure["document_folder"],
        parent_id=client_folder_id,
    )

    if folder_structure.get("year_folder"):
        document_folder_id = get_or_create_folder(
            folder_structure["year_folder"],
            parent_id=document_folder_id,
        )

    if client:
        client.google_drive_folder_id = client_folder_id

    logger.debug(
        "Drive folders — firm: %s  client: %s  document: %s",
        firm_folder_id,
        client_folder_id,
        document_folder_id,
    )
    return {
        "firm_folder_id": firm_folder_id,
        "client_folder_id": client_folder_id,
        "document_folder_id": document_folder_id,
    }


# -------------------------------------------------------------------
# Review Queue
# -------------------------------------------------------------------

@documents_bp.route("/reviews")
@login_required
def review_queue():
    documents = (
        Document.query
        .filter_by(firm_id=session["firm_id"], status="pending_review")
        .all()
    )
    return render_template("reviews/list.html", documents=documents)


@documents_bp.route("/reviews/<int:doc_id>", methods=["GET", "POST"])
@login_required
def review_document(doc_id):
    document = Document.query.get_or_404(doc_id)

    # Security check (was missing in original)
    if document.firm_id != session["firm_id"]:
        flash("Unauthorized access", "danger")
        return redirect(url_for("documents.review_queue"))

    clients = Client.query.filter_by(firm_id=session["firm_id"]).all()

    if request.method == "POST":
        document.client_id = request.form.get("client_id")
        document.document_type = request.form.get("document_type")
        document.assessment_year = request.form.get("assessment_year")
        document.status = "approved"
        document.client_id = request.form.get(
    "client_id"
)


        client = Client.query.get(
            document.client_id
        )

        firm = Firm.query.get(
            session["firm_id"]
        )

        folder_structure = build_folder_structure(
            firm=firm,
            client=client,
            document_type=document.document_type,
            assessment_year=document.assessment_year,
        )

        from app.services.drive_service import (
            FOLDER_ID,
            get_or_create_folder,
            move_file_to_folder
        )

        firm_folder_id = get_or_create_folder(
            folder_structure["firm_folder"],
            parent_id=FOLDER_ID
        )

        client_folder_id = get_or_create_folder(
            folder_structure["client_folder"],
            parent_id=firm_folder_id
        )

        document_folder_id = get_or_create_folder(
            folder_structure["document_folder"],
            parent_id=client_folder_id
        )

        if folder_structure.get("year_folder"):
            document_folder_id = get_or_create_folder(
                folder_structure["year_folder"],
                parent_id=document_folder_id
            )

        move_file_to_folder(
            file_id=document.google_drive_file_id,
            folder_id=document_folder_id
        )


        db.session.commit()
        flash("Document approved", "success")
        return redirect(url_for("documents.review_queue"))

    return render_template(
        "reviews/review.html",
        document=document,
        clients=clients,
    )


# -------------------------------------------------------------------
# Dashboard
# -------------------------------------------------------------------

@documents_bp.route("/dashboard")
@login_required
def dashboard():
    firm_id = session["firm_id"]

    total_clients = Client.query.filter_by(firm_id=firm_id).count()
    total_documents = Document.query.filter_by(firm_id=firm_id).count()
    pending_reviews = Document.query.filter_by(
        firm_id=firm_id, status="pending_review"
    ).count()
    ai_classified = Document.query.filter_by(
        firm_id=firm_id, status="auto_classified"
    ).count()
    documents = (
        db.session.query(
            Document,
            Client.client_name,
            Client.pan_number,
        )
        .outerjoin(Client, Document.client_id == Client.id)
        .filter(Document.firm_id == firm_id)
        .order_by(Document.uploaded_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "dashboard.html",
        total_clients=total_clients,
        total_documents=total_documents,
        pending_reviews=pending_reviews,
        ai_classified=ai_classified,
        documents=documents,
    )


# -------------------------------------------------------------------
# Single Upload
# -------------------------------------------------------------------

@documents_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        file = request.files.get("file")
        if not file:
            flash("Please select a file", "danger")
            return redirect(request.url)

        filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        upload_path = os.path.join(Config.UPLOAD_FOLDER, filename)
        file.save(upload_path)

        process_local_document(
            file_path=upload_path,
            mime_type=file.mimetype,
            original_filename=file.filename,
            firm_id=session["firm_id"],
            uploaded_by=session["user_id"],
        )

        flash("Document uploaded successfully", "success")
        return redirect(url_for("documents.dashboard"))

    return render_template("upload.html")


# -------------------------------------------------------------------
# View / Delete
# -------------------------------------------------------------------

@documents_bp.route("/documents/<int:doc_id>")
@login_required
def view_document(doc_id):
    document = Document.query.get_or_404(doc_id)
    if document.firm_id != session["firm_id"]:
        flash("Unauthorized access", "danger")
        return redirect(url_for("documents.dashboard"))
    return render_template("documents/view.html", document=document)


@documents_bp.route("/documents/delete/<int:doc_id>", methods=["POST"])
@login_required
def delete_document(doc_id):
    document = Document.query.get_or_404(doc_id)
    if document.firm_id != session["firm_id"]:
        flash("Unauthorized access", "danger")
        return redirect(url_for("documents.dashboard"))
    from app.services.drive_service import (
        delete_drive_file
    )

    if document.google_drive_file_id:

        try:

            delete_drive_file(
                document.google_drive_file_id
            )

        except Exception as e:

            print("\nDRIVE DELETE ERROR\n")
            print(e)
    

    db.session.delete(document)
    db.session.commit()
    flash("Document deleted successfully", "success")
    return redirect(url_for("documents.dashboard"))


# -------------------------------------------------------------------
# Bulk Upload
# -------------------------------------------------------------------

@documents_bp.route("/bulk-upload", methods=["GET", "POST"])
@login_required
def bulk_upload():
    if request.method == "POST":
        files = request.files.getlist("files")
        if not files:
            flash("Please select files", "danger")
            return redirect(request.url)

        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

        # Save all files locally first
        uploaded_paths = []
        for file in files:
            if not file.filename:
                continue
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            upload_path = os.path.join(Config.UPLOAD_FOLDER, filename)
            file.save(upload_path)
            uploaded_paths.append(upload_path)

        # OCR batch
        processor = BatchProcessor(workers=1, cache_dir=None, verbose=False)
        results = processor.process_batch(uploaded_paths, use_routing=False)

        # Fetch firm once — it never changes across the loop
        firm = Firm.query.get(session["firm_id"])
        processed_count = 0

        for result in results:
            try:
                extracted_text = (result.get("text") or result.get("raw_text") or "").strip()
                metadata = _build_metadata(result)

                # Client matching
                match_result = match_client(metadata, session["firm_id"])
                client = match_result.get("client")
                ambiguous = match_result.get("ambiguous")

                # Status
                status = _resolve_status(metadata, client, ambiguous)

                # Drive folders
                drive = _build_drive_folders(
                    firm=firm,
                    client=client,
                    document_type=metadata.get("document_type"),
                    assessment_year=metadata.get("assessment_year"),
                )

                # Upload file to Drive
                original_path = result["file"]
                filename = os.path.basename(original_path)
                uploaded_drive_file = upload_file_to_folder(
                    file_path=original_path,
                    filename=filename,
                    folder_id=drive["document_folder_id"],
                    mime_type="application/octet-stream",
                )

                # Stage document for bulk commit
                document = Document(
                    google_drive_file_id=uploaded_drive_file["id"],
                    firm_id=session["firm_id"],
                    client_id=client.id if client else None,
                    uploaded_by=session["user_id"],
                    filename=filename,
                    document_type=metadata.get("document_type"),
                    assessment_year=metadata.get("assessment_year"),
                    extracted_text=extracted_text,
                    extracted_json=metadata,
                    confidence_score=metadata.get("confidence_score", 0),
                    status=status,
                )
                db.session.add(document)
                processed_count += 1

            except Exception:
                logger.exception("Error processing bulk file: %s", result.get("file"))
                continue

        # Single commit for all successfully processed documents
        db.session.commit()

        flash(
            f"Bulk upload complete: {processed_count} file(s) processed",
            "success",
        )
        return redirect(url_for("documents.dashboard"))

    return render_template("bulk_upload.html")
