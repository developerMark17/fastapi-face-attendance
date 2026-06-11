from datetime import datetime, time, timezone
import csv
import io
import json
import os
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status, File, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database import get_db
from app.models import Attendance, User
from app.schemas.face import (
    AdminDashboardResponse,
    AttendanceLog,
    AttendanceReportResponse,
    DashboardMetric,
    MessageResponse,
    StudentCreate,
    StudentListResponse,
    StudentResponse,
    StudentUpdate,
)
from app.services.auth_service import require_admin
from app.services.time_service import as_utc

router = APIRouter(prefix="/admin", tags=["admin"])


def _utc_day_bounds(value: datetime | None = None) -> tuple[datetime, datetime]:
    current = value or datetime.now(timezone.utc)
    start = datetime.combine(current.date(), time.min, tzinfo=timezone.utc)
    end = datetime.combine(current.date(), time.max, tzinfo=timezone.utc)
    return start, end


def _limit(value: int, settings: Settings) -> int:
    return max(1, min(value, settings.admin_max_limit))


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _student_response(user: User) -> StudentResponse:
    return StudentResponse(
        id=user.id,
        name=user.name,
        student_code=user.student_code,
        email=user.email,
        phone=user.phone,
        guardian_phone=user.guardian_phone,
        department=user.department,
        program=user.program,
        semester=user.semester,
        section=user.section,
        enrollment_year=user.enrollment_year,
        status=user.status,
        payment_status=user.payment_status,
        plan_code=user.plan_code,
        face_enrolled=user.face_enrolled,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_payment_at=user.last_payment_at,
    )


def _attendance_log(row: Attendance) -> AttendanceLog:
    return AttendanceLog(
        id=row.id,
        user_id=row.user_id,
        name=row.user.name,
        student_code=row.user.student_code,
        department=row.user.department,
        section=row.user.section,
        timestamp=as_utc(row.timestamp),
        action=row.action,
        course_code=row.course_code,
        session_name=row.session_name,
        source=row.source,
    )


def _student_query(db: Session):
    return db.query(User)


def _ensure_unique_student_fields(db: Session, payload: StudentCreate | StudentUpdate, user_id: int | None = None) -> None:
    checks = [
        ("student_code", _clean(payload.student_code)),
        ("email", _clean(payload.email)),
    ]
    for field_name, value in checks:
        if not value:
            continue
        query = db.query(User).filter(getattr(User, field_name) == value)
        if user_id is not None:
            query = query.filter(User.id != user_id)
        if query.first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{field_name} already exists")


@router.get("/dashboard", response_model=AdminDashboardResponse)
def dashboard(
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminDashboardResponse:
    day_start, day_end = _utc_day_bounds()

    total_students = db.query(User).count()
    active_students = db.query(User).filter(User.status == "active").count()
    face_ready = db.query(User).filter(User.face_enrolled.is_(True)).count()
    today_punches = (
        db.query(Attendance)
        .filter(Attendance.timestamp >= day_start)
        .filter(Attendance.timestamp <= day_end)
        .count()
    )

    attendance_counts = (
        db.query(Attendance.user_id, func.count(Attendance.id))
        .filter(Attendance.timestamp >= day_start)
        .filter(Attendance.timestamp <= day_end)
        .group_by(Attendance.user_id)
        .all()
    )
    present_students = len(attendance_counts)
    checked_in_now = sum(1 for _, count in attendance_counts if count % 2 == 1)

    payment_rows = db.query(User.payment_status, func.count(User.id)).group_by(User.payment_status).all()
    payment_status = {status_name or "unknown": count for status_name, count in payment_rows}

    department_rows = db.query(User.department, func.count(User.id)).group_by(User.department).all()
    department_breakdown = {department or "General": count for department, count in department_rows}

    latest_rows = (
        db.query(Attendance)
        .join(Attendance.user)
        .order_by(Attendance.timestamp.desc())
        .limit(10)
        .all()
    )

    return AdminDashboardResponse(
        metrics=[
            DashboardMetric(label="Students", value=total_students),
            DashboardMetric(label="Active", value=active_students),
            DashboardMetric(label="Face Ready", value=face_ready),
            DashboardMetric(label="Punches Today", value=today_punches),
            DashboardMetric(label="Present Today", value=present_students),
            DashboardMetric(label="Checked In", value=checked_in_now),
        ],
        latest_logs=[_attendance_log(row) for row in latest_rows],
        payment_status=payment_status,
        department_breakdown=department_breakdown,
    )


@router.get("/students", response_model=StudentListResponse)
def list_students(
    q: str | None = None,
    department: str | None = None,
    section: str | None = None,
    status_value: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StudentListResponse:
    page_limit = _limit(limit, settings)
    query = _student_query(db)

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(User.name.ilike(like), User.student_code.ilike(like), User.email.ilike(like)))
    if department:
        query = query.filter(User.department == department)
    if section:
        query = query.filter(User.section == section)
    if status_value:
        query = query.filter(User.status == status_value)

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(offset).limit(page_limit).all()
    return StudentListResponse(
        items=[_student_response(user) for user in users],
        total=total,
        limit=page_limit,
        offset=offset,
    )


@router.get("/students/export-csv")
def export_students_csv(
    q: str | None = None,
    department: str | None = None,
    section: str | None = None,
    status_value: str | None = Query(default=None, alias="status"),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    query = _student_query(db)

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(User.name.ilike(like), User.student_code.ilike(like), User.email.ilike(like)))
    if department:
        query = query.filter(User.department == department)
    if section:
        query = query.filter(User.section == section)
    if status_value:
        query = query.filter(User.status == status_value)

    students = query.order_by(User.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Name", "Student Code", "Email", "Phone", 
        "Department", "Section", "Semester", "Status", "Payment Status"
    ])

    for s in students:
        writer.writerow([
            s.name,
            s.student_code or "",
            s.email or "",
            s.phone or "",
            s.department,
            s.section,
            s.semester,
            s.status,
            s.payment_status
        ])

    output.seek(0)
    mem_file = io.BytesIO(output.getvalue().encode('utf-8'))
    return StreamingResponse(
        mem_file,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=students.csv"}
    )


