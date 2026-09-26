"""Every error the API returns must use the same {"error": {"code", "message"}} envelope."""

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


def test_wrong_method_uses_error_envelope(client: TestClient) -> None:
    response = client.patch("/centres")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert response.headers["allow"]


def test_unhandled_exception_uses_error_envelope_without_leaking_details() -> None:
    def broken_get_db():
        raise RuntimeError("database exploded with secret details")
        yield  # pragma: no cover - makes this a generator like get_db

    original_debug = app.debug
    app.dependency_overrides[get_db] = broken_get_db
    # Starlette returns HTML tracebacks when debug=True; force the production path.
    app.debug = False
    app.middleware_stack = None
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.get("/centres")
    finally:
        app.dependency_overrides.clear()
        app.debug = original_debug
        app.middleware_stack = None

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_server_error", "message": "An unexpected error occurred."}
    }
    assert "secret details" not in response.text
