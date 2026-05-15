import logging
import os
import re
import time
import uuid

import requests
from sqlalchemy.exc import OperationalError
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

from ocr import process_document

from app.extensions import db
from app.models.client import Client
from app.models.document import Document
from app.models.firm import Firm
from app.models.user import User
from app.services.client_matcher import match_client
from app.services.drive_service import FOLDER_ID, get_or_create_folder, upload_file_to_folder
from app.services.folder_service import build_folder_structure
from config import Config

logger = logging.getLogger(__name__)

DOCUMENT_KEYWORDS = {
    "Aadhaar": ["aadhaar", "adhar", "aadhar"],
    "PAN": ["pan"],
    "ITR": [
        "itr",
        "income tax return",
        "income tax",
        "return of income",
        "income taxt return",
        "insome tax return",
    ],
    "GST": ["gst", "gstin"],
    "Bank Statement": ["bank statement", "statement"],
    "Balance Sheet": [
        "balance sheet",
        "balancesheet",
        "assets liabilities",
    ],
    "Form 16": ["form 16", "form16"],
    "Salary Slip": ["salary slip", "payslip", "pay slip"],
}

YEAR_PATTERN = re.compile(
    r"(?:\bay\b|\bassessment\s+year\b)?\s*"
    r"\b(?:(20)?(\d{2})\s*[-/]\s*(20)?(\d{2}))\b",
    re.IGNORECASE,
)

SUPPORTED_MEDIA_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def detect_document_types(message):
    text = (message or "").lower()
    return [
        doc_type
        for doc_type, keywords in DOCUMENT_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]


def normalize_assessment_year(value):
    text = (value or "").strip()
    if not text:
        return None

    match = YEAR_PATTERN.search(text)
    if not match:
        return None

    start_prefix, start_year, end_prefix, end_year = match.groups()
    start_full = int(f"{start_prefix or '20'}{start_year}")
    end_full = int(f"{end_prefix or '20'}{end_year}")

    if end_full < start_full:
        end_full += 100

    return f"{start_full}-{str(end_full)[-2:]}"


def extract_requested_assessment_year(message):
    return normalize_assessment_year(message)


