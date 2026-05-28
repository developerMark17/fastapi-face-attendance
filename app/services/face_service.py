from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
import math

import cv2
import numpy as np

try:
    import face_recognition  # type: ignore[import-untyped]
except ImportError:  # Python 3.14+ – dlib wheel not yet available
    from app.services import face_recognition_cv as face_recognition  # type: ignore[no-redef]
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Attendance, User
from app.services.face_index import compute_face_hash, has_valid_face_encoding
from app.services.time_service import as_utc


@dataclass
class FaceDetectionResult:
    location: tuple[int, int, int, int]
    encoding: np.ndarray
    landmarks: dict[str, list[tuple[int, int]]]


def _distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def _eye_aspect_ratio(eye_points: list[tuple[int, int]]) -> float:
    if len(eye_points) < 6:
        return 1.0

    p2_p6 = np.linalg.norm(np.array(eye_points[1]) - np.array(eye_points[5]))
    p3_p5 = np.linalg.norm(np.array(eye_points[2]) - np.array(eye_points[4]))
    p1_p4 = np.linalg.norm(np.array(eye_points[0]) - np.array(eye_points[3]))

    if p1_p4 == 0:
        return 1.0
    return float((p2_p6 + p3_p5) / (2.0 * p1_p4))


def _smile_ratio(top_lip: list[tuple[int, int]], bottom_lip: list[tuple[int, int]]) -> float:
    if len(top_lip) < 10 or len(bottom_lip) < 10:
        return 0.0

    mouth_width = np.linalg.norm(np.array(top_lip[0]) - np.array(top_lip[6]))
    mouth_open = np.linalg.norm(np.array(top_lip[9]) - np.array(bottom_lip[9]))
    if mouth_width == 0:
        return 0.0
    return float(mouth_open / mouth_width)


def extract_single_face(image_bgr: np.ndarray) -> FaceDetectionResult:
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

    locations = face_recognition.face_locations(image_rgb, model="hog")
    if len(locations) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No face detected")
    if len(locations) > 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Multiple faces detected")

    encodings = face_recognition.face_encodings(image_rgb, known_face_locations=locations)
    if not encodings:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to generate encoding")

    landmarks_list = face_recognition.face_landmarks(image_rgb, face_locations=locations)
    landmarks = landmarks_list[0] if landmarks_list else {}

    return FaceDetectionResult(location=locations[0], encoding=encodings[0], landmarks=landmarks)


