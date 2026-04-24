from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import OAUTH_TOKEN_PATH, SCOPES


def _credentials():
    creds = Credentials.from_authorized_user_file(OAUTH_TOKEN_PATH, SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    return creds


def build_drive():
    return build("drive", "v3", credentials=_credentials())


def build_sheets():
    return build("sheets", "v4", credentials=_credentials())
