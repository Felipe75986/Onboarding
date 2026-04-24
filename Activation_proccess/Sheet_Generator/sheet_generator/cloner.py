from datetime import datetime


def clone_template(drive, template_id):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = {"name": f"activation-test-clone {timestamp}"}
    return drive.files().copy(
        fileId=template_id, body=body, fields="id,name"
    ).execute()
