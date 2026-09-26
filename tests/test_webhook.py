from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Payment

FUTURE_APPOINTMENT = "2026-10-10T10:00:00Z"


def _auth_headers(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/auth/signup",
        json={"email": email, "password": "StrongPassword123", "full_name": "Webhook Tester"},
    )
    token = client.post(
        "/auth/login",
        json={"email": email, "password": "StrongPassword123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _webhook_headers() -> dict[str, str]:
    return {"X-Webhook-Secret": settings.webhook_secret}


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


def _webhook_payload(booking: dict, **overrides) -> dict:
    payload = {
        "event_id": "evt_12345",
        "booking_id": booking["id"],
        "status": "SUCCESS",
        "amount": 450.00,
    }
    payload.update(overrides)
    return payload


def test_webhook_rejects_missing_secret(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post("/payments/webhook", json=_webhook_payload(booking))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_webhook_secret"


def test_webhook_rejects_invalid_secret(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking),
        headers={"X-Webhook-Secret": "definitely-not-the-webhook-secret"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_webhook_secret"
    assert client.get(f"/bookings/{booking['id']}", headers=headers).json()["status"] == "PENDING"


def test_success_webhook(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking),
        headers=_webhook_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "processed"}


def test_failed_webhook(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, status="FAILED"),
        headers=_webhook_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "processed"}


def test_invalid_event(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)
    payload = _webhook_payload(booking)
    payload.pop("event_id")

    response = client.post("/payments/webhook", json=payload, headers=_webhook_headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_invalid_booking(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, booking_id=str(uuid4())),
        headers=_webhook_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "booking_not_found"


def test_invalid_status(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, status="MAYBE"),
        headers=_webhook_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_amount_mismatch(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, amount=999.00),
        headers=_webhook_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "amount_mismatch"


def test_success_changes_pending_to_confirmed(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    client.post("/payments/webhook", json=_webhook_payload(booking), headers=_webhook_headers())
    updated = client.get(f"/bookings/{booking['id']}", headers=headers)

    assert updated.json()["status"] == "CONFIRMED"


def test_failed_changes_pending_to_failed(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, status="FAILED"),
        headers=_webhook_headers(),
    )
    updated = client.get(f"/bookings/{booking['id']}", headers=headers)

    assert updated.json()["status"] == "FAILED"


def test_cannot_change_confirmed_to_failed(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)
    client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, event_id="evt_success"),
        headers=_webhook_headers(),
    )

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, event_id="evt_fail", status="FAILED"),
        headers=_webhook_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_booking_status"
    assert client.get(f"/bookings/{booking['id']}", headers=headers).json()["status"] == "CONFIRMED"


def test_cannot_change_failed_to_confirmed(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)
    client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, event_id="evt_fail", status="FAILED"),
        headers=_webhook_headers(),
    )

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, event_id="evt_success", status="SUCCESS"),
        headers=_webhook_headers(),
    )

    assert response.status_code == 409
    assert client.get(f"/bookings/{booking['id']}", headers=headers).json()["status"] == "FAILED"


def test_cannot_change_cancelled_to_confirmed(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)
    client.post(f"/bookings/{booking['id']}/cancel", headers=headers)

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking),
        headers=_webhook_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_booking_status"
    assert client.get(f"/bookings/{booking['id']}", headers=headers).json()["status"] == "CANCELLED"


def test_same_webhook_sent_twice(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)
    payload = _webhook_payload(booking)

    first = client.post("/payments/webhook", json=payload, headers=_webhook_headers())
    second = client.post("/payments/webhook", json=payload, headers=_webhook_headers())

    assert first.json() == {"status": "processed"}
    assert second.json() == {"status": "already_processed"}
    payments = list(db_session.scalars(select(Payment).where(Payment.booking_id == booking["id"])).all())
    assert len(payments) == 1
    assert client.get(f"/bookings/{booking['id']}", headers=headers).json()["status"] == "CONFIRMED"


def test_same_webhook_sent_multiple_times(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)
    payload = _webhook_payload(booking)

    statuses = [
        client.post("/payments/webhook", json=payload, headers=_webhook_headers()).json()["status"]
        for _ in range(4)
    ]

    assert statuses[0] == "processed"
    assert statuses[1:] == ["already_processed"] * 3
    payments = list(db_session.scalars(select(Payment).where(Payment.booking_id == booking["id"])).all())
    assert len(payments) == 1
    assert payments[0].provider_event_id == "evt_12345"
    assert client.get(f"/bookings/{booking['id']}", headers=headers).json()["status"] == "CONFIRMED"


def test_duplicate_event_id_protected_by_database_constraint(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(client, "owner@example.com")
    first = _create_pending_booking(client, headers)
    client.post("/payments/webhook", json=_webhook_payload(first), headers=_webhook_headers())

    centre = client.post(
        "/centres",
        json={"name": "Second Lab", "location": "Pune"},
        headers=headers,
    ).json()
    test = client.post("/tests", json={"name": "Lipid Panel"}, headers=headers).json()
    client.post(
        f"/centres/{centre['id']}/tests",
        json={"test_id": test["id"], "price": "450.00"},
        headers=headers,
    )
    second = client.post(
        "/bookings",
        json={
            "centre_id": centre["id"],
            "test_id": test["id"],
            "appointment_at": "2026-10-11T10:00:00Z",
        },
        headers=headers,
    ).json()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                Payment(
                    booking_id=second["id"],
                    provider_event_id="evt_12345",
                    amount=Decimal("450.00"),
                    status="SUCCESS",
                )
            )
            db_session.flush()


def test_existing_payment_behavior_remains_correct(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    payment = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
    )
    updated = client.get(f"/bookings/{booking['id']}", headers=headers)

    assert payment.status_code == 201
    assert updated.json()["status"] == "CONFIRMED"


def test_webhook_correlates_existing_simulated_payment(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)
    payment = client.post(
        "/payments",
        json={"booking_id": booking["id"], "result": "SUCCESS"},
        headers=headers,
    ).json()

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, payment_id=payment["id"]),
        headers=_webhook_headers(),
    )

    payments = list(db_session.scalars(select(Payment).where(Payment.booking_id == booking["id"])).all())
    assert response.json() == {"status": "already_processed"}
    assert len(payments) == 1
    assert payments[0].provider_event_id == "evt_12345"
    assert client.get(f"/bookings/{booking['id']}", headers=headers).json()["status"] == "CONFIRMED"


def test_invalid_payment_id(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    booking = _create_pending_booking(client, headers)

    response = client.post(
        "/payments/webhook",
        json=_webhook_payload(booking, payment_id=str(uuid4())),
        headers=_webhook_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "payment_not_found"
