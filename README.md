# EVE Healthcare Backend

Diagnostic test booking and simulated payment API for the EVE Healthcare SDE Intern Backend Engineering Assignment.

This repository is being built in small, verified phases. The current slice includes authentication, the catalogue, bookings, simulated payments, an idempotent payment webhook, and concurrency-safe settlement/booking constraints.

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
WEBHOOK_SECRET=change-me-webhook-secret
```

`WEBHOOK_SECRET` must be at least 16 characters. `POST /payments/webhook` requires it in the `X-Webhook-Secret` header.

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

## Bookings

All booking endpoints require a valid JWT. A user can only list, view, or cancel their own bookings. Another user's booking ID returns `403`.

The client never sends an amount. The backend copies `CentreTest.price` into `Booking.amount` at create time. Later catalogue price changes do not update existing bookings.

### Endpoints

```powershell
curl -X POST http://127.0.0.1:8000/bookings `
  -H "Authorization: Bearer <access_token>" `
  -H "Content-Type: application/json" `
  -d "{\"centre_id\":\"<centre_id>\",\"test_id\":\"<test_id>\",\"appointment_at\":\"2026-10-10T10:00:00Z\"}"

curl http://127.0.0.1:8000/bookings -H "Authorization: Bearer <access_token>"
curl http://127.0.0.1:8000/bookings/<booking_id> -H "Authorization: Bearer <access_token>"
curl -X POST http://127.0.0.1:8000/bookings/<booking_id>/cancel -H "Authorization: Bearer <access_token>"
```

Example create response:

```json
{
  "id": "...",
  "user_id": "...",
  "centre_id": "...",
  "test_id": "...",
  "appointment_at": "2026-10-10T10:00:00Z",
  "amount": 450.0,
  "status": "PENDING"
}
```

### Lifecycle

- New bookings are created as `PENDING`.
- The owner can cancel a `PENDING` booking. It becomes `CANCELLED`.
- Simulated `POST /payments` with `SUCCESS` sets the booking to `CONFIRMED`.
- Simulated `POST /payments` with `FAILED` sets the booking to `FAILED`.
- Invalid transitions return `409`. A cancelled, confirmed, or failed booking cannot be paid or cancelled again.

### Duplicate bookings

A user cannot create a second **active** booking (`PENDING` or `CONFIRMED`) for the same centre, test, and appointment time. After cancellation they can book that slot again.

The application check still returns `409 duplicate_booking`. A PostgreSQL partial unique index `uq_bookings_active_slot` on `(user_id, centre_id, test_id, appointment_at) WHERE status IN ('PENDING', 'CONFIRMED')` also rejects concurrent inserts that both pass the read check. `CANCELLED` and `FAILED` rows are excluded, so the slot can be booked again.

## Simulated payments

`POST /payments` is authenticated and simulated. There is no Razorpay/Stripe integration.

The owner must pay their own `PENDING` booking. The payment amount is copied from `Booking.amount`, never from the request. Payment creation and the booking status change happen in one database transaction. The booking row is locked with `SELECT ... FOR UPDATE`, and `payments.booking_id` is UNIQUE, so concurrent `POST /payments` requests cannot settle the same booking twice.

```powershell
curl -X POST http://127.0.0.1:8000/payments `
  -H "Authorization: Bearer <access_token>" `
  -H "Content-Type: application/json" `
  -d "{\"booking_id\":\"<booking_id>\",\"result\":\"SUCCESS\"}"
```

`result` must be `SUCCESS` or `FAILED`.

Example response:

```json
{
  "id": "...",
  "booking_id": "...",
  "amount": 450.0,
  "status": "SUCCESS"
}
```

- `SUCCESS` → booking becomes `CONFIRMED`
- `FAILED` → booking becomes `FAILED`
- Another user's booking → `403`
- Missing booking → `404`
- `CANCELLED`, `CONFIRMED`, or `FAILED` booking → `409`

`POST /payments` creates a payment **without** `provider_event_id`. The webhook is a separate simulated provider callback.

## Payment webhook

`POST /payments/webhook` is not a user JWT endpoint. It requires the shared `WEBHOOK_SECRET` in the `X-Webhook-Secret` header. A missing or incorrect secret returns `401 invalid_webhook_secret`.

```powershell
curl -X POST http://127.0.0.1:8000/payments/webhook `
  -H "Content-Type: application/json" `
  -H "X-Webhook-Secret: <WEBHOOK_SECRET>" `
  -d "{\"event_id\":\"evt_12345\",\"booking_id\":\"<booking_id>\",\"status\":\"SUCCESS\",\"amount\":450.00}"
```

`status` must be `SUCCESS` or `FAILED`. The webhook amount is compared with `Booking.amount` and rejected on mismatch. The stored payment amount is always the booking snapshot.

### Idempotency

`event_id` is stored on `payments.provider_event_id`, which has a database UNIQUE constraint.

1. Look up the event id.
2. If it already exists, return `{"status":"already_processed"}` and do not change the booking.
3. Lock the booking row, then look up the event id again so a concurrent replay cannot miss the insert.
4. Otherwise create/link the payment and update the booking in one transaction.
5. If two requests still race, `uq_payments_provider_event_id` or `uq_payments_booking_id` raises a conflict. The loser rolls back and returns `already_processed`.

Repeated deliveries of the same `event_id` do not create a second payment and do not change booking state again.

### State transitions

- `SUCCESS` on `PENDING` → `CONFIRMED`
- `FAILED` on `PENDING` → `FAILED`
- `CONFIRMED` → `FAILED`, `FAILED` → `CONFIRMED`, and any webhook against `CANCELLED` are rejected (`409`)
- A replay of an already stored `event_id` is idempotent, not a transition error

### Relationship with `POST /payments`

Either path can settle a `PENDING` booking. They must not create two payments for the same provider event.

- In-app `POST /payments` settles the booking and leaves `provider_event_id` empty.
- A later webhook with the same `booking_id` and the returned `payment_id` attaches `event_id` to that payment and returns `already_processed`.
- A later webhook with a **new** `event_id` and no matching `payment_id` is rejected if the booking is already terminal.

## How to run with Docker

```powershell
docker compose up --build
```

This starts PostgreSQL and the FastAPI application. The API container runs `alembic upgrade head` before uvicorn, so a fresh Compose database receives the current schema automatically. The API is available at `http://127.0.0.1:8000`.

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
- Authenticated bookings with owner-only access and price snapshots
- Simulated `POST /payments` that confirms or fails a booking
- Idempotent `POST /payments/webhook` using `provider_event_id`
- Shared webhook secret, one payment per booking, and a partial unique index on active booking slots
- Docker Compose schema initialization via Alembic on API startup

Not implemented yet:

- Bonus features such as Redis, Celery, or a real payment provider
