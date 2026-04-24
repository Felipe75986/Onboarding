from google.oauth2 import service_account
from googleapiclient.discovery import build

from .config import SA_JSON_PATH, SCOPES


def build_drive():
    creds = service_account.Credentials.from_service_account_file(
        SA_JSON_PATH, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)
