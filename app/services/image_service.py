import cv2
import numpy as np
from fastapi import HTTPException, UploadFile, status


def _sniff_image_type(header: bytes) -> str | None:
    """Return 'jpeg' / 'png' from the first few magic bytes, or None."""
    if header[:2] == b"\xff\xd8":
        return "jpeg"
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


def validate_image_file(file: UploadFile, max_upload_mb: int) -> None:
    allowed_types = {"image/jpeg", "image/jpg", "image/png"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Use JPEG or PNG.",
        )


def bytes_to_bgr_image(image_bytes: bytes, max_upload_mb: int) -> np.ndarray:
    if len(image_bytes) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty image file")

    if len(image_bytes) > max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image too large. Max size is {max_upload_mb}MB.",
        )

    image_kind = _sniff_image_type(image_bytes[:12])
    if image_kind not in {"jpeg", "png"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image binary")

    np_buffer = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot decode image")

    return image
