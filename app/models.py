from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    student_code: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    guardian_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    department: Mapped[str] = mapped_column(String(120), default="General", nullable=False, index=True)
    program: Mapped[str] = mapped_column(String(120), default="General", nullable=False, index=True)
    semester: Mapped[int] = mapped_column(Integer, default=1, nullable=False, index=True)
    section: Mapped[str] = mapped_column(String(40), default="A", nullable=False, index=True)
    enrollment_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    # Storing 128-d face encoding vector as JSON array for portability.
    face_encoding: Mapped[list[float]] = mapped_column(JSON, nullable=False, default=list)
    face_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    face_enrolled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    payment_status: Mapped[str] = mapped_column(String(24), default="trial", nullable=False, index=True)
    plan_code: Mapped[str] = mapped_column(String(40), default="campus_basic", nullable=False, index=True)
    last_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    attendances = relationship("Attendance", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("PaymentRecord", back_populates="user", cascade="all, delete-orphan")


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("user_id", "timestamp", name="uq_attendance_user_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(10), default="in", nullable=False)  # "in" or "out"
    course_code: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    session_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="mobile", nullable=False, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    user = relationship("User", back_populates="attendances")


class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    student_code: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="demo", nullable=False, index=True)
    checkout_session_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    plan_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(12), default="usd", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    user = relationship("User", back_populates="payments")
