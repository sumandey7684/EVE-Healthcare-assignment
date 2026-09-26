from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Booking, BookingStatus, Payment, PaymentStatus, User
from app.schemas.payment import PaymentCreateRequest, WebhookEventRequest
from app.services.booking import get_owned_booking

PAYABLE_STATUSES = (BookingStatus.PENDING,)
RESULT_TO_BOOKING_STATUS = {
    PaymentStatus.SUCCESS: BookingStatus.CONFIRMED,
    PaymentStatus.FAILED: BookingStatus.FAILED,
}


def _same_money(left: Decimal, right: Decimal) -> bool:
    return left.quantize(Decimal("0.01")) == right.quantize(Decimal("0.01"))


def _is_event_id_conflict(exc: IntegrityError) -> bool:
    return "uq_payments_provider_event_id" in str(getattr(exc, "orig", exc))


def _payment_by_event_id(db: Session, event_id: str) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.provider_event_id == event_id))


def simulate_payment(db: Session, user: User, payload: PaymentCreateRequest) -> Payment:
    booking = get_owned_booking(db, user, payload.booking_id)
    if booking.status not in PAYABLE_STATUSES:
        raise AppError(
            status_code=409,
            code="invalid_booking_status",
            message=f"A {booking.status.value} booking cannot be paid.",
        )

    payment = Payment(
        booking_id=booking.id,
        amount=booking.amount,
        status=payload.result,
    )
    booking.status = RESULT_TO_BOOKING_STATUS[payload.result]
    db.add(payment)
    db.commit()
    db.refresh(payment)
    db.refresh(booking)
    return payment


def process_webhook(db: Session, payload: WebhookEventRequest) -> str:
    if _payment_by_event_id(db, payload.event_id) is not None:
        return "already_processed"

    booking = db.get(Booking, payload.booking_id)
    if booking is None:
        raise AppError(
            status_code=404,
            code="booking_not_found",
            message="Booking was not found.",
        )
    if not _same_money(payload.amount, booking.amount):
        raise AppError(
            status_code=409,
            code="amount_mismatch",
            message="Webhook amount does not match the booking amount.",
        )

    payment: Payment | None = None
    if payload.payment_id is not None:
        payment = db.get(Payment, payload.payment_id)
        if payment is None:
            raise AppError(
                status_code=404,
                code="payment_not_found",
                message="Payment was not found.",
            )
        if payment.booking_id != booking.id:
            raise AppError(
                status_code=400,
                code="payment_booking_mismatch",
                message="payment_id does not belong to the given booking.",
            )
        if payment.provider_event_id is not None and payment.provider_event_id != payload.event_id:
            raise AppError(
                status_code=409,
                code="payment_already_linked",
                message="This payment is already linked to a different provider event.",
            )

    expected_status = RESULT_TO_BOOKING_STATUS[payload.status]

    if booking.status != BookingStatus.PENDING:
        if (
            payment is not None
            and payment.provider_event_id is None
            and payment.status == payload.status
            and booking.status == expected_status
        ):
            payment.provider_event_id = payload.event_id
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                if _is_event_id_conflict(exc):
                    return "already_processed"
                raise
            return "already_processed"
        raise AppError(
            status_code=409,
            code="invalid_booking_status",
            message=f"A {booking.status.value} booking cannot be updated by webhook.",
        )

    if payment is None:
        payment = Payment(
            booking_id=booking.id,
            provider_event_id=payload.event_id,
            amount=booking.amount,
            status=payload.status,
        )
        db.add(payment)
    else:
        payment.provider_event_id = payload.event_id
        payment.status = payload.status

    booking.status = expected_status
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_event_id_conflict(exc):
            return "already_processed"
        raise
    return "processed"