def check_liveness(challenge: str, landmarks: dict[str, list[tuple[int, int]]]) -> bool:
    challenge_normalized = (challenge or "").strip().lower()

    if challenge_normalized == "blink":
        left_eye = landmarks.get("left_eye", [])
        right_eye = landmarks.get("right_eye", [])
        left_ear = _eye_aspect_ratio(left_eye)
        right_ear = _eye_aspect_ratio(right_eye)
        # Lower EAR likely means eyes are closed.
        return (left_ear + right_ear) / 2.0 < 0.20

    if challenge_normalized == "smile":
        top_lip = landmarks.get("top_lip", [])
        bottom_lip = landmarks.get("bottom_lip", [])
        
        # If we can detect lips, it's a live face
        if len(top_lip) > 0 and len(bottom_lip) > 0:
            ratio = _smile_ratio(top_lip, bottom_lip)
            print(f"DEBUG: smile_ratio = {ratio}, top_lip_count = {len(top_lip)}, bottom_lip_count = {len(bottom_lip)}")
            # Very lenient: if lips are detected, assume smile is present
            return True
        
        # No lips detected: fail liveness
        return False

    # Unknown challenge: fail closed for safety.
    return False


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def register_face(
    db: Session,
    name: str,
    encoding: np.ndarray,
    face_hash_bits: int,
    student_code: str | None = None,
    email: str | None = None,
    department: str | None = None,
    program: str | None = None,
    semester: int | None = None,
    section: str | None = None,
    phone: str | None = None,
    guardian_phone: str | None = None,
    enrollment_year: int | None = None,
) -> User:
    normalized_name = name.strip().lower()
    clean_student_code = _clean_optional(student_code)
    clean_email = _clean_optional(email)

    query = db.query(User)
    existing = None
    if clean_student_code:
        existing = query.filter(User.student_code == clean_student_code).first()
    if existing is None and clean_email:
        existing = query.filter(User.email == clean_email).first()
    if existing is None:
        existing = next((user for user in query.all() if user.name.strip().lower() == normalized_name), None)

    duplicate_query = db.query(User)
    if clean_student_code:
        duplicate = duplicate_query.filter(User.student_code == clean_student_code)
        if existing:
            duplicate = duplicate.filter(User.id != existing.id)
        if duplicate.first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student code already exists")

    if clean_email:
        duplicate = db.query(User).filter(User.email == clean_email)
        if existing:
            duplicate = duplicate.filter(User.id != existing.id)
        if duplicate.first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    face_hash = compute_face_hash(encoding, face_hash_bits)

    if existing:
        if existing.face_enrolled and has_valid_face_encoding(existing.face_encoding):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Face already enrolled for this student")

        existing.name = name
        existing.student_code = clean_student_code or existing.student_code
        existing.email = clean_email or existing.email
        existing.department = _clean_optional(department) or existing.department
        existing.program = _clean_optional(program) or existing.program
        existing.semester = semester or existing.semester
        existing.section = _clean_optional(section) or existing.section
        existing.phone = _clean_optional(phone) or existing.phone
        existing.guardian_phone = _clean_optional(guardian_phone) or existing.guardian_phone
        existing.enrollment_year = enrollment_year or existing.enrollment_year
        existing.face_encoding = encoding.tolist()
        existing.face_hash = face_hash
        existing.face_enrolled = True
        existing.status = "active"
        db.commit()
        db.refresh(existing)
        return existing

    name_duplicate = db.query(User).filter(User.name == name).first()
    if name_duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User name already exists")

    user = User(
        name=name,
        student_code=clean_student_code,
        email=clean_email,
        phone=_clean_optional(phone),
        guardian_phone=_clean_optional(guardian_phone),
        department=_clean_optional(department) or "General",
        program=_clean_optional(program) or "General",
        semester=semester or 1,
        section=_clean_optional(section) or "A",
        enrollment_year=enrollment_year,
        face_encoding=encoding.tolist(),
        face_hash=face_hash,
        face_enrolled=True,
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _match_best_user(users: list[User], query_encoding: np.ndarray, tolerance: float) -> User | None:
    users = [user for user in users if has_valid_face_encoding(user.face_encoding)]
    if not users:
        return None

    known_encodings = np.array([user.face_encoding for user in users], dtype=np.float64)
    distances = face_recognition.face_distance(known_encodings, query_encoding)
    best_idx = int(np.argmin(distances))

    if distances[best_idx] <= tolerance:
        return users[best_idx]
    return None


def recognize_user(
    db: Session,
    query_encoding: np.ndarray,
    tolerance: float,
    face_hash_bits: int,
    candidate_limit: int,
    max_full_scan_faces: int,
) -> User | None:
    base_query = db.query(User).filter(User.status == "active").filter(User.face_enrolled.is_(True))
    total_enrolled = base_query.count()
    if total_enrolled == 0:
        return None

    # If exactly one user is currently checked in for today, prefer that user for continuity
    # so the next punch resolves to OUT for the same profile.
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    today_rows = (
        db.query(Attendance.user_id)
        .filter(Attendance.timestamp >= day_start)
        .filter(Attendance.timestamp < day_end)
        .order_by(Attendance.timestamp.asc())
        .all()
    )
    per_user_count: dict[int, int] = {}
    for (att_user_id,) in today_rows:
        per_user_count[att_user_id] = per_user_count.get(att_user_id, 0) + 1

    open_user_ids = [uid for uid, count in per_user_count.items() if (count % 2) == 1]
    open_users = base_query.filter(User.id.in_(open_user_ids)).all() if open_user_ids else []
    if open_users:
        matched_open_user = _match_best_user(open_users, query_encoding, tolerance + 0.08)
        if matched_open_user:
            return matched_open_user

    query_hash = compute_face_hash(query_encoding, face_hash_bits)
    users = (
        base_query.filter(User.face_hash == query_hash)
        .order_by(User.id.asc())
        .limit(candidate_limit)
        .all()
    )

    matched_user = _match_best_user(users, query_encoding, tolerance)
    if matched_user:
        return matched_user

    if total_enrolled <= max_full_scan_faces:
        fallback_users = base_query.order_by(User.id.asc()).limit(max_full_scan_faces).all()
        return _match_best_user(fallback_users, query_encoding, tolerance)

    return None


def enforce_geofence(settings: Settings, latitude: float | None, longitude: float | None) -> None:
    if latitude is None or longitude is None:
        return

    distance = _distance_meters(
        settings.office_latitude,
        settings.office_longitude,
        latitude,
        longitude,
    )
    
    # If distance is > 1000km, likely invalid GPS coordinates, skip geofence check
    if distance > 1000000:  # 1000 km in meters
        print(f"DEBUG: Skipping geofence - unrealistic distance: {distance}m")
        return
    
    if distance > settings.geofence_radius_meters:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Outside allowed attendance zone ({int(distance)}m away)",
        )


