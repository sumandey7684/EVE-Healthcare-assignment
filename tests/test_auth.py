from datetime import timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.security import create_access_token, verify_password

SIGNUP_PAYLOAD = {
    "email": "user@example.com",
    "password": "StrongPassword123",
    "full_name": "Suman Dey",
}


def _signup(client: TestClient, **overrides) -> object:
    payload = {**SIGNUP_PAYLOAD, **overrides}
    return client.post("/auth/signup", json=payload)


def test_signup_success(client: TestClient, db_session: Session) -> None:
    response = _signup(client)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "email", "full_name"}
    assert body["email"] == "user@example.com"
    assert body["full_name"] == "Suman Dey"
    assert "password" not in body
    assert "password_hash" not in body

    user = db_session.scalar(select(User).where(User.email == "user@example.com"))
    assert user is not None
    assert user.password_hash != SIGNUP_PAYLOAD["password"]
    assert verify_password(SIGNUP_PAYLOAD["password"], user.password_hash)


def test_signup_duplicate_email(client: TestClient) -> None:
    first = _signup(client)
    assert first.status_code == 201

    response = _signup(client, full_name="Someone Else")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_email"


def test_signup_normalizes_email_for_duplicates(client: TestClient) -> None:
    assert _signup(client, email="User@Example.com").status_code == 201

    response = _signup(client, email="user@example.com")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_email"


def test_signup_invalid_email(client: TestClient) -> None:
    response = _signup(client, email="not-an-email")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "password" not in str(body).lower() or "StrongPassword123" not in str(body)


def test_signup_invalid_password(client: TestClient) -> None:
    response = _signup(client, password="short")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert all(item.get("input") != "short" for item in body["error"]["details"])


def test_signup_response_never_includes_password_hash(client: TestClient) -> None:
    response = _signup(client)

    assert response.status_code == 201
    assert "password_hash" not in response.text
    assert "password" not in response.json()


def test_login_success(client: TestClient) -> None:
    assert _signup(client).status_code == 201

    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "StrongPassword123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str)
    assert body["access_token"]
    assert "password" not in body
    assert "password_hash" not in body


def test_login_wrong_password(client: TestClient) -> None:
    assert _signup(client).status_code == 201

    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "WrongPassword123"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert response.json()["error"]["message"] == "Invalid email or password."


def test_login_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "missing@example.com", "password": "StrongPassword123"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert response.json()["error"]["message"] == "Invalid email or password."


def test_auth_me_success(client: TestClient) -> None:
    signup = _signup(client)
    token = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "StrongPassword123"},
    ).json()["access_token"]

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == signup.json()["id"]
    assert body["email"] == "user@example.com"
    assert body["full_name"] == "Suman Dey"
    assert "password_hash" not in body
    assert "password" not in body


def test_auth_me_missing_token(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_auth_me_invalid_token(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_auth_me_malformed_bearer_token(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": "Token abc"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_auth_me_expired_token(client: TestClient) -> None:
    signup = _signup(client)
    token = create_access_token(
        user_id=UUID(signup.json()["id"]),
        expires_delta=timedelta(seconds=-1),
    )

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_auth_me_nonexistent_user(client: TestClient) -> None:
    token = create_access_token(user_id=uuid4())

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "user_not_found"
