from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
from urllib import parse, request
from urllib.error import HTTPError, URLError
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import PaymentRecord, User


@dataclass(frozen=True)
class BillingPlan:
    code: str
    name: str
    description: str
    amount_cents: int
    interval: str


PLANS = [
    BillingPlan(
        code="campus_basic",
        name="Campus Basic",
        description="Attendance, student records, and admin reporting for one campus.",
        amount_cents=9900,
        interval="month",
    ),
    BillingPlan(
        code="campus_scale",
        name="Campus Scale",
        description="Higher-volume attendance operations with larger admin teams.",
        amount_cents=29900,
        interval="month",
    ),
    BillingPlan(
        code="university_enterprise",
        name="University Enterprise",
        description="Multi-campus readiness, exports, audit trails, and priority rollout support.",
        amount_cents=99900,
        interval="month",
    ),
]


def get_plans(settings: Settings) -> list[dict]:
    currency = settings.payment_currency.lower()
    return [
        {
            "code": plan.code,
            "name": plan.name,
            "description": plan.description,
            "amount_cents": plan.amount_cents,
            "currency": currency,
            "interval": plan.interval,
        }
        for plan in PLANS
    ]


def find_plan(plan_code: str) -> BillingPlan:
    for plan in PLANS:
        if plan.code == plan_code:
            return plan
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment plan not found")


def resolve_student(db: Session, user_id: int | None, student_code: str | None) -> User | None:
    if user_id is not None:
        return db.get(User, user_id)
    if student_code:
        return db.query(User).filter(User.student_code == student_code).first()
    return None


def _record_payment(
    db: Session,
    settings: Settings,
    plan: BillingPlan,
    user: User | None,
    checkout_session_id: str,
    checkout_url: str,
    status_value: str,
    provider_payload: dict | None = None,
) -> PaymentRecord:
    now = datetime.now(timezone.utc)
    record = PaymentRecord(
        user_id=user.id if user else None,
        student_code=user.student_code if user else None,
        provider=settings.payment_provider,
        checkout_session_id=checkout_session_id,
        plan_code=plan.code,
        amount_cents=plan.amount_cents,
        currency=settings.payment_currency.lower(),
        status=status_value,
        checkout_url=checkout_url,
        provider_payload=provider_payload,
        paid_at=now if status_value == "paid" else None,
    )

    if user:
        user.payment_status = "paid" if status_value == "paid" else "pending"
        user.plan_code = plan.code
        if status_value == "paid":
            user.last_payment_at = now

    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def create_checkout_session(
    db: Session,
    settings: Settings,
    plan_code: str,
    user: User | None,
    success_url: str | None,
    cancel_url: str | None,
) -> PaymentRecord:
    plan = find_plan(plan_code)
    provider = settings.payment_provider.lower()
    default_success = success_url or f"{settings.public_base_url}/admin-panel/?payment=success"
    default_cancel = cancel_url or f"{settings.public_base_url}/admin-panel/?payment=cancelled"

    if provider != "stripe":
        session_id = f"demo_{uuid4().hex}"
        checkout_url = f"{settings.public_base_url}/admin-panel/?payment=demo-paid&session_id={session_id}"
        return _record_payment(db, settings, plan, user, session_id, checkout_url, "paid")

    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STRIPE_SECRET_KEY is required when PAYMENT_PROVIDER=stripe",
        )

    payload = {
        "mode": "payment",
        "success_url": default_success,
        "cancel_url": default_cancel,
        "client_reference_id": str(user.id if user else uuid4().hex),
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": settings.payment_currency.lower(),
        "line_items[0][price_data][unit_amount]": str(plan.amount_cents),
        "line_items[0][price_data][product_data][name]": plan.name,
        "line_items[0][price_data][product_data][description]": plan.description,
        "metadata[plan_code]": plan.code,
    }
    if user:
        if user.email:
            payload["customer_email"] = user.email
        payload["metadata[user_id]"] = str(user.id)
        payload["metadata[student_code]"] = user.student_code or ""

    encoded = parse.urlencode(payload).encode("utf-8")
    stripe_request = request.Request(
        "https://api.stripe.com/v1/checkout/sessions",
        data=encoded,
        headers={
            "Authorization": f"Bearer {settings.stripe_secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with request.urlopen(stripe_request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=exc.code, detail=f"Stripe checkout error: {error_body}") from exc
    except URLError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc.reason)) from exc

    checkout_url = data.get("url")
    session_id = data.get("id")
    if not checkout_url or not session_id:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Stripe did not return a checkout URL")

    return _record_payment(db, settings, plan, user, session_id, checkout_url, "pending", data)


def verify_stripe_signature(payload: bytes, signature_header: str, endpoint_secret: str, tolerance_seconds: int = 300) -> None:
    parts = {}
    for item in signature_header.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            parts.setdefault(key, []).append(value)

    timestamps = parts.get("t", [])
    signatures = parts.get("v1", [])
    if not timestamps or not signatures:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Stripe signature")

    timestamp_value = timestamps[0]
    try:
        timestamp_int = int(timestamp_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe timestamp") from exc

    if abs(time.time() - timestamp_int) > tolerance_seconds:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expired Stripe signature")

    signed_payload = f"{timestamp_value}.{payload.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(endpoint_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()

    if not any(hmac.compare_digest(expected, value) for value in signatures):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe signature")


def complete_checkout_session(db: Session, session_id: str, provider_payload: dict | None = None) -> PaymentRecord | None:
    record = db.query(PaymentRecord).filter(PaymentRecord.checkout_session_id == session_id).first()
    if not record:
        return None

    now = datetime.now(timezone.utc)
    record.status = "paid"
    record.paid_at = now
    if provider_payload:
        record.provider_payload = provider_payload

    if record.user:
        record.user.payment_status = "paid"
        record.user.plan_code = record.plan_code
        record.user.last_payment_at = now

    db.commit()
    db.refresh(record)
    return record
