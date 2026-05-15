from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import io

SCOPES = ['https://www.googleapis.com/auth/drive']

SERVICE_ACCOUNT_FILE = 'credentials.json'

FOLDER_ID = '1393m-1NMGrCwHnHo4_r_zTzfHCbGEBM2'

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES
)

service = build('drive', 'v3', credentials=credentials)


def upload_file(file_path, file_name):

    file_metadata = {
        'name': file_name,
        'parents': [FOLDER_ID]
    }

    media = MediaFileUpload(file_path, resumable=True)

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id,name'
    ).execute()

    return file


def list_files():

    results = service.files().list(
        q=f"'{FOLDER_ID}' in parents",
        fields="files(id, name)"
    ).execute()

    return results.get('files', [])


def download_file(file_id):

    request = service.files().get_media(fileId=file_id)

    file_data = io.BytesIO()

    downloader = MediaIoBaseDownload(file_data, request)

    done = False

    while done is False:
        status, done = downloader.next_chunk()

    file_data.seek(0)

    return file_data