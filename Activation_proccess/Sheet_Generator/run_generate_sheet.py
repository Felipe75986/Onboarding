import sys

from sheet_generator.cloner import clone_template
from sheet_generator.config import ROOT_FOLDER_ID, TEMPLATE_ID
from sheet_generator.google_client import build_drive


def main():
    if not ROOT_FOLDER_ID:
        sys.exit(
            "SHEET_ROOT_FOLDER_ID env var is required. "
            "Set it to a Drive folder ID the service account has Editor access to."
        )
    drive = build_drive()
    clone = clone_template(drive, TEMPLATE_ID, ROOT_FOLDER_ID)
    url = f"https://docs.google.com/spreadsheets/d/{clone['id']}/edit"
    print(f"Cloned: {url}")


if __name__ == "__main__":
    main()
