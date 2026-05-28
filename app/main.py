from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models import User
from app.routes.admin_routes import router as admin_router
from app.routes.face_routes import router as face_router
from app.routes.payment_routes import router as payment_router
from app.services.face_index import compute_face_hash, has_valid_face_encoding
from app.services.websocket_manager import manager

settings = get_settings()


def _parse_cors_origins(value: str) -> list[str]:
    if not value:
        return ["*"]
    parts = [item.strip() for item in value.split(",") if item.strip()]
    return parts or ["*"]

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_runtime_columns()
    _ensure_runtime_indexes()
    _backfill_face_index()


def _add_column_if_missing(table_name: str, column_name: str, column_sql: str) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return

    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))


def _ensure_runtime_columns() -> None:
    """Keep older local SQLite/Postgres databases compatible without Alembic."""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"

    if "users" in table_names:
        _add_column_if_missing("users", "student_code", "VARCHAR(40)")
        _add_column_if_missing("users", "email", "VARCHAR(255)")
        _add_column_if_missing("users", "phone", "VARCHAR(40)")
        _add_column_if_missing("users", "guardian_phone", "VARCHAR(40)")
        _add_column_if_missing("users", "department", "VARCHAR(120) NOT NULL DEFAULT 'General'")
        _add_column_if_missing("users", "program", "VARCHAR(120) NOT NULL DEFAULT 'General'")
        _add_column_if_missing("users", "semester", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing("users", "section", "VARCHAR(40) NOT NULL DEFAULT 'A'")
        _add_column_if_missing("users", "enrollment_year", "INTEGER")
        _add_column_if_missing("users", "status", "VARCHAR(24) NOT NULL DEFAULT 'active'")
        _add_column_if_missing("users", "face_hash", "VARCHAR(64)")
        _add_column_if_missing("users", "face_enrolled", "BOOLEAN NOT NULL DEFAULT FALSE")
        _add_column_if_missing("users", "payment_status", "VARCHAR(24) NOT NULL DEFAULT 'trial'")
        _add_column_if_missing("users", "plan_code", "VARCHAR(40) NOT NULL DEFAULT 'campus_basic'")
        _add_column_if_missing("users", "last_payment_at", timestamp_type)
        _add_column_if_missing("users", "updated_at", timestamp_type)

        truthy = "TRUE" if engine.dialect.name == "postgresql" else "1"
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE users SET face_enrolled = {truthy} WHERE face_encoding IS NOT NULL"))
            conn.execute(text("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL"))

    if "attendance" in table_names:
        _add_column_if_missing("attendance", "action", "VARCHAR(10) NOT NULL DEFAULT 'in'")
        _add_column_if_missing("attendance", "course_code", "VARCHAR(40)")
        _add_column_if_missing("attendance", "session_name", "VARCHAR(120)")
        _add_column_if_missing("attendance", "source", "VARCHAR(40) NOT NULL DEFAULT 'mobile'")
        _add_column_if_missing("attendance", "latitude", "FLOAT")
        _add_column_if_missing("attendance", "longitude", "FLOAT")


def _ensure_runtime_indexes() -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_users_student_code_runtime ON users (student_code)",
        "CREATE INDEX IF NOT EXISTS ix_users_email_runtime ON users (email)",
        "CREATE INDEX IF NOT EXISTS ix_users_department_section_runtime ON users (department, section)",
        "CREATE INDEX IF NOT EXISTS ix_users_status_runtime ON users (status)",
        "CREATE INDEX IF NOT EXISTS ix_users_face_hash_runtime ON users (face_hash)",
        "CREATE INDEX IF NOT EXISTS ix_users_payment_status_runtime ON users (payment_status)",
        "CREATE INDEX IF NOT EXISTS ix_attendance_user_timestamp_runtime ON attendance (user_id, timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_attendance_timestamp_runtime ON attendance (timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_attendance_course_runtime ON attendance (course_code)",
        "CREATE INDEX IF NOT EXISTS ix_payment_records_student_runtime ON payment_records (student_code)",
        "CREATE INDEX IF NOT EXISTS ix_payment_records_status_runtime ON payment_records (status)",
    ]

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _backfill_face_index() -> None:
    db = SessionLocal()
    try:
        users = (
            db.query(User)
            .filter(User.face_enrolled.is_(True))
            .filter(User.face_hash.is_(None))
            .limit(1000)
            .all()
        )
        for user in users:
            if has_valid_face_encoding(user.face_encoding):
                user.face_hash = compute_face_hash(user.face_encoding, settings.face_hash_bits)
        db.commit()
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str | int]:
    return {
        "status": "ok",
        "environment": settings.environment,
        "websocket_clients": len(manager.active_connections),
    }


@app.get("/ready")
def ready() -> dict[str, str]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database connection is not ready")


@app.websocket("/ws/attendance")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Keep connection alive, just acknowledge ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)


app.include_router(face_router)
app.include_router(admin_router)
app.include_router(payment_router)

admin_web_dir = Path(__file__).resolve().parent / "admin_web"
if admin_web_dir.exists():
    app.mount("/admin-panel", StaticFiles(directory=str(admin_web_dir), html=True), name="admin-panel")
