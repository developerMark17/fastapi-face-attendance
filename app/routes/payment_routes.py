import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database import get_db
from app.models import PaymentRecord
from app.schemas.face import (
    MessageResponse,
    PaymentCheckoutRequest,
    PaymentCheckoutResponse,
    PaymentListResponse,
    PaymentPlanListResponse,
    PaymentRecordResponse,
)
from app.services.auth_service import require_admin
from app.services.payment_service import (
    complete_checkout_session,
    create_checkout_session,
    get_plans,
    resolve_student,
    verify_stripe_signature,
)

router = APIRouter(tags=["payments"])


def _payment_response(record: PaymentRecord) -> PaymentRecordResponse:
    return PaymentRecordResponse(
        id=record.id,
        user_id=record.user_id,
        student_code=record.student_code,
        student_name=record.user.name if record.user else None,
        provider=record.provider,
        checkout_session_id=record.checkout_session_id,
        plan_code=record.plan_code,
        amount_cents=record.amount_cents,
        currency=record.currency,
        status=record.status,
        checkout_url=record.checkout_url,
        created_at=record.created_at,
        paid_at=record.paid_at,
    )


def _limit(value: int, settings: Settings) -> int:
    return max(1, min(value, settings.admin_max_limit))


@router.get("/billing/plans", response_model=PaymentPlanListResponse)
def billing_plans(settings: Settings = Depends(get_settings)) -> PaymentPlanListResponse:
    return PaymentPlanListResponse(plans=get_plans(settings))


@router.get("/admin/payments", response_model=PaymentListResponse)
def list_payments(
    status_value: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PaymentListResponse:
    page_limit = _limit(limit, settings)
    query = db.query(PaymentRecord)
    if status_value:
        query = query.filter(PaymentRecord.status == status_value)

    total = query.count()
    records = query.order_by(PaymentRecord.created_at.desc()).offset(offset).limit(page_limit).all()
    return PaymentListResponse(
        items=[_payment_response(record) for record in records],
        total=total,
        limit=page_limit,
        offset=offset,
    )


@router.post("/payments/checkout-session", response_model=PaymentCheckoutResponse)
def create_payment_checkout(
    payload: PaymentCheckoutRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PaymentCheckoutResponse:
    user = resolve_student(db, payload.user_id, payload.student_code)
    if (payload.user_id is not None or payload.student_code) and not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    record = create_checkout_session(
        db=db,
        settings=settings,
        plan_code=payload.plan_code,
        user=user,
        success_url=payload.success_url,
        cancel_url=payload.cancel_url,
    )
    return PaymentCheckoutResponse(
        provider=record.provider,
        checkout_session_id=record.checkout_session_id or "",
        checkout_url=record.checkout_url or "",
        status=record.status,
    )


@router.post("/payments/stripe/webhook", response_model=MessageResponse)
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    if settings.stripe_webhook_secret:
        verify_stripe_signature(payload, signature, settings.stripe_webhook_secret)
    elif settings.environment != "development":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Stripe webhook secret is required")

    try:
        event = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook JSON") from exc

    if event.get("type") == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        session_id = session.get("id")
        if session_id:
            complete_checkout_session(db, session_id, session)

    return MessageResponse(message="Webhook received")
