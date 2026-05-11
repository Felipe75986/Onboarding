def clone_template(drive, template_id, parent_folder_id, name):
    body = {
        "name": name,
        "parents": [parent_folder_id],
    }
    return drive.files().copy(
        fileId=template_id, body=body, fields="id,name"
    ).execute()
