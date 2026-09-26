from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_webhook_secret
from app.database import get_db
from app.models import Payment, User
from app.schemas.payment import (
    PaymentCreateRequest,
    PaymentPublic,
    WebhookEventRequest,
    WebhookEventResponse,
)
from app.services.payment import process_webhook, simulate_payment

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/webhook", response_model=WebhookEventResponse)
def payment_webhook(
    payload: WebhookEventRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_webhook_secret),
) -> WebhookEventResponse:
    return WebhookEventResponse(status=process_webhook(db, payload))


@router.post("", response_model=PaymentPublic, status_code=201)
def create_payment(
    payload: PaymentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Payment:
    return simulate_payment(db, current_user, payload)
