# EVE Healthcare Backend

Diagnostic test booking and simulated payment API for the EVE Healthcare SDE Intern Backend Engineering Assignment.

A patient signs up, logs in, browses diagnostic centres and the tests each centre offers at its own price, books a test for a future appointment, and settles the booking either through the simulated `POST /payments` endpoint or through an idempotent provider webhook. The backend owns every price and every state transition; the client never supplies an amount.

## Contents

- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Setup (local)](#setup-local)
- [Setup (Docker Compose)](#setup-docker-compose)
- [Environment variables](#environment-variables)
- [Database and migrations](#database-and-migrations)
- [API overview](#api-overview)
- [Error format](#error-format)
- [Authentication](#authentication)
- [Catalogue](#catalogue)
- [Bookings](#bookings)
- [Simulated payments](#simulated-payments)
- [Payment webhook](#payment-webhook)
- [Idempotency strategy](#idempotency-strategy)
- [Concurrency protection](#concurrency-protection)
- [Testing](#testing)
- [Known limitations](#known-limitations)

## Architecture

```
app/
  main.py          FastAPI app, router registration, error handlers
  config.py        Settings loaded from environment variables (pydantic-settings)
  database.py      SQLAlchemy engine, SessionLocal, Base, get_db dependency
  security.py      bcrypt password hashing, JWT encode/decode
  errors.py        AppError and the consistent JSON error envelope
  api/             HTTP routers only (auth, centres, tests, bookings, payments, health)
  schemas/         Pydantic request/response models
  services/        Business rules and database transactions
  models/          SQLAlchemy 2.x mapped classes
alembic/           Migrations (two revisions)
tests/             Pytest suite (HTTP via TestClient + direct DB checks)
scripts/           docker-entrypoint.sh, optional catalogue seed
```

Request flow: router → Pydantic schema validation → service (business rule + one transaction) → SQLAlchemy model → PostgreSQL. Routers never touch the session directly beyond passing it to a service; services raise `AppError`, which the global handler turns into the JSON error envelope.

Domain model:

- `users` — email (unique), bcrypt password hash, full name
- `diagnostic_centres`, `diagnostic_tests` — catalogue
- `centre_tests` — a test offered by a centre **with that centre's price**; unique per `(centre_id, test_id)`
- `bookings` — user, centre, test, `appointment_at`, **amount snapshot**, status (`PENDING`, `CONFIRMED`, `FAILED`, `CANCELLED`)
- `payments` — one row per settled booking (`booking_id` unique), `provider_event_id` unique, amount, status (`SUCCESS`, `FAILED`)

All primary keys are UUIDs. Money is `NUMERIC(10,2)`. Timestamps are `timestamptz`. Statuses are native PostgreSQL enums.

## Tech stack

- Python 3.12, FastAPI, Pydantic v2 / pydantic-settings
- PostgreSQL 16, SQLAlchemy 2.x, Alembic, psycopg 3
- PyJWT (HS256), bcrypt
- Pytest, HTTPX (FastAPI `TestClient`)
- Docker and Docker Compose

## Setup (local)

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

3. Create your environment file and set real secrets:

   ```powershell
   copy .env.example .env
   ```

   `JWT_SECRET_KEY` and `WEBHOOK_SECRET` are required and must be at least 16 characters. Do not commit `.env` (it is git-ignored).

4. Start PostgreSQL:

   ```powershell
   docker compose up db -d
   ```

   Compose publishes Postgres on host port **5433** so it does not clash with a local PostgreSQL install on 5432. Inside Docker the database still listens on 5432.

5. Apply database migrations:

   ```powershell
   alembic upgrade head
   ```

6. Start the API (port 8000):

   ```powershell
   uvicorn app.main:app --reload
   ```

7. Check health:

   ```powershell
   curl http://127.0.0.1:8000/health
   ```

   Expected: `{"status":"ok"}`. Swagger UI is at `http://127.0.0.1:8000/docs`, OpenAPI JSON at `/openapi.json`.

Optional development seed (2 centres, 3 tests, a few prices; safe to re-run, never runs at startup):

```powershell
.\.venv\Scripts\python.exe scripts\seed_catalogue.py
```

## Setup (Docker Compose)

```powershell
docker compose up --build
```

This starts PostgreSQL (`db`) and the API (`api`). The API container's entrypoint runs `alembic upgrade head` before starting uvicorn, so a fresh database receives the full schema automatically. The API listens on `http://127.0.0.1:8000`; Postgres is published on host port 5433.

Compose falls back to placeholder secrets (`change-me-...`) when `JWT_SECRET_KEY` / `WEBHOOK_SECRET` are not set in your shell or `.env`. That is fine for local review; set real values for anything beyond that.

Stop the stack:

```powershell
docker compose down
```

Add `-v` to also delete the database volume.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | no | `postgresql+psycopg://eve:eve@localhost:5433/eve_healthcare` | SQLAlchemy URL (Compose sets `db:5432`) |
| `JWT_SECRET_KEY` | **yes** | — | HS256 signing key, min 16 chars |
| `JWT_ALGORITHM` | no | `HS256` | JWT algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | no | `60` | Access token lifetime |
| `WEBHOOK_SECRET` | **yes** | — | Shared secret for `X-Webhook-Secret`, min 16 chars |
| `APP_NAME` | no | `EVE Healthcare` | OpenAPI title |
| `ENVIRONMENT` | no | `development` | Tests refuse to run when `production` |
| `DEBUG` | no | `false` | `true` returns stack traces instead of the JSON error envelope; keep `false` |

## Database and migrations

Alembic revisions:

1. `90eacca781c5` — all tables, foreign keys, indexes, `uq_users_email`, `uq_centre_tests_centre_id_test_id`, `uq_payments_provider_event_id`, enums `booking_status` and `payment_status`
2. `b7c2d4e91a10` — `uq_payments_booking_id` (one payment per booking) and the partial unique index `uq_bookings_active_slot ON bookings (user_id, centre_id, test_id, appointment_at) WHERE status IN ('PENDING', 'CONFIRMED')`

Commands:

```powershell
alembic upgrade head     # apply
alembic check            # confirm models and database agree (no pending autogenerate)
alembic downgrade -1     # roll back one revision
```

## API overview

| Method | Path | Auth | Purpose | Success | Important errors |
|---|---|---|---|---|---|
| GET | `/health` | none | Liveness | 200 | — |
| POST | `/auth/signup` | none | Create user | 201 | 409 `duplicate_email`, 422 |
| POST | `/auth/login` | none | Get JWT | 200 | 401 `invalid_credentials` |
| GET | `/auth/me` | JWT | Current user | 200 | 401 `missing_token` / `invalid_token` / `token_expired` / `user_not_found` |
| GET | `/centres` | none | List centres | 200 | — |
| POST | `/centres` | JWT | Create centre | 201 | 401, 422 |
| GET | `/centres/{centre_id}` | none | Centre detail | 200 | 404 `centre_not_found` |
| GET | `/centres/{centre_id}/tests` | none | Tests offered at the centre **with centre price** | 200 | 404 `centre_not_found` |
| POST | `/centres/{centre_id}/tests` | JWT | Offer a test at a centre with a price | 201 | 404 `centre_not_found` / `test_not_found`, 409 `duplicate_centre_test`, 422 |
| GET | `/tests` | none | List tests (no price) | 200 | — |
| POST | `/tests` | JWT | Create test | 201 | 401, 422 |
| GET | `/tests/{test_id}` | none | Test detail | 200 | 404 `test_not_found` |
| POST | `/bookings` | JWT | Create booking (`PENDING`, amount snapshot) | 201 | 400 `test_not_offered`, 404, 409 `duplicate_booking`, 422 |
| GET | `/bookings` | JWT | List **own** bookings | 200 | 401 |
| GET | `/bookings/{booking_id}` | JWT | Own booking detail | 200 | 403 `booking_forbidden`, 404 `booking_not_found` |
| POST | `/bookings/{booking_id}/cancel` | JWT | Cancel own `PENDING` booking | 200 | 403, 404, 409 `invalid_booking_status` |
| POST | `/payments` (also `/payments/`) | JWT | Simulated payment for own `PENDING` booking | **201** | 403, 404, 409 `invalid_booking_status`, 422 |
| POST | `/payments/webhook` (also `/payments/webhook/`) | `X-Webhook-Secret` | Provider payment event, idempotent | 200 | 401 `invalid_webhook_secret`, 400 `payment_booking_mismatch`, 404, 409 `amount_mismatch` / `invalid_booking_status` / `payment_already_linked`, 422 |

Notes:

- Create endpoints return **201 Created** with the created resource; `POST /payments` therefore returns 201, not 200.
- The assignment names the payment endpoints with trailing slashes (`/payments/`, `/payments/webhook/`). Both spellings are served directly (no redirect); the trailing-slash forms are hidden from the OpenAPI document to avoid duplicates.
- Request bodies for bookings and payments use `extra="forbid"`: any client-supplied `amount` is rejected with 422.

## Error format

Every error is JSON with the same envelope:

```json
{ "error": { "code": "booking_forbidden", "message": "You cannot access another user's booking." } }
```

Validation errors (422) add a `details` list with the Pydantic error items; the `input` of password fields is stripped. Framework errors use the same shape: unknown route → 404 `not_found`, wrong method → 405 `method_not_allowed`, unexpected failure → 500 `internal_server_error` (no stack trace is returned when `DEBUG=false`).

## Authentication

Passwords are hashed with bcrypt (72-byte input limit enforced by validation). Login failures always return the same 401 `invalid_credentials`, and a dummy hash is verified for unknown emails to keep timing similar. JWTs are HS256, signed with `JWT_SECRET_KEY`, carry `sub` = user UUID, `iat`, `exp`, and are verified with the algorithm pinned.

```powershell
curl -X POST http://127.0.0.1:8000/auth/signup `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"user@example.com\",\"password\":\"StrongPassword123\",\"full_name\":\"Suman Dey\"}"

curl -X POST http://127.0.0.1:8000/auth/login `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"user@example.com\",\"password\":\"StrongPassword123\"}"
```

Login returns `{"access_token":"...","token_type":"bearer"}`. Send it as `Authorization: Bearer <access_token>`:

```powershell
curl http://127.0.0.1:8000/auth/me -H "Authorization: Bearer <access_token>"
```

Signup requires a password of 8–72 characters containing at least one letter and one digit. Emails are normalised to lower case, so `User@Example.com` and `user@example.com` are the same account. Responses never include the password or its hash.

## Catalogue

Read endpoints are public so a reviewer can browse without a token. Create endpoints require a valid JWT. There is no admin role: any authenticated user can add centres, tests and prices. This is an assignment-scope assumption, not a production permission model.

Prices live only on `centre_tests.price`. `GET /tests/{id}` deliberately has no price; the same test can cost different amounts at different centres.

```powershell
curl http://127.0.0.1:8000/centres
curl http://127.0.0.1:8000/centres/<centre_id>/tests
```

Example `GET /centres/{centre_id}/tests` response:

```json
[
  { "id": "...", "name": "CBC", "description": "Complete Blood Count", "price": "450.00" }
]
```

Create a centre, a test, and offer the test at the centre:

```powershell
curl -X POST http://127.0.0.1:8000/centres `
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" `
  -d "{\"name\":\"City Diagnostics\",\"location\":\"Bengaluru\"}"

curl -X POST http://127.0.0.1:8000/tests `
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" `
  -d "{\"name\":\"CBC\",\"description\":\"Complete Blood Count\"}"

curl -X POST http://127.0.0.1:8000/centres/<centre_id>/tests `
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" `
  -d "{\"test_id\":\"<test_id>\",\"price\":450.00}"
```

A repeated centre/test pair returns 409 `duplicate_centre_test` from the database unique constraint. There is no price-update endpoint; a price change would be a new catalogue operation and never alters existing bookings.

## Bookings

All booking endpoints require a JWT. Users see only their own bookings; another user's booking id returns 403 `booking_forbidden`.

```powershell
curl -X POST http://127.0.0.1:8000/bookings `
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" `
  -d "{\"centre_id\":\"<centre_id>\",\"test_id\":\"<test_id>\",\"appointment_at\":\"2027-01-15T10:00:00Z\"}"

curl http://127.0.0.1:8000/bookings -H "Authorization: Bearer <access_token>"
curl http://127.0.0.1:8000/bookings/<booking_id> -H "Authorization: Bearer <access_token>"
curl -X POST http://127.0.0.1:8000/bookings/<booking_id>/cancel -H "Authorization: Bearer <access_token>"
```

Example response:

```json
{
  "id": "...", "user_id": "...", "centre_id": "...", "test_id": "...",
  "appointment_at": "2027-01-15T10:00:00Z", "amount": "450.00", "status": "PENDING"
}
```

Rules enforced on create:

- centre and test must exist (404) and the test must be offered at that centre (400 `test_not_offered`)
- `appointment_at` must be timezone-aware and in the future (422)
- the client cannot send `amount`; the backend copies `centre_tests.price` into `bookings.amount` once. Later price changes never touch existing bookings — the amount is a historical snapshot and nothing in the API can modify it.
- a user may hold only one **active** (`PENDING` or `CONFIRMED`) booking per centre/test/appointment time (409 `duplicate_booking`); after `CANCELLED` or `FAILED` the slot can be booked again

State machine:

| From | Event | To |
|---|---|---|
| `PENDING` | `POST /payments` result `SUCCESS`, or webhook `SUCCESS` | `CONFIRMED` |
| `PENDING` | `POST /payments` result `FAILED`, or webhook `FAILED` | `FAILED` |
| `PENDING` | `POST /bookings/{id}/cancel` | `CANCELLED` |
| `CONFIRMED`, `FAILED`, `CANCELLED` | any pay / cancel / webhook | 409 `invalid_booking_status` (terminal) |

## Simulated payments

`POST /payments` is authenticated and deterministic; there is no real payment provider. The caller chooses the outcome:

```powershell
curl -X POST http://127.0.0.1:8000/payments `
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" `
  -d "{\"booking_id\":\"<booking_id>\",\"result\":\"SUCCESS\"}"
```

`result` must be `SUCCESS` or `FAILED`. Response (201):

```json
{ "id": "...", "booking_id": "...", "amount": "450.00", "status": "SUCCESS" }
```

- The booking must belong to the caller (403) and be `PENDING` (409).
- `payments.amount` is copied from `bookings.amount`; the request cannot carry an amount.
- Payment insert and booking status update happen in **one transaction** while the booking row is locked (`SELECT ... FOR UPDATE`).
- `SUCCESS` → booking `CONFIRMED`; `FAILED` → booking `FAILED`. A failed booking is terminal; the patient books the slot again.
- A simulated payment has no `provider_event_id`; a later webhook can attach one (see below).

## Payment webhook

`POST /payments/webhook` represents the provider calling back. It is not a user endpoint: instead of a JWT it requires the shared secret in `X-Webhook-Secret`, compared in constant time. Missing or wrong secret → 401 `invalid_webhook_secret` and no state change.

```powershell
curl -X POST http://127.0.0.1:8000/payments/webhook `
  -H "Content-Type: application/json" -H "X-Webhook-Secret: <WEBHOOK_SECRET>" `
  -d "{\"event_id\":\"evt_12345\",\"booking_id\":\"<booking_id>\",\"status\":\"SUCCESS\",\"amount\":450.00}"
```

Fields: `event_id` (provider's unique event id), `booking_id`, `status` (`SUCCESS`/`FAILED`), `amount`, optional `payment_id` to correlate a payment created by `POST /payments`.

Response: `{"status":"processed"}` the first time, `{"status":"already_processed"}` for any replay.

Validation: the booking must exist (404), `amount` must equal `bookings.amount` (409 `amount_mismatch`), and a supplied `payment_id` must exist (404) and belong to that booking (400 `payment_booking_mismatch`). Webhooks against a terminal booking are rejected with 409 unless they merely attach their `event_id` to the matching existing payment.

## Idempotency strategy

`event_id` is stored in `payments.provider_event_id`, which has a database `UNIQUE` constraint. Processing order:

1. Look up the `event_id`; if present, return `already_processed` without touching anything.
2. Lock the booking row (`SELECT ... FOR UPDATE`).
3. Look up the `event_id` again under the lock, so a replay that raced step 1 is still caught.
4. Insert/link the payment and update the booking in one transaction.
5. If two requests still collide, `uq_payments_provider_event_id` (same event) or `uq_payments_booking_id` (second payment for the booking) raises; the loser rolls back and returns `already_processed`.

Result: repeated deliveries never create a second payment, never change the booking a second time, and never flip a terminal state.

## Concurrency protection

Enforced by PostgreSQL, not by application checks alone:

| Race | Protection |
|---|---|
| Two `POST /payments` for the same booking | booking row lock + `UNIQUE (payments.booking_id)` → one 201, one 409 |
| Two identical webhooks | row lock + re-check + `UNIQUE (provider_event_id)` → `processed` + `already_processed` |
| Webhook vs `POST /payments` | both take the same row lock; second sees terminal state |
| Cancel vs payment/webhook | cancel also takes the row lock, so it cannot overwrite a booking that was just confirmed |
| Two identical bookings | partial unique index `uq_bookings_active_slot` → one 201, one 409 `duplicate_booking` |

Every `IntegrityError` path rolls the session back before mapping the error to a response.

## Testing

The suite runs against a real PostgreSQL (`DATABASE_URL`) and refuses to start when `ENVIRONMENT=production`.

```powershell
docker compose up db -d
alembic upgrade head
pytest
```

- Most tests run inside a transaction that is rolled back after each test, so they leave no data behind.
- `tests/test_concurrency.py` uses real committed rows and separate connections (row locks are invisible inside a single transaction) and cleans up after itself.
- Coverage: auth (signup/login/me/token errors), catalogue and centre-specific pricing, bookings (ownership, validation, snapshot, duplicates, cancellation), simulated payments, webhook (secret, idempotency, correlation, amount check, terminal states), state machine, error envelope, schema constraints, and races (double payment, double booking, double webhook, cancel vs payment).

Other checks:

```powershell
alembic check
python -m compileall app tests
```

## Known limitations

- No roles: any authenticated user can create catalogue rows. Read endpoints are public by design.
- Webhook authentication is a shared header secret, not an HMAC signature over the body; there is no timestamp/replay window beyond `event_id` uniqueness.
- No pagination, rate limiting, structured logging, background jobs, Redis, or retry handling (all listed as optional in the assignment).
- No endpoint to update a centre's price; prices are created once per centre/test pair.
- A `FAILED` booking cannot be paid again; the patient creates a new booking.
- Compose uses fixed container names (`eve-postgres`, `eve-api`) and placeholder secrets by default; both are for local review only.
