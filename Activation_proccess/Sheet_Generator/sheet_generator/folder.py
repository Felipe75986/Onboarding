def ensure_site_folder(drive, root_folder_id, site):
    query = (
        f"'{root_folder_id}' in parents "
        f"and name = '{site}' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    result = drive.files().list(q=query, fields="files(id,name)").execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]

    body = {
        "name": site,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [root_folder_id],
    }
    folder = drive.files().create(body=body, fields="id").execute()
    return folder["id"]
