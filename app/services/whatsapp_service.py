import os

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

TWILIO_WHATSAPP_NUMBER = os.getenv(
    "TWILIO_WHATSAPP_NUMBER",
    "whatsapp:+14155238886",
)


def _get_twilio_client():
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token:
        raise RuntimeError("Twilio credentials are not configured")

    return Client(account_sid, auth_token)


def send_whatsapp_message(to_number, text):
    message = _get_twilio_client().messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=to_number,
        body=text,
    )

    print("\nWHATSAPP TEXT SENT:")
    print(message.sid)


def send_whatsapp_document(to_number, media_url):
    message = _get_twilio_client().messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=to_number,
        body="Here is your requested document.",
        media_url=[media_url],
    )

    print("\nWHATSAPP SENT:")
    print(message.sid)


if __name__ == "__main__":
    send_whatsapp_document(
        "whatsapp:+916264705691",
        "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
    )
