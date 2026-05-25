import logging

from flask import Blueprint, render_template, request, session
from app.services.whatsapp_service import (
    send_whatsapp_message
)
from app.services.whatsapp_document_workflow import (
    process_meta_webhook_payload,
    process_twilio_webhook_form,
    search_client_documents,
)
from app.utils.access_control import login_required

whatsapp_bp = Blueprint("whatsapp", __name__)
logger = logging.getLogger(__name__)


@whatsapp_bp.route("/whatsapp-docs", methods=["GET", "POST"])
@login_required
def whatsapp_docs():
    phone = ""
    message = ""
    error = None
    documents = []
    requested_types = []

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        message = request.form.get("message", "").strip()
        _, requested_types, documents, error = search_client_documents(
            phone,
            message,
            firm_id=session["firm_id"],
        )

    return render_template(
        "whatsapp_docs.html",
        phone=phone,
        message=message,
        error=error,
        documents=documents,
        requested_types=requested_types,
    )


@whatsapp_bp.route("/webhook", methods=["POST"])
def meta_whatsapp_webhook():
    payload = request.get_json(silent=True) or {}

    try:
        results = process_meta_webhook_payload(payload)
        logger.info("Meta WhatsApp webhook processed results=%s", results)
    except Exception:
        logger.exception("Unhandled WhatsApp webhook error")

    return "OK", 200


@whatsapp_bp.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    sender = request.form.get("From", "")

    try:
        result = process_twilio_webhook_form(request.form)
        logger.info("Twilio WhatsApp webhook processed result=%s", result)

        reply = result.get("reply")
        if sender and reply:
            send_whatsapp_message(sender, reply)

    except Exception:
        logger.exception("Unhandled Twilio WhatsApp webhook error sender=%s", sender)
        if sender:
            try:
                send_whatsapp_message(
                    sender,
                    "Sorry, this WhatsApp request could not be processed.",
                )
            except Exception:
                logger.exception("Twilio error reply failed sender=%s", sender)

    return "OK", 200
