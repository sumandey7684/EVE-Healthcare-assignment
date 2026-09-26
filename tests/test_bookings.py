from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, BookingStatus, CentreTest

FUTURE_APPOINTMENT = "2026-10-10T10:00:00Z"


def _auth_headers(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/auth/signup",
        json={"email": email, "password": "StrongPassword123", "full_name": "Booking Tester"},
    )
    token = client.post(
        "/auth/login",
        json={"email": email, "password": "StrongPassword123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_offering(client: TestClient, headers: dict[str, str], price: str = "450.00") -> tuple[dict, dict]:
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
    offered = client.post(
        f"/centres/{centre['id']}/tests",
        json={"test_id": test["id"], "price": price},
        headers=headers,
    )
    assert offered.status_code == 201
    return centre, test


def _create_booking(
    client: TestClient,
    headers: dict[str, str],
    centre_id: str,
    test_id: str,
    appointment_at: str = FUTURE_APPOINTMENT,
) -> object:
    return client.post(
        "/bookings",
        json={"centre_id": centre_id, "test_id": test_id, "appointment_at": appointment_at},
        headers=headers,
    )


def test_successful_booking(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, test = _seed_offering(client, headers)

    response = _create_booking(client, headers, centre["id"], test["id"])

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "user_id",
        "centre_id",
        "test_id",
        "appointment_at",
        "amount",
        "status",
    }
    assert body["centre_id"] == centre["id"]
    assert body["test_id"] == test["id"]
    assert body["status"] == "PENDING"
    assert Decimal(str(body["amount"])) == Decimal("450.00")
    assert "amount" not in {
        "centre_id": centre["id"],
        "test_id": test["id"],
        "appointment_at": FUTURE_APPOINTMENT,
    }


def test_unauthenticated_booking(client: TestClient) -> None:
    response = client.post(
        "/bookings",
        json={
            "centre_id": str(uuid4()),
            "test_id": str(uuid4()),
            "appointment_at": FUTURE_APPOINTMENT,
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_nonexistent_centre(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    _, test = _seed_offering(client, headers)

    response = _create_booking(client, headers, str(uuid4()), test["id"])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "centre_not_found"


def test_nonexistent_test(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, _ = _seed_offering(client, headers)

    response = _create_booking(client, headers, centre["id"], str(uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "test_not_found"


def test_test_not_available_at_centre(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, _ = _seed_offering(client, headers)
    other_test = client.post(
        "/tests",
        json={"name": "Lipid Panel"},
        headers=headers,
    ).json()

    response = _create_booking(client, headers, centre["id"], other_test["id"])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "test_not_offered"


def test_price_copied_from_centre_test(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, test = _seed_offering(client, headers, price="799.50")

    response = _create_booking(client, headers, centre["id"], test["id"])

    assert response.status_code == 201
    offering = db_session.scalar(
        select(CentreTest).where(
            CentreTest.centre_id == centre["id"],
            CentreTest.test_id == test["id"],
        )
    )
    assert offering is not None
    assert Decimal(str(response.json()["amount"])) == offering.price == Decimal("799.50")


def test_price_snapshot_unchanged_after_centre_price_change(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, test = _seed_offering(client, headers, price="450.00")
    created = _create_booking(client, headers, centre["id"], test["id"])
    assert created.status_code == 201

    offering = db_session.scalar(
        select(CentreTest).where(
            CentreTest.centre_id == centre["id"],
            CentreTest.test_id == test["id"],
        )
    )
    assert offering is not None
    offering.price = Decimal("999.00")
    db_session.commit()

    response = client.get(f"/bookings/{created.json()['id']}", headers=headers)
    stored = db_session.get(Booking, created.json()["id"])

    assert response.status_code == 200
    assert Decimal(str(response.json()["amount"])) == Decimal("450.00")
    assert stored is not None
    assert stored.amount == Decimal("450.00")
    assert offering.price == Decimal("999.00")


def test_appointment_in_the_past(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, test = _seed_offering(client, headers)

    response = _create_booking(
        client,
        headers,
        centre["id"],
        test["id"],
        appointment_at="2020-01-01T10:00:00Z",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_invalid_booking_id(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")

    response = client.get(f"/bookings/{uuid4()}", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "booking_not_found"


def test_user_can_view_own_booking(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, test = _seed_offering(client, headers)
    created = _create_booking(client, headers, centre["id"], test["id"])

    response = client.get(f"/bookings/{created.json()['id']}", headers=headers)
    listing = client.get("/bookings", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == created.json()["id"]
    assert [item["id"] for item in listing.json()] == [created.json()["id"]]


def test_user_cannot_view_another_users_booking(client: TestClient) -> None:
    owner_headers = _auth_headers(client, "owner@example.com")
    other_headers = _auth_headers(client, "other@example.com")
    centre, test = _seed_offering(client, owner_headers)
    created = _create_booking(client, owner_headers, centre["id"], test["id"])

    response = client.get(f"/bookings/{created.json()['id']}", headers=other_headers)
    listing = client.get("/bookings", headers=other_headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "booking_forbidden"
    assert listing.json() == []


def test_user_can_cancel_own_booking(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, test = _seed_offering(client, headers)
    created = _create_booking(client, headers, centre["id"], test["id"])

    response = client.post(f"/bookings/{created.json()['id']}/cancel", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_invalid_cancellation_state_transition(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, test = _seed_offering(client, headers)
    created = _create_booking(client, headers, centre["id"], test["id"])
    booking_id = created.json()["id"]

    first = client.post(f"/bookings/{booking_id}/cancel", headers=headers)
    second = client.post(f"/bookings/{booking_id}/cancel", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "invalid_booking_status"

    booking = db_session.get(Booking, booking_id)
    assert booking is not None
    booking.status = BookingStatus.FAILED
    db_session.commit()

    failed_cancel = client.post(f"/bookings/{booking_id}/cancel", headers=headers)
    assert failed_cancel.status_code == 409
    assert failed_cancel.json()["error"]["code"] == "invalid_booking_status"


def test_duplicate_active_booking(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, test = _seed_offering(client, headers)

    first = _create_booking(client, headers, centre["id"], test["id"])
    second = _create_booking(client, headers, centre["id"], test["id"])

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_booking"


def test_cancelled_booking_can_be_rebooked(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, test = _seed_offering(client, headers)
    first = _create_booking(client, headers, centre["id"], test["id"])
    client.post(f"/bookings/{first.json()['id']}/cancel", headers=headers)

    second = _create_booking(client, headers, centre["id"], test["id"])

    assert second.status_code == 201
    assert second.json()["status"] == "PENDING"


def test_client_cannot_supply_booking_amount(client: TestClient) -> None:
    headers = _auth_headers(client, "owner@example.com")
    centre, test = _seed_offering(client, headers)

    response = client.post(
        "/bookings",
        json={
            "centre_id": centre["id"],
            "test_id": test["id"],
            "appointment_at": FUTURE_APPOINTMENT,
            "amount": "1.00",
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
