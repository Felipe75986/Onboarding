import os

TEMPLATE_ID = os.environ.get(
    "SHEET_TEMPLATE_ID",
    "1mpn2P4IoI00M5zRBDmj-Yz0rrl7MGVlHy0M4wD4tahU",
)

SA_JSON_PATH = os.environ.get("GOOGLE_SA_JSON_PATH", "/secrets/sa.json")

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
