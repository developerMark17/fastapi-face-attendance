from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database import get_db
from app.models import Attendance
from app.schemas.face import (
    AttendanceListResponse,
    AttendanceLog,
    MessageResponse,
    RecognizeFaceResponse,
    RegisterFaceResponse,
    TokenRequest,
    TokenResponse,
)
from app.services.auth_service import authenticate_admin, create_access_token, require_admin
from app.services.face_service import (
    check_liveness,
    enforce_geofence,
    extract_single_face,
    infer_action_for_log,
    mark_attendance,
    prevent_duplicate_attendance,
    recognize_user,
    register_face,
    resolve_next_action,
)
from app.services.image_service import bytes_to_bgr_image, validate_image_file
from app.services.time_service import as_utc
from app.services.websocket_manager import manager

router = APIRouter(tags=["face-attendance"])


def _build_attendance_logs(rows: list[Attendance]) -> list[AttendanceLog]:
    per_user_day_count: dict[tuple[int, str], int] = {}
    ordered_rows = list(reversed(rows))
    action_map: dict[int, str] = {}

    for row in ordered_rows:
        ts_utc = as_utc(row.timestamp)
        day_key = ts_utc.date().isoformat()
        key = (row.user_id, day_key)
        per_user_day_count[key] = per_user_day_count.get(key, 0) + 1
        action_map[row.id] = infer_action_for_log(per_user_day_count[key])

    return [
        AttendanceLog(
            id=row.id,
            user_id=row.user_id,
            name=row.user.name,
            student_code=row.user.student_code,
            department=row.user.department,
            section=row.user.section,
            timestamp=as_utc(row.timestamp),
            action=row.action or action_map.get(row.id, "in"),
            course_code=row.course_code,
            session_name=row.session_name,
            source=row.source,
        )
        for row in rows
    ]


@router.post("/auth/token", response_model=TokenResponse)
def login_for_token(payload: TokenRequest, settings: Settings = Depends(get_settings)) -> TokenResponse:
    if not authenticate_admin(payload.username, payload.password, settings):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(subject=payload.username, settings=settings)
    return TokenResponse(access_token=token)


@router.post("/auth/logout", response_model=MessageResponse)
def logout(_: str = Depends(require_admin)) -> MessageResponse:
    return MessageResponse(message="Logged out successfully")


@router.post("/register-face", response_model=RegisterFaceResponse)
async def register_face_endpoint(
    name: str = Form(..., min_length=2, max_length=120),
    student_code: str | None = Form(default=None, max_length=40),
    email: str | None = Form(default=None, max_length=255),
    phone: str | None = Form(default=None, max_length=40),
    guardian_phone: str | None = Form(default=None, max_length=40),
    department: str | None = Form(default=None, max_length=120),
    program: str | None = Form(default=None, max_length=120),
    semester: int | None = Form(default=None),
    section: str | None = Form(default=None, max_length=40),
    enrollment_year: int | None = Form(default=None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RegisterFaceResponse:
    validate_image_file(image, settings.max_upload_mb)
    image_bytes = await image.read()
    image_bgr = bytes_to_bgr_image(image_bytes, settings.max_upload_mb)

    face_data = extract_single_face(image_bgr)
    user = register_face(
        db,
        name.strip(),
        face_data.encoding,
        face_hash_bits=settings.face_hash_bits,
        student_code=student_code,
        email=email,
        phone=phone,
        guardian_phone=guardian_phone,
        department=department,
        program=program,
        semester=semester,
        section=section,
        enrollment_year=enrollment_year,
    )

    return RegisterFaceResponse(
        user_id=user.id,
        name=user.name,
        student_code=user.student_code,
        message="Face registered successfully",
    )


@router.post("/recognize-face", response_model=RecognizeFaceResponse)
async def recognize_face_endpoint(
    image: UploadFile = File(...),
    challenge: str = Form(...),
    action: str = Form(default="auto"),
    course_code: str | None = Form(default=None, max_length=40),
    session_name: str | None = Form(default=None, max_length=120),
    latitude: float | None = Form(default=None),
    longitude: float | None = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RecognizeFaceResponse:
    validate_image_file(image, settings.max_upload_mb)
    image_bytes = await image.read()
    image_bgr = bytes_to_bgr_image(image_bytes, settings.max_upload_mb)

    face_data = extract_single_face(image_bgr)

    if not check_liveness(challenge=challenge, landmarks=face_data.landmarks):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Liveness check failed")

    user = recognize_user(
        db,
        face_data.encoding,
        tolerance=settings.face_tolerance,
        face_hash_bits=settings.face_hash_bits,
        candidate_limit=settings.face_candidate_limit,
        max_full_scan_faces=settings.max_full_scan_faces,
    )
    if not user:
        return RecognizeFaceResponse(matched=False, message="Face not recognized")

    enforce_geofence(settings, latitude, longitude)
    next_action = resolve_next_action(db, user.id, action)
    # Allow OUT punch (second punch) even within cooldown window
    allow_out_punch = next_action == "out"
    prevent_duplicate_attendance(db, user.id, settings.attendance_cooldown_minutes, allow_out=allow_out_punch)
    attendance = mark_attendance(
        db,
        user.id,
        action=next_action,
        latitude=latitude,
        longitude=longitude,
        course_code=course_code,
        session_name=session_name,
    )

    # Broadcast real-time attendance update
    timestamp_str = as_utc(attendance.timestamp).isoformat()
    await manager.broadcast_attendance(user.name, timestamp_str, user.id, next_action, user.student_code)

    return RecognizeFaceResponse(
        matched=True,
        message=f"Attendance marked as {next_action.upper()} successfully",
        user_id=user.id,
        name=user.name,
        timestamp=as_utc(attendance.timestamp),
        action=next_action,
    )


@router.get("/attendance", response_model=AttendanceListResponse)
def list_attendance(
    db: Session = Depends(get_db),
) -> AttendanceListResponse:
    rows = (
        db.query(Attendance)
        .join(Attendance.user)
        .order_by(Attendance.timestamp.desc())
        .limit(200)
        .all()
    )

    logs = _build_attendance_logs(rows)
    return AttendanceListResponse(logs=logs)
