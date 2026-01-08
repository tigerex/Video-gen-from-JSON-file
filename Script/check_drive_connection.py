import os
import tempfile
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# =====================
# DEFAULT CONFIG (can be overridden later)
# =====================
SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = "service_account.json"
ROOT_PARENT_FOLDER_ID = "0AJE_ev2xV-qHUk9PVA"  # Target Drive folder ID

# =====================
# AUTH / SERVICE
# =====================
def authenticate(
    service_account_file: str = SERVICE_ACCOUNT_FILE,
    scopes: list = SCOPES,
):
    """Authenticate using a service account JSON file."""
    return service_account.Credentials.from_service_account_file(
        service_account_file,
        scopes=scopes,
    )


def get_drive_service(
    service_account_file: str = SERVICE_ACCOUNT_FILE,
    scopes: list = SCOPES,
):
    """Build and return the Drive API service."""
    creds = authenticate(service_account_file, scopes)
    return build("drive", "v3", credentials=creds)


# =====================
# CORE DRIVE HELPERS
# =====================
created_folders_cache = {}


def create_drive_folder(service, folder_name, parent_id):
    """Create a folder on Drive and return its ID (cached)."""
    cache_key = (folder_name, parent_id)
    if cache_key in created_folders_cache:
        return created_folders_cache[cache_key]

    file_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }

    folder = service.files().create(
        body=file_metadata,
        fields="id",
        supportsAllDrives=True,
    ).execute()

    folder_id = folder["id"]
    created_folders_cache[cache_key] = folder_id
    return folder_id


def upload_file(service, file_path, parent_id):
    """Upload a single file to Drive and return its file ID."""
    media = MediaFileUpload(file_path, resumable=True)

    file_metadata = {
        "name": os.path.basename(file_path),
        "parents": [parent_id],
    }

    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    ).execute()

    return uploaded["id"]


def delete_file(service, file_id):
    """Delete a file from Drive."""
    service.files().delete(
        fileId=file_id,
        supportsAllDrives=True,
    ).execute()


# =====================
# ACCESS CHECK FUNCTION
# =====================
def check_drive_access(
    parent_folder_id: str = ROOT_PARENT_FOLDER_ID,
    service_account_file: str = SERVICE_ACCOUNT_FILE,
) -> bool:
    """
    Check whether the service account can access the target Drive folder.

    Strategy:
    - Create a temporary local file
    - Upload it to the target Drive folder
    - Immediately delete it if upload succeeds

    Returns:
        True  -> access confirmed
        False -> access denied or error
    """
    service = get_drive_service(service_account_file)

    tmp_file_path = None
    uploaded_file_id = None

    try:
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
            tmp.write(b"Drive access check")
            tmp_file_path = tmp.name

        # Upload temp file
        uploaded_file_id = upload_file(
            service,
            tmp_file_path,
            parent_folder_id,
        )

        # Delete uploaded file
        delete_file(service, uploaded_file_id)

        return True

    except Exception as e:
        print("Drive access check failed:")
        print(e)
        return False

    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)


# =====================
# UPLOAD LOGIC (not in use in this file)
# =====================
def upload_folder_recursive(service, local_folder_path, parent_drive_id):
    for item in os.listdir(local_folder_path):
        local_path = os.path.join(local_folder_path, item)

        if os.path.isdir(local_path):
            new_drive_folder_id = create_drive_folder(
                service, item, parent_drive_id
            )
            upload_folder_recursive(service, local_path, new_drive_folder_id)
        else:
            upload_file(service, local_path, parent_drive_id)


def upload_full_structure(
    local_folder_path,
    parent_folder_id: str = ROOT_PARENT_FOLDER_ID,
):
    service = get_drive_service()

    root_folder_name = os.path.basename(local_folder_path.rstrip("/\\"))
    root_drive_folder_id = create_drive_folder(
        service, root_folder_name, parent_folder_id
    )

    upload_folder_recursive(
        service,
        local_folder_path,
        root_drive_folder_id,
    )

    print("Upload completed.")
