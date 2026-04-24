import os

TEMPLATE_ID = os.environ.get(
    "SHEET_TEMPLATE_ID",
    "1mpn2P4IoI00M5zRBDmj-Yz0rrl7MGVlHy0M4wD4tahU",
)

ROOT_FOLDER_ID = os.environ.get(
    "SHEET_ROOT_FOLDER_ID",
    "14hh4FKJoLmZZ0Nm2oZZipATknj-8xCSJ"
)

OAUTH_TOKEN_PATH = os.environ.get("OAUTH_TOKEN_PATH", "/secrets/token.json")

ONBOARDING_TAB = "Onboarding"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
