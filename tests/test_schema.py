from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import engine
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

EXPECTED_TABLES = {
    "users",
    "diagnostic_centres",
    "diagnostic_tests",
    "centre_tests",
    "bookings",
    "payments",
}


def test_expected_tables_exist() -> None:
    inspector = inspect(engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))


def test_unique_and_foreign_key_constraints() -> None:
    inspector = inspect(engine)

    user_uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("users")}
    assert ("email",) in user_uniques

    centre_test_uniques = {
        tuple(item["column_names"]) for item in inspector.get_unique_constraints("centre_tests")
    }
    assert ("centre_id", "test_id") in centre_test_uniques

    payment_uniques = {
        tuple(item["column_names"]) for item in inspector.get_unique_constraints("payments")
    }
    assert ("provider_event_id",) in payment_uniques

    booking_fk_referred = {
        fk["referred_table"] for fk in inspector.get_foreign_keys("bookings")
    }
    assert booking_fk_referred == {"users", "diagnostic_tests", "diagnostic_centres"}

    centre_test_fk_referred = {
        fk["referred_table"] for fk in inspector.get_foreign_keys("centre_tests")
    }
    assert centre_test_fk_referred == {"diagnostic_centres", "diagnostic_tests"}

    payment_fk_referred = {
        fk["referred_table"] for fk in inspector.get_foreign_keys("payments")
    }
    assert payment_fk_referred == {"bookings"}


def test_schema_can_persist_related_rows(db_session: Session) -> None:
    user = User(
        email="schema-test@example.com",
        password_hash="not-a-real-hash",
        full_name="Schema Tester",
    )
    centre = DiagnosticCentre(name="Central Lab", location="Bengaluru")
    test = DiagnosticTest(name="CBC", description="Complete blood count")
    db_session.add_all([user, centre, test])
    db_session.flush()

    centre_test = CentreTest(centre_id=centre.id, test_id=test.id, price=Decimal("499.00"))
    db_session.add(centre_test)
    db_session.flush()

    booking = Booking(
        user_id=user.id,
        test_id=test.id,
        centre_id=centre.id,
        appointment_at=datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc),
        amount=Decimal("499.00"),
        status=BookingStatus.PENDING,
    )
    db_session.add(booking)
    db_session.flush()

    payment = Payment(
        booking_id=booking.id,
        provider_event_id="evt_schema_test_1",
        amount=Decimal("499.00"),
        status=PaymentStatus.SUCCESS,
    )
    db_session.add(payment)
    db_session.flush()

    stored_amount = db_session.execute(
        text("SELECT amount FROM bookings WHERE id = :id"),
        {"id": booking.id},
    ).scalar_one()
    assert stored_amount == Decimal("499.00")
    assert booking.amount == centre_test.price


def test_centre_test_unique_constraint(db_session: Session) -> None:
    centre = DiagnosticCentre(name="East Lab", location="Hyderabad")
    test = DiagnosticTest(name="Lipid Panel")
    db_session.add_all([centre, test])
    db_session.flush()

    db_session.add(CentreTest(centre_id=centre.id, test_id=test.id, price=Decimal("700.00")))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                CentreTest(centre_id=centre.id, test_id=test.id, price=Decimal("800.00"))
            )
            db_session.flush()


def test_provider_event_id_unique_constraint(db_session: Session) -> None:
    user = User(
        email="webhook-test@example.com",
        password_hash="not-a-real-hash",
        full_name="Webhook Tester",
    )
    centre = DiagnosticCentre(name="West Lab", location="Pune")
    test = DiagnosticTest(name="Thyroid Profile")
    db_session.add_all([user, centre, test])
    db_session.flush()

    first_booking = Booking(
        user_id=user.id,
        test_id=test.id,
        centre_id=centre.id,
        appointment_at=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
        amount=Decimal("999.00"),
        status=BookingStatus.PENDING,
    )
    second_booking = Booking(
        user_id=user.id,
        test_id=test.id,
        centre_id=centre.id,
        appointment_at=datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc),
        amount=Decimal("999.00"),
        status=BookingStatus.PENDING,
    )
    db_session.add_all([first_booking, second_booking])
    db_session.flush()

    db_session.add(
        Payment(
            booking_id=first_booking.id,
            provider_event_id="evt_duplicate",
            amount=Decimal("999.00"),
            status=PaymentStatus.SUCCESS,
        )
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                Payment(
                    booking_id=second_booking.id,
                    provider_event_id="evt_duplicate",
                    amount=Decimal("999.00"),
                    status=PaymentStatus.FAILED,
                )
            )
            db_session.flush()
