# EVE Healthcare Backend

Diagnostic test booking and simulated payment API for the EVE Healthcare SDE Intern Backend Engineering Assignment.

This repository is being built in small, verified phases. The current slice includes authentication plus diagnostic centre and test catalogue APIs.

## Tech stack

- Python 3.12
- FastAPI
- PostgreSQL
- SQLAlchemy 2.x
- Alembic
- Pydantic / pydantic-settings
- Pytest
- HTTPX
- Docker and Docker Compose

## How to run locally

Prerequisites: Python 3.12 and Docker (for PostgreSQL).

1. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy environment variables:

   ```powershell
   copy .env.example .env
   ```

4. Start PostgreSQL:

   ```powershell
   docker compose up db -d
   ```

   Compose publishes Postgres on host port **5433** so it does not clash with a local PostgreSQL install on 5432. Inside Docker the database still listens on 5432.

5. Apply database migrations:

   ```powershell
   alembic upgrade head
   ```

6. Start the API:

   ```powershell
   uvicorn app.main:app --reload
   ```

7. Check health:

   ```powershell
   curl http://127.0.0.1:8000/health
   ```

The expected response is `{"status":"ok"}`. Interactive docs are available at `http://127.0.0.1:8000/docs`.

## Authentication

Copy `.env.example` to `.env` and set a long random `JWT_SECRET_KEY`. Do not commit the real secret.

```
JWT_SECRET_KEY=change-me-to-a-long-random-string
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
```

### Sign up

```powershell
curl -X POST http://127.0.0.1:8000/auth/signup `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"user@example.com\",\"password\":\"StrongPassword123\",\"full_name\":\"Suman Dey\"}"
```

### Log in

```powershell
curl -X POST http://127.0.0.1:8000/auth/login `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"user@example.com\",\"password\":\"StrongPassword123\"}"
```

The response is `{"access_token":"...","token_type":"bearer"}`.

### Current user

Send the token as a Bearer token:

```powershell
curl http://127.0.0.1:8000/auth/me `
  -H "Authorization: Bearer <access_token>"
```

## Diagnostic centres and tests

Read endpoints are public so a reviewer can browse the catalogue without a token.

Create endpoints require a valid JWT. There is no admin role yet, so any authenticated user can add centres, tests, and centre-test prices. This is an assignment-only assumption, not a production permission model.

Prices always come from `centre_tests.price`, never from the test catalogue row. The same test can cost different amounts at different centres.

### Centres

```powershell
curl http://127.0.0.1:8000/centres
curl http://127.0.0.1:8000/centres/<centre_id>
```

Create a centre:

```powershell
curl -X POST http://127.0.0.1:8000/centres `
  -H "Authorization: Bearer <access_token>" `
  -H "Content-Type: application/json" `
  -d "{\"name\":\"City Diagnostics\",\"location\":\"Bengaluru\"}"
```

### Tests

```powershell
curl http://127.0.0.1:8000/tests
curl http://127.0.0.1:8000/tests/<test_id>
```

Create a test:

```powershell
curl -X POST http://127.0.0.1:8000/tests `
  -H "Authorization: Bearer <access_token>" `
  -H "Content-Type: application/json" `
  -d "{\"name\":\"CBC\",\"description\":\"Complete Blood Count\"}"
```

### Centre-specific tests and prices

```powershell
curl http://127.0.0.1:8000/centres/<centre_id>/tests
```

Example response:

```json
[
  {
    "id": "...",
    "name": "CBC",
    "description": "Complete Blood Count",
    "price": 450.0
  }
]
```

Offer a test at a centre:

```powershell
curl -X POST http://127.0.0.1:8000/centres/<centre_id>/tests `
  -H "Authorization: Bearer <access_token>" `
  -H "Content-Type: application/json" `
  -d "{\"test_id\":\"<test_id>\",\"price\":450.00}"
```

A repeated centre-test pair returns `409` because of the database unique constraint on `(centre_id, test_id)`.

### Sample data

Optional development seed. It does not run at application startup:

```powershell
.\.venv\Scripts\python.exe scripts\seed_catalogue.py
```

This creates 2 centres, 3 tests, and a few centre-specific prices. It skips rows that already exist.

## How to run with Docker

```powershell
docker compose up --build
```

This starts PostgreSQL and the FastAPI application. The API is available at `http://127.0.0.1:8000`.

If you already have PostgreSQL running on host port 5432, keep the Compose host mapping at 5433 (the default in this repo) and point local `DATABASE_URL` at `localhost:5433`.

To stop the stack:

```powershell
docker compose down
```

## Current implementation status

Implemented:

- Project layout for a maintainable FastAPI service
- Environment-based configuration
- PostgreSQL / SQLAlchemy connection setup
- Database models: User, DiagnosticCentre, DiagnosticTest, CentreTest, Booking, Payment
- Initial Alembic migration
- Docker and Docker Compose
- `GET /health`
- User signup, login, and JWT-protected `GET /auth/me`
- Diagnostic centres, tests, and centre-specific prices

Not implemented yet:

- Booking APIs
- Simulated payments and webhook idempotency
