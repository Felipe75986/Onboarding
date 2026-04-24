from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import OAUTH_TOKEN_PATH, SCOPES


def build_drive():
    creds = Credentials.from_authorized_user_file(OAUTH_TOKEN_PATH, SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds)
