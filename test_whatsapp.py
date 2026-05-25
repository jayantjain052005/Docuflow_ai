import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
from_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

client = Client(account_sid, auth_token)

message = client.messages.create(
    from_=from_number,
    to="whatsapp:+916264705691",
    body="Hello from DocLedger Twilio WhatsApp test"
)

print("Message sent:", message.sid)
print("Status:", message.status)
