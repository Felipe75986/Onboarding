from .cell_map import ONBOARDING_METADATA_CELLS
from .config import ONBOARDING_TAB


def fill_onboarding_metadata(sheets, spreadsheet_id, inputs):
    data = []
    for cell, field in ONBOARDING_METADATA_CELLS.items():
        data.append({
            "range": f"{ONBOARDING_TAB}!{cell}",
            "values": [[getattr(inputs, field)]],
        })
    body = {"valueInputOption": "USER_ENTERED", "data": data}
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()
