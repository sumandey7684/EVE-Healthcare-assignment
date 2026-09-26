from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, Payment, PaymentStatus

# Computed relative to "now" so the suite does not break once a fixed date passes.
FUTURE_APPOINTMENT = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _auth_headers(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/auth/signup",
        json={"email": email, "password": "StrongPassword123", "full_name": "Payment Tester"},
    )
    token = client.post(
        "/auth/login",
        json={"email": email, "password": "StrongPassword123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_pending_booking(client: TestClient, headers: dict[str, str], price: str = "450.00") -> dict:
    centre = client.post(
        "/centres",
        json={"name": "City Lab", "location": "Bengaluru"},
        headers=headers,
    ).json()
    test = client.post(
        "/tests",
        json={"name": "CBC", "description": "Complete Blood Count"},
        headers=headers,
    ).json()
    client.post(
        f"/centres/{centre['id']}/tests",
        json={"test_id": test["id"], "price": price},
        headers=headers,
    )
    booking = client.post(
        "/bookings",
        json={
            "centre_id": centre["id"],
            "test_id": test["id"],
            "appointment_at": FUTURE_APPOINTMENT,
        },
        headers=headers,
    )
    assert booking.status_code == 201
    return booking.json()


def test_successful_payment(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "booking_id", "amount", "status"}
    assert body["booking_id"] == booking["id"]
    assert body["status"] == "SUCCESS"
    assert Decimal(str(body["amount"])) == Decimal("450.00")


def test_failed_payment(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "FAILED"},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"


def test_unauthenticated_payment(client: TestClient) -> None:
    response = client.post(
        "/payments",
        json={"booking_id": str(uuid4()), "result": "SUCCESS"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_invalid_booking_id(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")

    response = client.post(
        "/payments",
        json={"booking_id": str(uuid4()), "result": "SUCCESS"},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "booking_not_found"


def test_another_users_booking(client: TestClient) -> None:
    owner_headers = _auth_headers(client, "owner@example.com")
    other_headers = _auth_headers(client, "other@example.com")
    booking = _create_pending_booking(client, owner_headers)

    response = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=other_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "booking_forbidden"


def test_payment_for_cancelled_booking(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)
    client.post(f"/bookings/{booking['id']}/cancel", headers=headers)

    response = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_booking_status"


def test_payment_for_confirmed_booking(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)
    first = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
    )
    second = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "invalid_booking_status"


def test_payment_for_failed_booking(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)
    first = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "FAILED"},
        headers=headers,
    )
    second = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "invalid_booking_status"


def test_invalid_payment_result(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "MAYBE"},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_payment_amount_comes_from_booking(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers, price="799.50")

    response = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
    )

    payment = db_session.get(Payment, response.json()["id"])
    stored_booking = db_session.get(Booking, booking["id"])

    assert response.status_code == 201
    assert payment is not None
    assert stored_booking is not None
    assert payment.amount == stored_booking.amount == Decimal("799.50")


def test_success_confirms_booking(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
    )
    updated = client.get(f"/bookings/{booking['id']}", headers=headers)

    assert updated.status_code == 200
    assert updated.json()["status"] == "CONFIRMED"
    assert Decimal(str(updated.json()["amount"])) == Decimal("450.00")


def test_failed_marks_booking_failed(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "FAILED"},
        headers=headers,
    )
    updated = client.get(f"/bookings/{booking['id']}", headers=headers)

    assert updated.json()["status"] == "FAILED"


def test_payment_and_booking_update_are_consistent(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
    )

    stored_booking = db_session.get(Booking, booking["id"])
    payments = list(
        db_session.scalars(select(Payment).where(Payment.booking_id == booking["id"])).all()
    )

    assert response.status_code == 201
    assert stored_booking is not None
    assert stored_booking.status.value == "CONFIRMED"
    assert len(payments) == 1
    assert payments[0].status == PaymentStatus.SUCCESS
    assert payments[0].amount == stored_booking.amount
    assert payments[0].provider_event_id is None


def test_trailing_slash_form_from_assignment_is_served_directly(client: TestClient) -> None:
    """The assignment names the endpoint `POST /payments/`; it must not answer with a 307."""
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments/",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
        follow_redirects=False,
    )

    assert response.status_code == 201
    assert response.json()["status"] == "SUCCESS"
    assert client.get(f"/bookings/{booking['id']}", headers=headers).json()["status"] == "CONFIRMED"


def test_client_cannot_supply_payment_amount(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS", "amount": "1.00"},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
