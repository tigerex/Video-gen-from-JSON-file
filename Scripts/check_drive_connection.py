import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = 'service_account.json'
ROOT_PARENT_FOLDER_ID = "0AJE_ev2xV-qHUk9PVA"   # The Drive folder where the root will be uploaded

def authenticate():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return creds

def get_drive_service():
    creds = authenticate()
    return build('drive', 'v3', credentials=creds)

# Cache so we don't create duplicate folders if visited twice
created_folders_cache = {}

def create_drive_folder(service, folder_name, parent_id):
    """Create a folder on Drive and return its ID."""
    # Prevent duplicate folder creation under same parent
    cache_key = (folder_name, parent_id)
    if cache_key in created_folders_cache:
        return created_folders_cache[cache_key]

    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }

    folder = service.files().create(
        body=file_metadata,
        fields='id',
        supportsAllDrives=True
    ).execute()

    folder_id = folder.get('id')
    created_folders_cache[cache_key] = folder_id
    return folder_id

def upload_file(service, file_path, parent_id):
    """Upload a single file to Drive."""
    filename = os.path.basename(file_path)
    media = MediaFileUpload(file_path, resumable=True)

    file_metadata = {
        'name': filename,
        'parents': [parent_id]
    }

    service.files().create(
        body=file_metadata,
        media_body=media,
        supportsAllDrives=True
    ).execute()

    print(f"Uploaded file: {file_path}")

def upload_folder_recursive(service, local_folder_path, parent_drive_id):
    """Recursively upload folder structure and files."""
    for item in os.listdir(local_folder_path):
        local_path = os.path.join(local_folder_path, item)

        if os.path.isdir(local_path):
            # Create folder on Drive
            print(f"Creating folder on Drive: {item}")
            new_drive_folder_id = create_drive_folder(service, item, parent_drive_id)

            # Recurse into subfolder
            upload_folder_recursive(service, local_path, new_drive_folder_id)

        else:
            # Upload file
            upload_file(service, local_path, parent_drive_id)

def upload_full_structure(local_folder_path):
    service = get_drive_service()

    # Create top-level folder inside the parent Drive folder
    root_folder_name = os.path.basename(local_folder_path.rstrip("/\\"))
    root_drive_folder_id = create_drive_folder(service, root_folder_name, ROOT_PARENT_FOLDER_ID)

    upload_folder_recursive(service, local_folder_path, root_drive_folder_id)

    print("\nUpload completed.")

# Example:
upload_full_structure("Output/final_output_2025-11-21_02-55-12")
