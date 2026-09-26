from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

SIGNUP_PAYLOAD = {
    "email": "catalogue-user@example.com",
    "password": "StrongPassword123",
    "full_name": "Catalogue Tester",
}


def _auth_headers(client: TestClient) -> dict[str, str]:
    client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    token = client.post(
        "/auth/login",
        json={"email": SIGNUP_PAYLOAD["email"], "password": SIGNUP_PAYLOAD["password"]},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_centre(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    payload = {"name": "Central Lab", "location": "Bengaluru", **overrides}
    response = client.post("/centres", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _create_test(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    payload = {"name": "CBC", "description": "Complete Blood Count", **overrides}
    response = client.post("/tests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def test_list_centres(client: TestClient) -> None:
    headers = _auth_headers(client)
    first = _create_centre(client, headers, name="West Lab", location="Pune")
    second = _create_centre(client, headers, name="East Lab", location="Hyderabad")

    response = client.get("/centres")

    assert response.status_code == 200
    body = response.json()
    names = [item["name"] for item in body]
    assert names == ["East Lab", "West Lab"]
    assert {item["id"] for item in body} == {first["id"], second["id"]}


def test_get_centre(client: TestClient) -> None:
    headers = _auth_headers(client)
    created = _create_centre(client, headers)

    response = client.get(f"/centres/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_unknown_centre(client: TestClient) -> None:
    response = client.get(f"/centres/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "centre_not_found"


def test_list_tests(client: TestClient) -> None:
    headers = _auth_headers(client)
    first = _create_test(client, headers, name="Lipid Panel")
    second = _create_test(client, headers, name="CBC")

    response = client.get("/tests")

    assert response.status_code == 200
    names = [item["name"] for item in response.json()]
    assert names == ["CBC", "Lipid Panel"]
    assert {item["id"] for item in response.json()} == {first["id"], second["id"]}


def test_get_test(client: TestClient) -> None:
    headers = _auth_headers(client)
    created = _create_test(client, headers)

    response = client.get(f"/tests/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created
    assert "price" not in response.json()


def test_unknown_test(client: TestClient) -> None:
    response = client.get(f"/tests/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "test_not_found"


def test_create_centre(client: TestClient) -> None:
    headers = _auth_headers(client)

    response = client.post(
        "/centres",
        json={"name": "  Central Lab  ", "location": "  Bengaluru  "},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "name", "location"}
    assert body["name"] == "Central Lab"
    assert body["location"] == "Bengaluru"


def test_create_test(client: TestClient) -> None:
    headers = _auth_headers(client)

    response = client.post(
        "/tests",
        json={"name": "Thyroid Profile", "description": "TSH, T3, T4"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "name", "description"}
    assert body["name"] == "Thyroid Profile"


def test_add_test_to_centre_and_list_centre_tests(client: TestClient) -> None:
    headers = _auth_headers(client)
    centre = _create_centre(client, headers)
    test = _create_test(client, headers)

    created = client.post(
        f"/centres/{centre['id']}/tests",
        json={"test_id": test["id"], "price": "450.00"},
        headers=headers,
    )

    assert created.status_code == 201
    assert created.json()["id"] == test["id"]
    assert created.json()["name"] == "CBC"
    assert Decimal(str(created.json()["price"])) == Decimal("450.00")

    response = client.get(f"/centres/{centre['id']}/tests")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == test["id"]
    assert Decimal(str(body[0]["price"])) == Decimal("450.00")


def test_centre_specific_price(client: TestClient) -> None:
    headers = _auth_headers(client)
    first_centre = _create_centre(client, headers, name="City Lab")
    second_centre = _create_centre(client, headers, name="Metro Lab", location="Delhi")
    test = _create_test(client, headers)

    client.post(
        f"/centres/{first_centre['id']}/tests",
        json={"test_id": test["id"], "price": "450.00"},
        headers=headers,
    )
    client.post(
        f"/centres/{second_centre['id']}/tests",
        json={"test_id": test["id"], "price": "799.50"},
        headers=headers,
    )

    first_prices = client.get(f"/centres/{first_centre['id']}/tests").json()
    second_prices = client.get(f"/centres/{second_centre['id']}/tests").json()
    catalogue_test = client.get(f"/tests/{test['id']}").json()

    assert Decimal(str(first_prices[0]["price"])) == Decimal("450.00")
    assert Decimal(str(second_prices[0]["price"])) == Decimal("799.50")
    assert "price" not in catalogue_test


def test_duplicate_centre_test_relationship(client: TestClient) -> None:
    headers = _auth_headers(client)
    centre = _create_centre(client, headers)
    test = _create_test(client, headers)
    payload = {"test_id": test["id"], "price": "450.00"}

    first = client.post(f"/centres/{centre['id']}/tests", json=payload, headers=headers)
    second = client.post(f"/centres/{centre['id']}/tests", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_centre_test"


def test_invalid_price(client: TestClient) -> None:
    headers = _auth_headers(client)
    centre = _create_centre(client, headers)
    test = _create_test(client, headers)

    response = client.post(
        f"/centres/{centre['id']}/tests",
        json={"test_id": test["id"], "price": 0},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_invalid_uuid(client: TestClient) -> None:
    response = client.get("/centres/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unauthorized_management_endpoints(client: TestClient) -> None:
    centre_response = client.post(
        "/centres",
        json={"name": "Central Lab", "location": "Bengaluru"},
    )
    test_response = client.post("/tests", json={"name": "CBC"})
    offering_response = client.post(
        f"/centres/{uuid4()}/tests",
        json={"test_id": str(uuid4()), "price": "450.00"},
    )

    assert centre_response.status_code == 401
    assert test_response.status_code == 401
    assert offering_response.status_code == 401
    assert centre_response.json()["error"]["code"] == "missing_token"


def test_empty_centre_name_is_rejected(client: TestClient) -> None:
    headers = _auth_headers(client)

    response = client.post(
        "/centres",
        json={"name": "   ", "location": "Bengaluru"},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_add_unknown_test_to_centre(client: TestClient) -> None:
    headers = _auth_headers(client)
    centre = _create_centre(client, headers)

    response = client.post(
        f"/centres/{centre['id']}/tests",
        json={"test_id": str(uuid4()), "price": "450.00"},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "test_not_found"
