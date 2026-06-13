"""
Cloudinary integration for gallery photo storage.
Replaces Google Drive \u2014 simpler auth, better thumbnail URLs.
Free tier: 25 GB storage + 25 GB bandwidth/month.
"""
from __future__ import annotations

from pathlib import Path

_MIME_MAP = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}


def _get_client(cloud_name: str, api_key: str, api_secret: str):
    import cloudinary  # type: ignore
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )
    return cloudinary


def upload_photo(
    file_bytes: bytes,
    filename: str,
    student_code: str,
    cloud_name: str,
    api_key: str,
    api_secret: str,
) -> dict:
    """
    Upload *file_bytes* to Cloudinary under attendance/{student_code}/.
    Returns {"file_id", "thumb_url", "view_url"}.
    """
    import cloudinary.uploader  # type: ignore

    _get_client(cloud_name, api_key, api_secret)
    stem = Path(filename).stem

    result = cloudinary.uploader.upload(
        file_bytes,
        folder=f"attendance/{student_code}",
        public_id=stem,
        overwrite=False,          # skip if already exists
        resource_type="image",
    )

    public_id  = result["public_id"]
    secure_url = result["secure_url"]

    # Generate a 400-wide thumbnail URL using Cloudinary transformations
    thumb_url = secure_url.replace("/upload/", "/upload/w_400,c_limit/")

    return {
        "file_id":   public_id,
        "thumb_url": thumb_url,
        "view_url":  secure_url,
    }


def list_photos(
    student_code: str,
    cloud_name: str,
    api_key: str,
    api_secret: str,
) -> list[dict]:
    """Return metadata for all photos stored in Cloudinary for *student_code*."""
    import cloudinary.api  # type: ignore

    _get_client(cloud_name, api_key, api_secret)

    try:
        resp = cloudinary.api.resources(
            type="upload",
            prefix=f"attendance/{student_code}/",
            max_results=500,
        )
    except Exception:
        return []

    results = []
    for resource in resp.get("resources", []):
        secure_url = resource["secure_url"]
        thumb_url  = secure_url.replace("/upload/", "/upload/w_400,c_limit/")
        results.append({
            "name":      Path(resource["public_id"]).name,
            "source":    "cloudinary",
            "file_id":   resource["public_id"],
            "thumb_url": thumb_url,
            "view_url":  secure_url,
        })

    return results


def get_folder_url(student_code: str, cloud_name: str) -> str:
    """Return the Cloudinary media library URL for the student folder."""
    return f"https://console.cloudinary.com/console/media_library/folders/attendance/{student_code}"
