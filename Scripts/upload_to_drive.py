#!/usr/bin/env python3
"""
upload_to_drive.py

Module for uploading files or folders to Google Drive using a service account.
Supports recursive folder uploads, mirrored folder structure, and upload history.

Run as CLI:
  python3 upload_to_drive.py --file /path/to/file_or_folder --folder "https://drive.google.com/drive/folders/ABC123"

Or import:
  from upload_to_drive import upload_file
  upload_file("/path/to/file_or_folder", "ABC123")
"""

import os
import re
import json
import argparse
from datetime import datetime
from typing import Optional, Dict, Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# -------------------------
# Configuration
# -------------------------
SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
LOG_DIR = "serverLogs"                 # folder for logs
UPLOAD_HISTORY = os.path.join(LOG_DIR, "uploadHistory.log")

# -------------------------
# Helpers
# -------------------------
def extract_drive_id(folder_input: Optional[str]) -> Optional[str]:
    """Extract a Drive folder ID from URL, query param, or plain ID."""
    if not folder_input:
        return None
    s = folder_input.strip()
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", s)
    if m:
        return m.group(1)
    m2 = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", s)
    if m2:
        return m2.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", s):
        return s
    return None

def _get_drive_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(f"Service account file not found: {SERVICE_ACCOUNT_FILE}")
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def _ensure_log_dir():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)

def append_history(record: dict):
    """
    Append a JSON record to uploadHistory.log inside serverLog/.
    Automatically creates the folder if it doesn't exist.
    """
    _ensure_log_dir()
    timestamp = datetime.utcnow().isoformat() + "Z"
    record['logged_at'] = timestamp   # extra timestamp for when log was written
    with open(UPLOAD_HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")

# -------------------------
# Recursive folder upload
# -------------------------
_created_folders_cache = {}  # Avoid creating duplicate folders

def upload_folder(local_path: str, folder_input: Optional[str] = None) -> Dict[str, Any]:
    """
    Uploads a local folder recursively to Google Drive.
    Returns a dict mapping local file path -> upload info.
    """
    if not os.path.isdir(local_path):
        raise NotADirectoryError(f"Folder not found: {local_path}")

    service = _get_drive_service()
    parent_folder_id = extract_drive_id(folder_input)
    results = {}

    def create_drive_folder(name: str, parent_id: Optional[str] = None) -> str:
        """Create folder on Drive, return its ID, cache to avoid duplicates."""
        key = (name, parent_id)
        if key in _created_folders_cache:
            return _created_folders_cache[key]

        metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            metadata["parents"] = [parent_id]

        folder = service.files().create(
            body=metadata,
            fields="id",
            supportsAllDrives=True
        ).execute()
        folder_id = folder.get("id")
        _created_folders_cache[key] = folder_id
        return folder_id

    def _upload_dir(current_local_path: str, current_drive_id: str):
        for entry in os.listdir(current_local_path):
            full_path = os.path.join(current_local_path, entry)
            if os.path.isdir(full_path):
                new_drive_id = create_drive_folder(entry, current_drive_id)
                _upload_dir(full_path, new_drive_id)
            else:
                media = MediaFileUpload(full_path, resumable=True)
                metadata = {"name": entry, "parents": [current_drive_id]}
                try:
                    created = service.files().create(
                        body=metadata,
                        media_body=media,
                        fields="id, size",
                        supportsAllDrives=True
                    ).execute()
                    file_id = created.get("id")
                    file_url = f"https://drive.google.com/file/d/{file_id}/view"
                    results[full_path] = {
                        "drive_file_id": file_id,
                        "drive_file_url": file_url
                    }

                    # Log history
                    append_history({
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "local_path": os.path.abspath(full_path),
                        "local_size_bytes": os.path.getsize(full_path),
                        "drive_folder_id": current_drive_id,
                        "uploaded_file_id": file_id,
                        "uploaded_file_url": file_url,
                        "status": "success"
                    })

                except HttpError as e:
                    append_history({
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "local_path": os.path.abspath(full_path),
                        "local_size_bytes": os.path.getsize(full_path),
                        "drive_folder_id": current_drive_id,
                        "status": "error",
                        "error": str(e)
                    })
                    raise

    # Create root folder in Drive
    root_folder_name = os.path.basename(local_path.rstrip("/\\"))
    root_drive_id = create_drive_folder(root_folder_name, parent_folder_id)
    _upload_dir(local_path, root_drive_id)
    return results

# -------------------------
# Main upload function
# -------------------------
def upload_file(local_path: str, folder_input: Optional[str] = None, name_override: Optional[str] = None) -> Dict[str, Any]:
    """
    Uploads a file or folder to Google Drive.
    Returns upload info.
    """
    if os.path.isfile(local_path):
        service = _get_drive_service()
        folder_id = extract_drive_id(folder_input)
        file_name = name_override if name_override else os.path.basename(local_path)
        metadata = {"name": file_name}
        if folder_id:
            metadata["parents"] = [folder_id]

        media = MediaFileUpload(local_path, resumable=True)
        upload_time = datetime.utcnow().isoformat() + "Z"
        local_size = os.path.getsize(local_path)

        try:
            created = service.files().create(
                body=metadata,
                media_body=media,
                fields="id, size",
                supportsAllDrives=True
            ).execute()
            file_id = created.get("id")
            uploaded_size = created.get("size")
            file_url = f"https://drive.google.com/file/d/{file_id}/view" if file_id else None

            record = {
                "timestamp": upload_time,
                "local_path": os.path.abspath(local_path),
                "local_size_bytes": local_size,
                "drive_folder_id": folder_id,
                "uploaded_file_id": file_id,
                "uploaded_file_size": int(uploaded_size) if uploaded_size and uploaded_size.isdigit() else uploaded_size,
                "uploaded_file_url": file_url,
                "status": "success",
            }
            append_history(record)
            return record

        except HttpError as e:
            err = f"HttpError: {e}"
            record = {
                "timestamp": upload_time,
                "local_path": os.path.abspath(local_path),
                "local_size_bytes": local_size,
                "drive_folder_id": folder_id,
                "status": "error",
                "error": err,
            }
            append_history(record)
            raise RuntimeError(err)

    elif os.path.isdir(local_path):
        return upload_folder(local_path, folder_input)
    else:
        raise FileNotFoundError(f"Path not found: {local_path}")

# -------------------------
# CLI
# -------------------------
def main():
    parser = argparse.ArgumentParser(description="Upload file or folder to Google Drive using a service account.")
    parser.add_argument("--file", "-f", required=True, help="Local file or folder path to upload.")
    parser.add_argument("--folder", "-d", required=False, help="Drive folder URL or ID (optional).")
    parser.add_argument("--name", "-n", required=False, help="Optional name to set for the uploaded file.")
    args = parser.parse_args()

    try:
        res = upload_file(args.file, folder_input=args.folder, name_override=args.name)
        print(json.dumps({"ok": True, "result": res}, indent=2))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        raise SystemExit(1)

if __name__ == "__main__":
    main()
