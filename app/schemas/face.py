from datetime import datetime

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    message: str


class RegisterFaceResponse(BaseModel):
    user_id: int
    name: str
    student_code: str | None = None
    message: str


class RecognizeFaceResponse(BaseModel):
    matched: bool
    message: str
    user_id: int | None = None
    name: str | None = None
    timestamp: datetime | None = None
    action: str | None = None


class AttendanceLog(BaseModel):
    id: int
    user_id: int
    name: str
    student_code: str | None = None
    department: str | None = None
    section: str | None = None
    timestamp: datetime
    action: str
    course_code: str | None = None
    session_name: str | None = None
    source: str | None = None


class AttendanceListResponse(BaseModel):
    logs: list[AttendanceLog]


class TokenRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=3, max_length=120)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class StudentBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    student_code: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    guardian_phone: str | None = Field(default=None, max_length=40)
    department: str = Field(default="General", max_length=120)
    program: str = Field(default="General", max_length=120)
    semester: int = Field(default=1, ge=1, le=12)
    section: str = Field(default="A", max_length=40)
    enrollment_year: int | None = Field(default=None, ge=1900, le=2200)
    status: str = Field(default="active", max_length=24)
    payment_status: str = Field(default="trial", max_length=24)
    plan_code: str = Field(default="campus_basic", max_length=40)


class StudentCreate(StudentBase):
    pass


class StudentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    student_code: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    guardian_phone: str | None = Field(default=None, max_length=40)
    department: str | None = Field(default=None, max_length=120)
    program: str | None = Field(default=None, max_length=120)
    semester: int | None = Field(default=None, ge=1, le=12)
    section: str | None = Field(default=None, max_length=40)
    enrollment_year: int | None = Field(default=None, ge=1900, le=2200)
    status: str | None = Field(default=None, max_length=24)
    payment_status: str | None = Field(default=None, max_length=24)
    plan_code: str | None = Field(default=None, max_length=40)


class StudentResponse(StudentBase):
    id: int
    face_enrolled: bool
    created_at: datetime
    updated_at: datetime | None = None
    last_payment_at: datetime | None = None


class StudentListResponse(BaseModel):
    items: list[StudentResponse]
    total: int
    limit: int
    offset: int


class DashboardMetric(BaseModel):
    label: str
    value: int | str


class AdminDashboardResponse(BaseModel):
    metrics: list[DashboardMetric]
    latest_logs: list[AttendanceLog]
    payment_status: dict[str, int]
    department_breakdown: dict[str, int]


class AttendanceReportResponse(BaseModel):
    logs: list[AttendanceLog]
    total: int
    present_students: int
    checked_in_now: int
    limit: int
    offset: int


class PaymentPlan(BaseModel):
    code: str
    name: str
    description: str
    amount_cents: int
    currency: str
    interval: str


class PaymentPlanListResponse(BaseModel):
    plans: list[PaymentPlan]


class PaymentCheckoutRequest(BaseModel):
    plan_code: str = Field(default="campus_basic", max_length=40)
    user_id: int | None = None
    student_code: str | None = Field(default=None, max_length=40)
    success_url: str | None = None
    cancel_url: str | None = None


class PaymentCheckoutResponse(BaseModel):
    provider: str
    checkout_session_id: str
    checkout_url: str
    status: str


class PaymentRecordResponse(BaseModel):
    id: int
    user_id: int | None = None
    student_code: str | None = None
    student_name: str | None = None
    provider: str
    checkout_session_id: str | None = None
    plan_code: str
    amount_cents: int
    currency: str
    status: str
    checkout_url: str | None = None
    created_at: datetime
    paid_at: datetime | None = None


class PaymentListResponse(BaseModel):
    items: list[PaymentRecordResponse]
    total: int
    limit: int
    offset: int
