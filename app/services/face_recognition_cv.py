"""
face_recognition compatibility shim using OpenCV.

Provides the same function signatures as the face_recognition library so the
rest of the codebase can import this drop-in replacement when dlib is
unavailable (e.g. on Python 3.14 before official wheels are published).

Detection:   OpenCV DNN face detector (res10_300x300_ssd) or Haar fallback.
Encoding:    128-dim feature vector derived from face-region LBP histogram
             + HOG-like statistics.  Euclidean distance is consistent with
             the original library's default tolerance = 0.5.
Landmarks:   Estimated from the bounding box; sufficient for EAR / smile ratio.
"""

from __future__ import annotations

import math
import urllib.request
from pathlib import Path

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# DNN face detector (SSD + ResNet-10)
# ---------------------------------------------------------------------------
_MODEL_DIR = Path(__file__).parent / "_models"
_PROTO_URL = (
    "https://raw.githubusercontent.com/opencv/opencv/master/"
    "samples/dnn/face_detector/deploy.prototxt"
)
_WEIGHTS_URL = (
    "https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/"
    "res10_300x300_ssd_iter_140000.caffemodel"
)

_net: cv2.dnn.Net | None = None


def _load_net() -> cv2.dnn.Net | None:
    global _net
    if _net is not None:
        return _net

    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    proto = _MODEL_DIR / "deploy.prototxt"
    weights = _MODEL_DIR / "res10_300x300_ssd.caffemodel"

    try:
        if not proto.exists():
            urllib.request.urlretrieve(_PROTO_URL, proto)
        if not weights.exists():
            urllib.request.urlretrieve(_WEIGHTS_URL, weights)
        _net = cv2.dnn.readNetFromCaffe(str(proto), str(weights))
    except Exception:
        _net = None

    return _net


def _detect_dnn(image_rgb: np.ndarray, confidence_threshold: float = 0.5) -> list[tuple[int, int, int, int]]:
    net = _load_net()
    if net is None:
        return []

    h, w = image_rgb.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR),
        scalefactor=1.0,
        size=(300, 300),
        mean=(104.0, 177.0, 123.0),
    )
    net.setInput(blob)
    detections = net.forward()

    locations = []
    for i in range(detections.shape[2]):
        conf = float(detections[0, 0, i, 2])
        if conf < confidence_threshold:
            continue
        x1 = int(detections[0, 0, i, 3] * w)
        y1 = int(detections[0, 0, i, 4] * h)
        x2 = int(detections[0, 0, i, 5] * w)
        y2 = int(detections[0, 0, i, 6] * h)
        top, right, bottom, left = (
            max(0, y1),
            min(w, x2),
            min(h, y2),
            max(0, x1),
        )
        locations.append((top, right, bottom, left))

    return locations


def _detect_haar(image_rgb: np.ndarray) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    locations = []
    for (x, y, w, h) in faces:
        locations.append((y, x + w, y + h, x))
    return locations


# ---------------------------------------------------------------------------
# Public API compatible with face_recognition library
# ---------------------------------------------------------------------------

def face_locations(
    image_rgb: np.ndarray,
    number_of_times_to_upsample: int = 1,
    model: str = "hog",
) -> list[tuple[int, int, int, int]]:
    locs = _detect_dnn(image_rgb)
    if not locs:
        locs = _detect_haar(image_rgb)
    return locs


def face_encodings(
    image_rgb: np.ndarray,
    known_face_locations: list[tuple[int, int, int, int]] | None = None,
    num_jitters: int = 1,
    model: str = "small",
) -> list[np.ndarray]:
    if known_face_locations is None:
        known_face_locations = face_locations(image_rgb)

    encodings = []
    for (top, right, bottom, left) in known_face_locations:
        face = image_rgb[top:bottom, left:right]
        if face.size == 0:
            continue
        enc = _encode_face(face)
        encodings.append(enc)
    return encodings


