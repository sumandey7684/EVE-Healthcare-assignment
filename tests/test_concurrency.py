from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier, Thread
from uuid import uuid4

from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import (
    Booking,
    BookingStatus,
    CentreTest,
    DiagnosticCentre,
    DiagnosticTest,
    Payment,
    PaymentStatus,
    User,
)
from app.schemas.booking import BookingCreateRequest
from app.schemas.payment import PaymentCreateRequest, WebhookEventRequest
from app.security import hash_password
from app.services.booking import cancel_booking, create_booking
from app.services.payment import process_webhook, simulate_payment

# Computed relative to "now" so the suite does not break once a fixed date passes.
FUTURE_APPOINTMENT = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)


def _seed_user_and_offering() -> tuple[User, DiagnosticCentre, DiagnosticTest]:
    suffix = uuid4().hex
    db = SessionLocal()
    try:
        user = User(
            email=f"race-{suffix}@example.com",
            password_hash=hash_password("StrongPassword123"),
            full_name="Race Tester",
        )
        centre = DiagnosticCentre(name=f"Race Lab {suffix}", location="Bengaluru")
        test = DiagnosticTest(name=f"Race Test {suffix}")
        db.add_all([user, centre, test])
        db.flush()
        db.add(CentreTest(centre_id=centre.id, test_id=test.id, price=Decimal("450.00")))
        db.commit()
        db.refresh(user)
        db.refresh(centre)
        db.refresh(test)
        return user, centre, test
    finally:
        db.close()


def _seed_pending_booking() -> Booking:
    user, centre, test = _seed_user_and_offering()
    db = SessionLocal()
    try:
        booking = Booking(
            user_id=user.id,
            centre_id=centre.id,
            test_id=test.id,
            appointment_at=FUTURE_APPOINTMENT,
            amount=Decimal("450.00"),
            status=BookingStatus.PENDING,
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)
        return booking
    finally:
        db.close()