def normalize_phone(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def format_meta_recipient(phone):
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def find_client_by_phone(phone, firm_id=None):
    clients = find_clients_by_phone(phone, firm_id=firm_id)
    return clients[0] if clients else None


def find_clients_by_phone(phone, firm_id=None):
    mobile = normalize_phone(phone)
    query = Client.query.filter(
        Client.is_active == True,
        func.replace(Client.mobile, " ", "").like(f"%{mobile}"),
    )

    if firm_id:
        query = query.filter(Client.firm_id == firm_id)

    return query.all()


def search_client_documents(phone, message, firm_id):
    clients = find_clients_by_phone(phone, firm_id=firm_id)
    if not clients:
        return None, [], [], "No access / client not found"

    requested_types = detect_document_types(message)
    if not requested_types:
        return clients[0], requested_types, [], "No supported document keywords found"

    requested_year = extract_requested_assessment_year(message)

    filters = []
    for doc_type in requested_types:
        type_terms = [doc_type.lower(), *DOCUMENT_KEYWORDS[doc_type]]
        if doc_type == "Aadhaar":
            type_terms.append("aadhaar card")
        elif doc_type == "PAN":
            type_terms.append("pan card")

        for term in type_terms:
            filters.append(func.lower(Document.document_type).like(f"%{term}%"))

    documents = (
        Document.query
        .filter(Document.firm_id == firm_id)
        .filter(Document.client_id.in_([client.id for client in clients]))
        .filter(or_(*filters))
        .order_by(Document.uploaded_at.desc())
        .all()
    )

    if requested_year and "ITR" in requested_types:
        documents = [
            document
            for document in documents
            if normalize_assessment_year(document.assessment_year) == requested_year
        ]

        if not documents:
            return (
                clients[0],
                requested_types,
                [],
                f"No ITR found for AY {requested_year}",
            )

    return clients[0], requested_types, documents, None


def _build_metadata(ocr_result):
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


def _resolve_status(metadata, client, ambiguous):
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


def _build_drive_folders(firm, client, document_type, assessment_year=None):
    folder_structure = build_folder_structure(
        firm=firm,
        client=client,
        document_type=document_type,
        assessment_year=assessment_year,
    )

    firm_folder_id = get_or_create_folder(folder_structure["firm_folder"], parent_id=FOLDER_ID)
    client_folder_id = get_or_create_folder(folder_structure["client_folder"], parent_id=firm_folder_id)
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

    return document_folder_id


def process_local_document(
    file_path,
    original_filename,
    mime_type,
    firm_id,
    uploaded_by=None,
    fallback_client=None,
):
    ocr_result = process_document(file_path)
    extracted_text = (ocr_result.get("text") or ocr_result.get("raw_text") or "").strip()
    metadata = _build_metadata(ocr_result)

    match_result = match_client(metadata, firm_id)
    client = match_result.get("client") or fallback_client
    ambiguous = match_result.get("ambiguous")

    if client and client.client_name:
        metadata["name"] = client.client_name

    status = _resolve_status(metadata, client, ambiguous)

    firm = Firm.query.get(firm_id)
    folder_id = _build_drive_folders(
        firm,
        client,
        metadata.get("document_type"),
        metadata.get("assessment_year"),
    )

    filename = f"{uuid.uuid4().hex}_{secure_filename(original_filename)}"
    uploaded_drive_file = upload_file_to_folder(
        file_path=file_path,
        filename=filename,
        folder_id=folder_id,
        mime_type=mime_type,
    )

    if not uploaded_by:
        owner = User.query.filter_by(firm_id=firm_id, role=User.ROLE_FIRM_ADMIN).first()
        uploaded_by = owner.id if owner else None

    document = Document(
        google_drive_file_id=uploaded_drive_file["id"],
        firm_id=firm_id,
        client_id=client.id if client else None,
        uploaded_by=uploaded_by,
        filename=filename,
        document_type=metadata.get("document_type"),
        assessment_year=metadata.get("assessment_year"),
        extracted_text=extracted_text,
        extracted_json=metadata,
        confidence_score=metadata.get("confidence_score", 0),
        status=status,
    )
    db.session.add(document)
    for attempt in range(3):
        try:
            db.session.commit()
            break
        except OperationalError as exc:
            db.session.rollback()
            if "database is locked" not in str(exc).lower() or attempt == 2:
                raise
            time.sleep(1)

    return document


def download_meta_media(media_id, fallback_mime_type=None, fallback_filename=None):
    token = os.getenv("TOKEN") or os.getenv("WHATSAPP_TOKEN") or os.getenv("META_WHATSAPP_TOKEN")
    if not token:
        raise RuntimeError("Meta WhatsApp token is not configured")

    headers = {"Authorization": f"Bearer {token}"}
    meta_url = f"https://graph.facebook.com/v19.0/{media_id}"
    meta_response = requests.get(meta_url, headers=headers, timeout=20)
    meta_response.raise_for_status()
    media_meta = meta_response.json()

    media_url = media_meta.get("url")
    mime_type = media_meta.get("mime_type") or fallback_mime_type
    if not media_url:
        raise ValueError("Meta media URL missing")
    if mime_type not in SUPPORTED_MEDIA_TYPES:
        raise ValueError(f"Unsupported file type: {mime_type}")

    original_filename = fallback_filename or f"whatsapp_{media_id}{SUPPORTED_MEDIA_TYPES[mime_type]}"
    filename = f"{uuid.uuid4().hex}_{secure_filename(original_filename)}"
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    file_path = os.path.join(Config.UPLOAD_FOLDER, filename)

    media_response = requests.get(media_url, headers=headers, timeout=60)
    media_response.raise_for_status()

    with open(file_path, "wb") as f:
        f.write(media_response.content)

    return file_path, original_filename, mime_type


def download_twilio_media(media_url, mime_type, fallback_filename=None):
    if not media_url:
        raise ValueError("Twilio media URL missing")
    if mime_type not in SUPPORTED_MEDIA_TYPES:
        raise ValueError(f"Unsupported file type: {mime_type}")

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        raise RuntimeError("Twilio credentials are not configured")

    original_filename = fallback_filename or f"twilio_whatsapp{SUPPORTED_MEDIA_TYPES[mime_type]}"
    filename = f"{uuid.uuid4().hex}_{secure_filename(original_filename)}"
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    file_path = os.path.join(Config.UPLOAD_FOLDER, filename)

    response = requests.get(
        media_url,
        auth=(account_sid, auth_token),
        timeout=60,
    )
    response.raise_for_status()

    with open(file_path, "wb") as f:
        f.write(response.content)

    return file_path, original_filename, mime_type


def process_twilio_webhook_form(form):
    sender = form.get("From", "")
    body = form.get("Body", "")
    num_media = int(form.get("NumMedia", "0") or 0)
    logger.info("Twilio WhatsApp webhook sender=%s media_count=%s", sender, num_media)

    client = find_client_by_phone(sender)
    if not client:
        return {
            "sender": sender,
            "status": "no_client",
            "reply": "No access / client not found",
        }

    if num_media <= 0:
        _, requested, docs, error = search_client_documents(
            sender,
            body,
            firm_id=client.firm_id,
        )

        if error:
            reply = error
        elif docs:
            lines = ["Here are your matching documents:"]
            for index, doc in enumerate(docs, start=1):
                drive_url = (
                    "https://drive.google.com/uc?export=download&id="
                    f"{doc.google_drive_file_id}"
                    if doc.google_drive_file_id
                    else "Drive link unavailable"
                )
                lines.append(f"{index}. {doc.filename} ({doc.document_type or 'Unknown'})")
                lines.append(drive_url)
            reply = "\n".join(lines)
        else:
            reply = "No matching documents found."

        return {
            "sender": sender,
            "status": "searched",
            "requested": requested,
            "count": len(docs),
            "reply": reply,
        }

    processed = []
    for index in range(num_media):
        media_url = form.get(f"MediaUrl{index}")
        mime_type = form.get(f"MediaContentType{index}")
        logger.info("Twilio WhatsApp media sender=%s mime_type=%s", sender, mime_type)

        file_path, filename, mime_type = download_twilio_media(
            media_url,
            mime_type,
            fallback_filename=f"twilio_whatsapp_{index}{SUPPORTED_MEDIA_TYPES.get(mime_type, '')}",
        )
        document = process_local_document(
            file_path=file_path,
            original_filename=filename,
            mime_type=mime_type,
            firm_id=client.firm_id,
            fallback_client=client,
        )
        processed.append(document)

    return {
        "sender": sender,
        "status": "processed",
        "count": len(processed),
        "reply": f"Received and saved {len(processed)} document(s).",
    }


def send_meta_text_message(to_number, text):
    token = os.getenv("TOKEN") or os.getenv("WHATSAPP_TOKEN") or os.getenv("META_WHATSAPP_TOKEN")
    phone_number_id = os.getenv("PHONE_NUMBER_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    if not token or not phone_number_id:
        logger.info("Meta WhatsApp reply skipped; token or phone_number_id missing")
        return

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": format_meta_recipient(to_number),
        "type": "text",
        "text": {"body": text},
    }

    response = requests.post(url, headers=headers, json=payload, timeout=20)
    response.raise_for_status()


def safe_send_meta_text_message(to_number, text):
    try:
        send_meta_text_message(to_number, text)
    except Exception:
        logger.exception("Meta WhatsApp reply failed sender=%s", to_number)


def process_meta_webhook_payload(payload):
    messages = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages.extend(value.get("messages", []))

    results = []
    for message in messages:
        sender = message.get("from")
        message_type = message.get("type")
        logger.info("WhatsApp webhook message sender=%s type=%s", sender, message_type)

        try:
            if message_type == "text":
                body = message.get("text", {}).get("body", "")
                client = find_client_by_phone(sender)
                if not client:
                    results.append({"sender": sender, "status": "no_client"})
                    safe_send_meta_text_message(sender, "No access / client not found")
                    continue

                _, requested, docs, error = search_client_documents(
                    sender,
                    body,
                    firm_id=client.firm_id,
                )
                results.append({
                    "sender": sender,
                    "status": "searched",
                    "requested": requested,
                    "count": len(docs),
                    "error": error,
                })
                if error:
                    safe_send_meta_text_message(sender, error)
                elif docs:
                    safe_send_meta_text_message(sender, f"Found {len(docs)} matching document(s).")
                else:
                    safe_send_meta_text_message(sender, "No matching documents found.")
                continue

            if message_type not in ("document", "image"):
                results.append({"sender": sender, "status": "unsupported", "type": message_type})
                continue

            media = message.get(message_type, {})
            media_id = media.get("id")
            if not media_id:
                results.append({"sender": sender, "status": "missing_media_id"})
                safe_send_meta_text_message(sender, "Could not process this file: media ID missing.")
                continue

            client = find_client_by_phone(sender)
            if not client:
                results.append({"sender": sender, "status": "no_client"})
                safe_send_meta_text_message(sender, "No access / client not found")
                continue

            file_path, filename, mime_type = download_meta_media(
                media_id,
                fallback_mime_type=media.get("mime_type"),
                fallback_filename=media.get("filename"),
            )
            document = process_local_document(
                file_path=file_path,
                original_filename=filename,
                mime_type=mime_type,
                firm_id=client.firm_id,
                fallback_client=client,
            )
            logger.info(
                "WhatsApp document processed sender=%s document_id=%s type=%s",
                sender,
                document.id,
                document.document_type,
            )
            results.append({"sender": sender, "status": "processed", "document_id": document.id})
            safe_send_meta_text_message(
                sender,
                f"Document received and saved as {document.document_type or 'Unknown'}.",
            )

        except Exception as exc:
            logger.exception("WhatsApp processing failed sender=%s type=%s", sender, message_type)
            db.session.rollback()
            results.append({"sender": sender, "status": "error", "error": str(exc)})
            safe_send_meta_text_message(sender, "Sorry, this WhatsApp document could not be processed.")

    return results
