from twilio.rest import Client
import os
from dotenv import load_dotenv
load_dotenv()
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

client = Client(ACCOUNT_SID, AUTH_TOKEN)

def send_whatsapp_message(to_number, text):

    message = client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=to_number,
        body=text
    )

    print("\nWHATSAPP TEXT SENT:")
    print(message.sid)
def send_whatsapp_document(to_number, media_url):

    message = client.messages.create(

        from_=TWILIO_WHATSAPP_NUMBER,

        to=to_number,

        body="Here is your requested document.",

        media_url=[media_url]

    )

    print("\nWHATSAPP SENT:")
    print(message.sid)

if __name__ == "__main__":

    send_whatsapp_document(
        "whatsapp:+916264705691",
        "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
    )
