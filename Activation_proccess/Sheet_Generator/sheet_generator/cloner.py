from datetime import datetime


def clone_template(drive, template_id, parent_folder_id):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = {
        "name": f"activation-test-clone {timestamp}",
        "parents": [parent_folder_id],
    }
    return drive.files().copy(
        fileId=template_id, body=body, fields="id,name"
    ).execute()
