import requests

TOKEN = EAAbGoKdx8w8BRWiYKdzZCYQ1g8ZCrnFMgDxK6ZADarZAwcmdj0k4o4rE5oQrUZB1jqMffnVn7PRZCPTUT59aJXARECoVUGs45VB9ZC9ZAiJWC94s2uaDHcbOdCpDPbzXZCZBdrsSsmh50jdg9eZBCcCGgjkZCKCZBSfewZCiX8qtxKQdMcqXHm21EbbL7M0jwZCFmHi02nL708QFt0bfsIoW9gAWKMK7vz23cxS1lAialHR1IfXMI1WZBLzONU1EsEIS5ijFpAh0ZCZAACC2Iiz1Vz8Glw9ifLQAA2eYkZD
PHONE_NUMBER_ID = 1134883416374630

url = f"https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/messages"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

payload = {
    "messaging_product": "whatsapp",
    "to": "917869863569",
    "type": "text",
    "text": {
        "body": "Hello from DocLedger AI"
    }
}

response = requests.post(url, headers=headers, json=payload)

print(response.status_code)
print(response.text)