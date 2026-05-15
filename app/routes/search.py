"""
DocuFlow AI - Search Routes
Searches current firm's documents.
"""

from types import SimpleNamespace

from flask import Blueprint, render_template, request, session
from sqlalchemy import or_

from app.models.client import Client
from app.models.document import Document
from app.services.groq_service import understand_search_query
from app.utils.access_control import login_required

search_bp = Blueprint("search", __name__)


def _to_search_result(document, client_name=None):
    return SimpleNamespace(
        id=document.id,
        file_id=document.id,
        filename=document.filename,
        document_type=document.document_type,
        summary=(document.extracted_json or {}).get("summary", ""),
        upload_date=document.uploaded_at.isoformat() if document.uploaded_at else "",
        detected_year=document.assessment_year,
        owner_name=client_name or "Unlinked",
        permission="owner",
    )


def _run_search(term):
    like = f"%{term}%"
    rows = (
        Document.query
        .outerjoin(Client, Document.client_id == Client.id)
        .filter(Document.firm_id == session["firm_id"])
        .filter(
            or_(
                Document.filename.ilike(like),
                Document.document_type.ilike(like),
                Document.extracted_text.ilike(like),
                Client.client_name.ilike(like),
                Client.pan_number.ilike(like),
            )
        )
        .order_by(Document.uploaded_at.desc())
        .limit(50)
        .with_entities(Document, Client.client_name)
        .all()
    )
    return [_to_search_result(document, client_name) for document, client_name in rows]


@search_bp.route("/search")
@login_required
def search():
    query = request.args.get("q", "").strip()
    results = []
    interpreted = None

    if query:
        results = _run_search(query)

        if not results:
            keywords = understand_search_query(query)
            interpreted = keywords
            if keywords and keywords != query:
                seen = set()
                expanded = []
                for part in keywords.split():
                    for result in _run_search(part):
                        if result.id not in seen:
                            seen.add(result.id)
                            expanded.append(result)
                results = expanded

    return render_template(
        "search.html",
        query=query,
        results=results,
        interpreted=interpreted,
    )