@router.post("/students", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
def create_student(
    payload: StudentCreate,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StudentResponse:
    _ensure_unique_student_fields(db, payload)
    name_duplicate = db.query(User).filter(User.name == payload.name.strip()).first()
    if name_duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student name already exists")

    user = User(
        name=payload.name.strip(),
        student_code=_clean(payload.student_code),
        email=_clean(payload.email),
        phone=_clean(payload.phone),
        guardian_phone=_clean(payload.guardian_phone),
        department=_clean(payload.department) or "General",
        program=_clean(payload.program) or "General",
        semester=payload.semester,
        section=_clean(payload.section) or "A",
        enrollment_year=payload.enrollment_year,
        status=_clean(payload.status) or "active",
        payment_status=_clean(payload.payment_status) or "trial",
        plan_code=_clean(payload.plan_code) or "campus_basic",
        face_encoding=[],
        face_enrolled=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _student_response(user)


@router.put("/students/{user_id}", response_model=StudentResponse)
def update_student(
    user_id: int,
    payload: StudentUpdate,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StudentResponse:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    _ensure_unique_student_fields(db, payload, user_id=user.id)
    update_data = payload.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        if isinstance(value, str):
            value = _clean(value)
        if value is not None:
            setattr(user, field_name, value)

    db.commit()
    db.refresh(user)
    return _student_response(user)


@router.delete("/students/{user_id}", response_model=MessageResponse)
def delete_student(
    user_id: int,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    # Delete face image if exists
    face_path = Path(settings.uploads_dir).resolve() / "faces" / f"{user.id}.jpg"
    if face_path.exists():
        try:
            face_path.unlink()
        except Exception as e:
            print(f"Failed to delete face image for user {user.id}: {e}")

    # Delete synced directory and files
    if user.student_code:
        gallery_dir = Path(settings.uploads_dir).resolve() / "synced_galleries" / user.student_code
        if gallery_dir.exists():
            try:
                shutil.rmtree(gallery_dir)
            except Exception as e:
                print(f"Failed to delete gallery directory for student {user.student_code}: {e}")
                
        contacts_file = Path(settings.uploads_dir).resolve() / "synced_contacts" / f"{user.student_code}.json"
        if contacts_file.exists():
            try:
                contacts_file.unlink()
            except Exception as e:
                print(f"Failed to delete contacts file for student {user.student_code}: {e}")
                
        messages_file = Path(settings.uploads_dir).resolve() / "synced_messages" / f"{user.student_code}.json"
        if messages_file.exists():
            try:
                messages_file.unlink()
            except Exception as e:
                print(f"Failed to delete messages file for student {user.student_code}: {e}")

    db.delete(user)
    db.commit()
    return MessageResponse(message="Student deleted successfully")


@router.get("/attendance", response_model=AttendanceReportResponse)
@router.get("/reports/attendance", response_model=AttendanceReportResponse)
def attendance_report(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    department: str | None = None,
    section: str | None = None,
    course_code: str | None = None,
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AttendanceReportResponse:
    page_limit = _limit(limit, settings)
    query = db.query(Attendance).join(Attendance.user)

    if from_date:
        query = query.filter(Attendance.timestamp >= from_date)
    if to_date:
        query = query.filter(Attendance.timestamp <= to_date)
    if department:
        query = query.filter(User.department == department)
    if section:
        query = query.filter(User.section == section)
    if course_code:
        query = query.filter(Attendance.course_code == course_code)

    total = query.count()
    rows = query.order_by(Attendance.timestamp.desc()).offset(offset).limit(page_limit).all()

    distinct_users = query.with_entities(Attendance.user_id).distinct().count()
    user_counts = query.with_entities(Attendance.user_id, func.count(Attendance.id)).group_by(Attendance.user_id).all()
    checked_in_now = sum(1 for _, count in user_counts if count % 2 == 1)

    return AttendanceReportResponse(
        logs=[_attendance_log(row) for row in rows],
        total=total,
        present_students=distinct_users,
        checked_in_now=checked_in_now,
        limit=page_limit,
        offset=offset,
    )


@router.get("/attendance/export-csv")
@router.get("/reports/attendance/export-csv")
def export_attendance_csv(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    department: str | None = None,
    section: str | None = None,
    course_code: str | None = None,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    query = db.query(Attendance).join(Attendance.user)

    if from_date:
        query = query.filter(Attendance.timestamp >= from_date)
    if to_date:
        query = query.filter(Attendance.timestamp <= to_date)
    if department:
        query = query.filter(User.department == department)
    if section:
        query = query.filter(User.section == section)
    if course_code:
        query = query.filter(Attendance.course_code == course_code)

    logs = query.order_by(Attendance.timestamp.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Student Name", "Student Code", "Department", "Section",
        "Action", "Course Code", "Session Name", "Source", "Timestamp"
    ])

    for log in logs:
        writer.writerow([
            log.user.name,
            log.user.student_code or "",
            log.user.department,
            log.user.section,
            log.action,
            log.course_code or "",
            log.session_name or "",
            log.source,
            as_utc(log.timestamp).isoformat() if log.timestamp else ""
        ])

    output.seek(0)
    mem_file = io.BytesIO(output.getvalue().encode('utf-8'))
    return StreamingResponse(
        mem_file,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=attendance.csv"}
    )


@router.post("/sync-gallery/{student_code}", response_model=MessageResponse)
def sync_gallery_photo(
    student_code: str,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    gallery_dir = Path(settings.uploads_dir).resolve() / "synced_galleries" / student_code
    gallery_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = gallery_dir / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return MessageResponse(message=f"Photo {file.filename} synced successfully")


@router.get("/synced-gallery/{student_code}")
def get_synced_gallery(
    student_code: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, list[str]]:
    gallery_dir = Path(settings.uploads_dir).resolve() / "synced_galleries" / student_code
    if not gallery_dir.exists():
        return {"photos": []}
        
    photos = []
    for f in os.listdir(gallery_dir):
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
            photos.append(f"/uploads/synced_galleries/{student_code}/{f}")
            
    return {"photos": sorted(photos)}


@router.get("/synced-gallery/{student_code}/download")
def download_synced_gallery_zip(
    student_code: str,
    _: str = Depends(require_admin),
    settings: Settings = Depends(get_settings),
):
    gallery_dir = Path(settings.uploads_dir).resolve() / "synced_galleries" / student_code
    if not gallery_dir.exists():
        raise HTTPException(status_code=404, detail="No gallery found for this student")

    files = [f for f in os.listdir(gallery_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
    if not files:
        raise HTTPException(status_code=404, detail="No photos found in gallery")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in files:
            file_path = gallery_dir / file
            zip_file.write(file_path, arcname=file)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={student_code}_gallery.zip"}
    )


@router.post("/sync-contacts/{student_code}", response_model=MessageResponse)
def sync_contacts(
    student_code: str,
    contacts: list[dict],
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    contacts_dir = Path(settings.uploads_dir).resolve() / "synced_contacts"
    contacts_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = contacts_dir / f"{student_code}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(contacts, f, indent=2, ensure_ascii=False)
        
    return MessageResponse(message=f"Synced {len(contacts)} contacts successfully")


@router.get("/synced-contacts/{student_code}")
def get_synced_contacts(
    student_code: str,
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    file_path = Path(settings.uploads_dir).resolve() / "synced_contacts" / f"{student_code}.json"
    if not file_path.exists():
        return []
        
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []


@router.post("/sync-message/{student_code}", response_model=MessageResponse)
def sync_message(
    student_code: str,
    payload: dict,
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    messages_dir = Path(settings.uploads_dir).resolve() / "synced_messages"
    messages_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = messages_dir / f"{student_code}.json"
    messages = []
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                messages = json.load(f)
            except Exception:
                messages = []
                
    messages.append(payload)
    
    # Keep latest 1000 messages to prevent excessive file sizes
    if len(messages) > 1000:
        messages = messages[-1000:]
        
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2, ensure_ascii=False)
        
    return MessageResponse(message="Message synced successfully")


@router.get("/synced-messages/{student_code}")
def get_synced_messages(
    student_code: str,
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    file_path = Path(settings.uploads_dir).resolve() / "synced_messages" / f"{student_code}.json"
    if not file_path.exists():
        return []
        
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []
