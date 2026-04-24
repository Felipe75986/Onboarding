import sys

from sheet_generator.cloner import clone_template
from sheet_generator.config import ROOT_FOLDER_ID, TEMPLATE_ID
from sheet_generator.folder import ensure_site_folder
from sheet_generator.google_client import build_drive
from sheet_generator.inputs import read_inputs


def main():
    if not ROOT_FOLDER_ID:
        sys.exit(
            "SHEET_ROOT_FOLDER_ID env var is required. "
            "Set it to a Drive folder ID the service account has Editor access to."
        )
    inputs = read_inputs()
    drive = build_drive()
    site_folder_id = ensure_site_folder(drive, ROOT_FOLDER_ID, inputs.site)
    name = f"[{inputs.site}] {inputs.ticket}"
    clone = clone_template(drive, TEMPLATE_ID, site_folder_id, name)
    url = f"https://docs.google.com/spreadsheets/d/{clone['id']}/edit"
    print(f"Cloned: {url}")


if __name__ == "__main__":
    main()
