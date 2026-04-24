from sheet_generator.cloner import clone_template
from sheet_generator.config import TEMPLATE_ID
from sheet_generator.google_client import build_drive


def main():
    drive = build_drive()
    clone = clone_template(drive, TEMPLATE_ID)
    url = f"https://docs.google.com/spreadsheets/d/{clone['id']}/edit"
    print(f"Cloned: {url}")


if __name__ == "__main__":
    main()