def _cleanup_offering(user_id, centre_id, test_id) -> None:
    db = SessionLocal()
    try:
        bookings = list(db.scalars(select(Booking).where(Booking.user_id == user_id)).all())
        booking_ids = [booking.id for booking in bookings]
        if booking_ids:
            for payment in db.scalars(select(Payment).where(Payment.booking_id.in_(booking_ids))).all():
                db.delete(payment)
            db.flush()
        for booking in bookings:
            db.delete(booking)
        db.flush()
        offering = db.scalar(
            select(CentreTest).where(
                CentreTest.centre_id == centre_id,
                CentreTest.test_id == test_id,
            )
        )
        if offering is not None:
            db.delete(offering)
            db.flush()
        centre = db.get(DiagnosticCentre, centre_id)
        test = db.get(DiagnosticTest, test_id)
        user = db.get(User, user_id)
        if centre is not None:
            db.delete(centre)
        if test is not None:
            db.delete(test)
        if user is not None:
            db.delete(user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def test_concurrent_payments_do_not_settle_the_same_booking_twice() -> None:
    booking = _seed_pending_booking()
    barrier = Barrier(2)
    outcomes: list[object] = []

    def worker() -> None:
        db = SessionLocal()
        try:
            user = db.get(User, booking.user_id)
            assert user is not None
            barrier.wait(timeout=5)
            payment = simulate_payment(
                db,
                user,
                PaymentCreateRequest(booking_id=booking.id, result=PaymentStatus.SUCCESS),
            )
            outcomes.append(payment.id)
        except AppError as exc:
            outcomes.append(exc)
        finally:
            db.close()

    try:
        threads = [Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        successes = [item for item in outcomes if not isinstance(item, AppError)]
        conflicts = [item for item in outcomes if isinstance(item, AppError)]
        assert len(successes) == 1
        assert len(conflicts) == 1
        assert conflicts[0].status_code == 409
        assert conflicts[0].code == "invalid_booking_status"

        db = SessionLocal()
        try:
            payments = list(db.scalars(select(Payment).where(Payment.booking_id == booking.id)).all())
            stored = db.get(Booking, booking.id)
            assert len(payments) == 1
            assert stored is not None
            assert stored.status == BookingStatus.CONFIRMED
        finally:
            db.close()
    finally:
        _cleanup_offering(booking.user_id, booking.centre_id, booking.test_id)


def test_concurrent_active_bookings_are_rejected_by_unique_index() -> None:
    user, centre, test = _seed_user_and_offering()
    barrier = Barrier(2)
    outcomes: list[object] = []
    payload = BookingCreateRequest(
        centre_id=centre.id,
        test_id=test.id,
        appointment_at=FUTURE_APPOINTMENT,
    )

    def worker() -> None:
        db = SessionLocal()
        try:
            owned = db.get(User, user.id)
            assert owned is not None
            barrier.wait(timeout=5)
            created = create_booking(db, owned, payload)
            outcomes.append(created.id)
        except AppError as exc:
            outcomes.append(exc)
        finally:
            db.close()

    try:
        threads = [Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        successes = [item for item in outcomes if not isinstance(item, AppError)]
        conflicts = [item for item in outcomes if isinstance(item, AppError)]
        assert len(successes) == 1
        assert len(conflicts) == 1
        assert conflicts[0].status_code == 409
        assert conflicts[0].code == "duplicate_booking"

        db = SessionLocal()
        try:
            bookings = list(db.scalars(select(Booking).where(Booking.user_id == user.id)).all())
            assert len(bookings) == 1
            assert bookings[0].status == BookingStatus.PENDING
        finally:
            db.close()
    finally:
        _cleanup_offering(user.id, centre.id, test.id)


def test_concurrent_cancel_and_payment_never_corrupt_state() -> None:
    """A cancel racing a payment must end in exactly one of two consistent states.

    Without the row lock in cancel_booking, the cancel could overwrite a booking that
    a payment had just CONFIRMED, leaving a SUCCESS payment on a CANCELLED booking.
    """
    booking = _seed_pending_booking()
    barrier = Barrier(2)
    outcomes: dict[str, object] = {}

    def pay() -> None:
        db = SessionLocal()
        try:
            user = db.get(User, booking.user_id)
            assert user is not None
            barrier.wait(timeout=5)
            simulate_payment(
                db,
                user,
                PaymentCreateRequest(booking_id=booking.id, result=PaymentStatus.SUCCESS),
            )
            outcomes["pay"] = "ok"
        except AppError as exc:
            outcomes["pay"] = exc
        finally:
            db.close()

    def cancel() -> None:
        db = SessionLocal()
        try:
            user = db.get(User, booking.user_id)
            assert user is not None
            barrier.wait(timeout=5)
            cancel_booking(db, user, booking.id)
            outcomes["cancel"] = "ok"
        except AppError as exc:
            outcomes["cancel"] = exc
        finally:
            db.close()

    try:
        threads = [Thread(target=pay), Thread(target=cancel)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        winners = [key for key, value in outcomes.items() if value == "ok"]
        losers = [value for value in outcomes.values() if isinstance(value, AppError)]
        assert len(winners) == 1
        assert len(losers) == 1
        assert losers[0].status_code == 409
        assert losers[0].code == "invalid_booking_status"

        db = SessionLocal()
        try:
            stored = db.get(Booking, booking.id)
            payments = list(db.scalars(select(Payment).where(Payment.booking_id == booking.id)).all())
            assert stored is not None
            if winners == ["pay"]:
                assert stored.status == BookingStatus.CONFIRMED
                assert len(payments) == 1
            else:
                assert stored.status == BookingStatus.CANCELLED
                assert payments == []
        finally:
            db.close()
    finally:
        _cleanup_offering(booking.user_id, booking.centre_id, booking.test_id)


def test_concurrent_identical_webhooks_remain_idempotent() -> None:
    booking = _seed_pending_booking()
    barrier = Barrier(2)
    outcomes: list[object] = []
    payload = WebhookEventRequest(
        event_id=f"evt_race_{uuid4().hex}",
        booking_id=booking.id,
        status=PaymentStatus.SUCCESS,
        amount=Decimal("450.00"),
    )

    def worker() -> None:
        db = SessionLocal()
        try:
            barrier.wait(timeout=5)
            outcomes.append(process_webhook(db, payload))
        except AppError as exc:
            outcomes.append(exc)
        finally:
            db.close()

    try:
        threads = [Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert all(not isinstance(item, AppError) for item in outcomes)
        assert sorted(outcomes) == ["already_processed", "processed"]

        db = SessionLocal()
        try:
            payments = list(db.scalars(select(Payment).where(Payment.booking_id == booking.id)).all())
            stored = db.get(Booking, booking.id)
            assert len(payments) == 1
            assert payments[0].provider_event_id == payload.event_id
            assert stored is not None
            assert stored.status == BookingStatus.CONFIRMED
        finally:
            db.close()
    finally:
        _cleanup_offering(booking.user_id, booking.centre_id, booking.test_id)
