from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import os
import io

SCOPES = ['https://www.googleapis.com/auth/drive.file']

FOLDER_ID = '1393m-1NMGrCwHnHo4_r_zTzfHCbGEBM2'

_service = None


def authenticate():

    creds = None

    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file(
            'token.json',
            SCOPES
        )

    if not creds or not creds.valid:

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secret.json',
                SCOPES
            )

            creds = flow.run_local_server(port=0)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('drive', 'v3', credentials=creds)


def get_service():

    global _service

    if _service is None:
        _service = authenticate()

    return _service


# ---------------------------------------------------------
# Find or create folder
# ---------------------------------------------------------

def get_or_create_folder(
    folder_name,
    parent_id=None
):

    service = get_service()

    query = (
        f"name='{folder_name}' "
        "and mimeType='application/vnd.google-apps.folder' "
        "and trashed=false"
    )

    if parent_id:

        query += (
            f" and '{parent_id}' in parents"
        )

    results = service.files().list(
        q=query,
        fields="files(id,name)"
    ).execute()

    folders = results.get(
        "files",
        []
    )

    # Folder already exists
    if folders:

        return folders[0]["id"]

    # Create new folder
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }

    if parent_id:

        metadata["parents"] = [parent_id]

    folder = service.files().create(
        body=metadata,
        fields="id"
    ).execute()

    return folder["id"]

def upload_file(file_storage):

    service = get_service()

    file_metadata = {
        'name': file_storage.filename,
        'parents': [FOLDER_ID]
    }

    file_bytes = io.BytesIO(file_storage.read())

    media = MediaIoBaseUpload(
        file_bytes,
        mimetype=file_storage.mimetype,
        resumable=True
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id,name'
    ).execute()

    return file

# ---------------------------------------------------------
# Upload file into specific folder
# ---------------------------------------------------------

def upload_file_to_folder(
    file_path,
    filename,
    folder_id,
    mime_type="application/pdf"
):

    service = get_service()

    metadata = {
        "name": filename,
        "parents": [folder_id]
    }

    with open(file_path, "rb") as f:

        media = MediaIoBaseUpload(
            io.BytesIO(f.read()),
            mimetype=mime_type,
            resumable=True
        )

        uploaded = service.files().create(
            body=metadata,
            media_body=media,
            fields="id,name"
        ).execute()

    return uploaded
# ---------------------------------------------------------
# Move folder to another parent
# ---------------------------------------------------------

def move_folder(
    folder_id,
    new_parent_id
):

    service = get_service()

    file = service.files().get(
        fileId=folder_id,
        fields="parents"
    ).execute()

    previous_parents = ",".join(
        file.get("parents")
    )

    updated = service.files().update(
        fileId=folder_id,
        addParents=new_parent_id,
        removeParents=previous_parents,
        fields="id, parents"
    ).execute()

    return updated
def list_files():

    service = get_service()

    results = service.files().list(
        q=f"'{FOLDER_ID}' in parents",
        fields="files(id,name)"
    ).execute()

    return results.get('files', [])
def get_file_link(file_id):

    service = get_service()

    file = service.files().get(
        fileId=file_id,
        fields='webViewLink, webContentLink'
    ).execute()

    return file

def delete_drive_file(file_id):

    service = get_service()

    service.files().delete(
        fileId=file_id
    ).execute()


def move_file_to_folder(
    file_id,
    folder_id
):

    service = get_service()

    file = service.files().get(
        fileId=file_id,
        fields="parents"
    ).execute()

    previous_parents = ",".join(
        file.get("parents", [])
    )

    service.files().update(
        fileId=file_id,
        addParents=folder_id,
        removeParents=previous_parents,
        fields="id, parents"
    ).execute()
