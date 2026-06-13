"""
Google Drive integration for gallery photo storage.
Photos are uploaded to a per-student subfolder inside a shared Drive folder
and made publicly readable so thumbnails load without auth tokens.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

_MIME_MAP = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".mp4":  "video/mp4",
}
_SCOPES = ["https://www.googleapis.com/auth/drive"]


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_service(credentials_json: str):
    from google.oauth2 import service_account  # type: ignore
    from googleapiclient.discovery import build  # type: ignore

    info = json.loads(credentials_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=_SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Return the Drive folder ID for *name* inside *parent_id*, creating if absent."""
    q = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    resp = service.files().list(q=q, fields="files(id)", pageSize=1).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]

    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def _make_public(service, file_id: str) -> None:
    """Grant anyone-reader permission so thumbnails load without authentication."""
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()


def _photo_urls(file_id: str) -> dict:
    return {
        "file_id":   file_id,
        "thumb_url": f"https://drive.google.com/thumbnail?id={file_id}&sz=w400",
        "view_url":  f"https://drive.google.com/file/d/{file_id}/view",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def upload_photo(
    file_bytes: bytes,
    filename: str,
    student_code: str,
    credentials_json: str,
    drive_folder_id: str,
) -> dict:
    """
    Upload *file_bytes* as *filename* under a per-student subfolder in Drive.
    Skips upload if a file with the same name already exists.
    Returns {"file_id", "thumb_url", "view_url"}.
    """
    from googleapiclient.http import MediaIoBaseUpload  # type: ignore

    service   = _build_service(credentials_json)
    folder_id = _get_or_create_folder(service, student_code, drive_folder_id)

    # Avoid duplicates
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    existing = (
        service.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
    )
    if existing:
        return _photo_urls(existing[0]["id"])

    ext       = Path(filename).suffix.lower()
    mime_type = _MIME_MAP.get(ext, "image/jpeg")
    file_meta = {"name": filename, "parents": [folder_id]}
    media     = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=False)
    uploaded  = service.files().create(
        body=file_meta, media_body=media, fields="id"
    ).execute()
    file_id   = uploaded["id"]
    _make_public(service, file_id)
    return _photo_urls(file_id)


def list_photos(
    student_code: str,
    credentials_json: str,
    drive_folder_id: str,
) -> list[dict]:
    """Return metadata for all photos stored in Drive for *student_code*."""
    service = _build_service(credentials_json)

    q = (
        f"name='{student_code}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{drive_folder_id}' in parents and trashed=false"
    )
    resp    = service.files().list(q=q, fields="files(id)", pageSize=1).execute()
    folders = resp.get("files", [])
    if not folders:
        return []

    folder_id = folders[0]["id"]
    q2        = f"'{folder_id}' in parents and trashed=false"
    resp2     = service.files().list(
        q=q2,
        fields="files(id,name)",
        orderBy="createdTime desc",
        pageSize=1000,
    ).execute()

    return [
        {
            "name":      f["name"],
            "source":    "drive",
            **_photo_urls(f["id"]),
        }
        for f in resp2.get("files", [])
    ]


def get_student_folder_url(
    student_code: str,
    credentials_json: str,
    drive_folder_id: str,
) -> str | None:
    """Return the Drive folder browse-URL for *student_code*, or None if not created yet."""
    service = _build_service(credentials_json)
    q = (
        f"name='{student_code}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{drive_folder_id}' in parents and trashed=false"
    )
    resp    = service.files().list(q=q, fields="files(id)", pageSize=1).execute()
    folders = resp.get("files", [])
    return f"https://drive.google.com/drive/folders/{folders[0]['id']}" if folders else None
