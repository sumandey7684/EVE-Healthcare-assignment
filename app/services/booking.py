from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Booking, BookingStatus, CentreTest, User
from app.schemas.booking import BookingCreateRequest
from app.services.catalogue import get_centre, get_test

ACTIVE_BOOKING_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED)
CANCELLABLE_STATUSES = (BookingStatus.PENDING,)


def _get_offering(db: Session, centre_id: UUID, test_id: UUID) -> CentreTest:
    offering = db.scalar(
        select(CentreTest).where(
            CentreTest.centre_id == centre_id,
            CentreTest.test_id == test_id,
        )
    )
    if offering is None:
        raise AppError(
            status_code=400,
            code="test_not_offered",
            message="The selected test is not offered by this diagnostic centre.",
        )
    return offering


def _require_future_appointment(appointment_at: datetime) -> None:
    if appointment_at.tzinfo is None or appointment_at.utcoffset() is None:
        raise AppError(
            status_code=422,
            code="invalid_appointment",
            message="appointment_at must include a timezone.",
        )
    if appointment_at <= datetime.now(timezone.utc):
        raise AppError(
            status_code=422,
            code="appointment_in_the_past",
            message="appointment_at must be in the future.",
        )


def create_booking(db: Session, user: User, payload: BookingCreateRequest) -> Booking:
    get_centre(db, payload.centre_id)
    get_test(db, payload.test_id)
    offering = _get_offering(db, payload.centre_id, payload.test_id)
    _require_future_appointment(payload.appointment_at)

    duplicate = db.scalar(
        select(Booking).where(
            Booking.user_id == user.id,
            Booking.centre_id == payload.centre_id,
            Booking.test_id == payload.test_id,
            Booking.appointment_at == payload.appointment_at,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
    )
    if duplicate is not None:
        raise AppError(
            status_code=409,
            code="duplicate_booking",
            message="An active booking already exists for this centre, test, and appointment time.",
        )

    booking = Booking(
        user_id=user.id,
        centre_id=payload.centre_id,
        test_id=payload.test_id,
        appointment_at=payload.appointment_at,
        amount=offering.price,
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_bookings_active_slot" in str(getattr(exc, "orig", exc)):
            raise AppError(
                status_code=409,
                code="duplicate_booking",
                message="An active booking already exists for this centre, test, and appointment time.",
            ) from exc
        raise
    db.refresh(booking)
    return booking


def list_bookings(db: Session, user: User) -> list[Booking]:
    return list(
        db.scalars(
            select(Booking)
            .where(Booking.user_id == user.id)
            .order_by(Booking.appointment_at.asc())
        ).all()
    )


def get_owned_booking(
    db: Session,
    user: User,
    booking_id: UUID,
    *,
    for_update: bool = False,
) -> Booking:
    statement = select(Booking).where(Booking.id == booking_id)
    if for_update:
        statement = statement.with_for_update()
    booking = db.scalar(statement)
    if booking is None:
        raise AppError(
            status_code=404,
            code="booking_not_found",
            message="Booking was not found.",
        )
    if booking.user_id != user.id:
        raise AppError(
            status_code=403,
            code="booking_forbidden",
            message="You cannot access another user's booking.",
        )
    return booking


def cancel_booking(db: Session, user: User, booking_id: UUID) -> Booking:
    booking = get_owned_booking(db, user, booking_id)
    if booking.status not in CANCELLABLE_STATUSES:
        raise AppError(
            status_code=409,
            code="invalid_booking_status",
            message=f"A {booking.status.value} booking cannot be cancelled.",
        )
    booking.status = BookingStatus.CANCELLED
    db.commit()
    db.refresh(booking)
    return booking