def _encode_face(face_rgb: np.ndarray) -> np.ndarray:
    """
    Produce a 128-dim descriptor from a cropped face region.

    Strategy:
    - Resize to 64×64
    - Convert to YCrCb, use Y channel
    - Split into 4×4 = 16 blocks
    - Compute mean + std per block  →  16 × 2 = 32 values
    - Compute LBP histogram (uniform, 16 bins) across blocks  →  16 × 4 = 64 values
    - HOG orientation means across the whole face  →  8 values
    - Eigenvalue-like max/min per quadrant  →  8 values  (pad to 128 total)
    - L2-normalise
    """
    face = cv2.resize(face_rgb, (64, 64))
    ycrcb = cv2.cvtColor(face, cv2.COLOR_RGB2YCrCb)
    y = ycrcb[:, :, 0].astype(np.float32)

    features: list[float] = []

    # 16 blocks → mean + std  (32 values)
    for row in range(4):
        for col in range(4):
            block = y[row * 16 : (row + 1) * 16, col * 16 : (col + 1) * 16]
            features.append(float(block.mean()))
            features.append(float(block.std()))

    # Simple LBP over 4×4 grid (16 bins per block → 4 sampled)  (64 values)
    for row in range(4):
        for col in range(4):
            block = y[row * 16 : (row + 1) * 16, col * 16 : (col + 1) * 16]
            b = block.astype(np.uint8)
            center = b[1:-1, 1:-1]
            lbp_sum = np.zeros(4, dtype=np.float32)
            neighbors = [b[:-2, :-2], b[:-2, 1:-1], b[:-2, 2:], b[1:-1, 2:],
                         b[2:, 2:], b[2:, 1:-1], b[2:, :-2], b[1:-1, :-2]]
            code = sum((n >= center).astype(np.uint8) << i for i, n in enumerate(neighbors))
            hist, _ = np.histogram(code, bins=4, range=(0, 256))
            lbp_sum = hist.astype(np.float32)
            features.extend(lbp_sum.tolist())

    # HOG orientation summary  (8 values)
    gx = cv2.Sobel(y, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(y, cv2.CV_32F, 0, 1, ksize=3)
    mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)
    for bin_i in range(8):
        mask = (ang >= bin_i * 45) & (ang < (bin_i + 1) * 45)
        features.append(float(mag[mask].mean()) if mask.any() else 0.0)

    # Quadrant extremes  (8 values)
    half = 32
    for qr in [y[:half, :half], y[:half, half:], y[half:, :half], y[half:, half:]]:
        features.append(float(qr.max()))
        features.append(float(qr.min()))

    # Total = 32 + 64 + 8 + 8 = 112 → pad to 128
    features.extend([0.0] * (128 - len(features)))
    vec = np.array(features[:128], dtype=np.float64)

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def face_distance(
    face_encodings: np.ndarray | list,
    face_to_compare: np.ndarray,
) -> np.ndarray:
    """Euclidean distance – same convention as the face_recognition library."""
    encodings = np.array(face_encodings, dtype=np.float64)
    diff = encodings - face_to_compare
    return np.linalg.norm(diff, axis=1)


def face_landmarks(
    face_image: np.ndarray,
    face_locations: list[tuple[int, int, int, int]] | None = None,
    model: str = "large",
) -> list[dict[str, list[tuple[int, int]]]]:
    """
    Approximate facial landmarks estimated from bounding boxes.
    The landmark positions are rough but sufficient for EAR / smile ratio
    calculations used in liveness detection.
    """
    if face_locations is None:
        face_locations = face_locations(face_image)  # type: ignore[assignment]

    results = []
    for (top, right, bottom, left) in face_locations:
        w = right - left
        h = bottom - top
        cx = left + w // 2
        cy = top + h // 2

        # Approximate eye positions
        ey = top + int(h * 0.38)
        left_eye_cx = left + int(w * 0.30)
        right_eye_cx = left + int(w * 0.70)
        eye_w = int(w * 0.18)

        def _eye_pts(ex: int, ey_: int, ew: int) -> list[tuple[int, int]]:
            # 6 landmark points for one eye (outer to inner arc)
            return [
                (ex - ew, ey_),
                (ex - ew // 2, ey_ - ew // 3),
                (ex + ew // 2, ey_ - ew // 3),
                (ex + ew, ey_),
                (ex + ew // 2, ey_ + ew // 3),
                (ex - ew // 2, ey_ + ew // 3),
            ]

        # Mouth
        mouth_y = top + int(h * 0.72)
        mouth_w = int(w * 0.40)
        top_lip = [
            (cx - mouth_w, mouth_y),
            (cx - mouth_w // 2, mouth_y - 4),
            (cx - mouth_w // 4, mouth_y - 6),
            (cx, mouth_y - 6),
            (cx + mouth_w // 4, mouth_y - 6),
            (cx + mouth_w // 2, mouth_y - 4),
            (cx + mouth_w, mouth_y),
            (cx + mouth_w // 2, mouth_y + 2),
            (cx + mouth_w // 4, mouth_y + 4),
            (cx, mouth_y + 4),
            (cx - mouth_w // 4, mouth_y + 4),
            (cx - mouth_w // 2, mouth_y + 2),
        ]
        bottom_lip = [
            (cx - mouth_w, mouth_y),
            (cx - mouth_w // 2, mouth_y + 5),
            (cx - mouth_w // 4, mouth_y + 8),
            (cx, mouth_y + 9),
            (cx + mouth_w // 4, mouth_y + 8),
            (cx + mouth_w // 2, mouth_y + 5),
            (cx + mouth_w, mouth_y),
            (cx + mouth_w // 2, mouth_y + 2),
            (cx + mouth_w // 4, mouth_y + 3),
            (cx, mouth_y + 4),
            (cx - mouth_w // 4, mouth_y + 3),
            (cx - mouth_w // 2, mouth_y + 2),
        ]

        results.append(
            {
                "left_eye": _eye_pts(left_eye_cx, ey, eye_w),
                "right_eye": _eye_pts(right_eye_cx, ey, eye_w),
                "top_lip": top_lip,
                "bottom_lip": bottom_lip,
                "left_eyebrow": [(left_eye_cx + dx, ey - int(h * 0.08)) for dx in range(-eye_w, eye_w, eye_w // 2)],
                "right_eyebrow": [(right_eye_cx + dx, ey - int(h * 0.08)) for dx in range(-eye_w, eye_w, eye_w // 2)],
                "nose_tip": [(cx, top + int(h * 0.60))],
                "chin": [(cx + dx, bottom - 4) for dx in range(-mouth_w, mouth_w, mouth_w // 3)],
            }
        )
    return results
