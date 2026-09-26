from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import BookingStatus, Payment, PaymentStatus, User
from app.schemas.payment import PaymentCreateRequest
from app.services.booking import get_owned_booking

PAYABLE_STATUSES = (BookingStatus.PENDING,)
RESULT_TO_BOOKING_STATUS = {
    PaymentStatus.SUCCESS: BookingStatus.CONFIRMED,
    PaymentStatus.FAILED: BookingStatus.FAILED,
}


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
