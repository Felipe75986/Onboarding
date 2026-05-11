from .cell_map import ONBOARDING_METADATA_CELLS
from .config import ONBOARDING_TAB


def fill_onboarding_metadata(sheets, spreadsheet_id, inputs):
    data = []
    for cell, field_name in ONBOARDING_METADATA_CELLS.items():
        data.append({
            "range": f"{ONBOARDING_TAB}!{cell}",
            "values": [[getattr(inputs, field_name)]],
        })
    body = {"valueInputOption": "USER_ENTERED", "data": data}
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()


def _deployment_names(inputs):
    if inputs.mode == "chassis":
        return [
            f"{inputs.chassis_name}-node{i}"
            for i in range(1, inputs.server_count + 1)
        ]
    return [f"{inputs.platform}-ru{ru}" for ru in inputs.positions]


def fill_onboarding_devices(sheets, spreadsheet_id, inputs):
    names = _deployment_names(inputs)
    rows = []
    for i in range(inputs.server_count):
        ru = inputs.positions[i] if inputs.mode == "individual" else ""
        rows.append([names[i], "", inputs.cluster, inputs.device_type, ru])

    start_row = 9
    end_row = start_row + inputs.server_count - 1
    body = {
        "valueInputOption": "USER_ENTERED",
        "data": [{
            "range": f"{ONBOARDING_TAB}!A{start_row}:E{end_row}",
            "values": rows,
        }],
    }
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()