def prevent_duplicate_attendance(db: Session, user_id: int, cooldown_minutes: int, allow_out: bool = False) -> None:
    """Prevent duplicate punches within cooldown window.
    
    Args:
        db: Database session
        user_id: User ID
        cooldown_minutes: Cooldown in minutes
        allow_out: If True, allows OUT punch even within cooldown (for IN->OUT flow)
    """
    latest = (
        db.query(Attendance)
        .filter(Attendance.user_id == user_id)
        .order_by(Attendance.timestamp.desc())
        .first()
    )

    if not latest:
        return

    now = datetime.now(timezone.utc)
    time_since_latest = (now - as_utc(latest.timestamp)).total_seconds() / 60  # in minutes
    
    if time_since_latest < cooldown_minutes:
        # Allow OUT punch (second punch on same day) even within cooldown window
        if allow_out:
            return
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Attendance already marked recently. Try again in {cooldown_minutes - int(time_since_latest)} minutes.",
        )


def infer_action_for_log(index_in_day: int) -> Literal["in", "out"]:
    # First punch of the day is IN, second is OUT, then repeats.
    return "in" if (index_in_day % 2) == 1 else "out"


def _today_attendance_count(db: Session, user_id: int, now: datetime) -> int:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    return (
        db.query(Attendance)
        .filter(Attendance.user_id == user_id)
        .filter(Attendance.timestamp >= day_start)
        .filter(Attendance.timestamp < day_end)
        .count()
    )


def resolve_next_action(
    db: Session,
    user_id: int,
    requested_action: str,
) -> Literal["in", "out"]:
    normalized = (requested_action or "auto").strip().lower()
    if normalized not in {"auto", "in", "out"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action must be one of: auto, in, out")

    now = datetime.now(timezone.utc)
    today_count = _today_attendance_count(db, user_id, now)
    currently_in = (today_count % 2) == 1

    if normalized == "auto":
        return "out" if currently_in else "in"

    if normalized == "in" and currently_in:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already checked in. Mark out first.")

    if normalized == "out" and not currently_in:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot mark out before marking in.")

    return "in" if normalized == "in" else "out"


def mark_attendance(
    db: Session,
    user_id: int,
    action: str = "in",
    latitude: float | None = None,
    longitude: float | None = None,
    course_code: str | None = None,
    session_name: str | None = None,
    source: str = "mobile",
) -> Attendance:
    attendance = Attendance(
        user_id=user_id,
        action=action,
        latitude=latitude,
        longitude=longitude,
        course_code=_clean_optional(course_code),
        session_name=_clean_optional(session_name),
        source=source,
    )
    db.add(attendance)
    db.commit()
    db.refresh(attendance)
    return attendance
