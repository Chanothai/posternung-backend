<div align="center">

# Poster Nung Backend

**REST API for a movie poster e-commerce platform — every poster is a one-of-a-kind item.**

[![CI](https://github.com/Chanothai/poster-nung-backend/actions/workflows/test.yml/badge.svg)](https://github.com/Chanothai/poster-nung-backend/actions/workflows/test.yml)
![Python](https://img.shields.io/badge/python-3.13-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)

</div>

---

## Overview

Poster Nung sells original, one-of-a-kind movie posters — every item has a stock of exactly one. That constraint drives the two hardest problems in this codebase:

- **Unique inventory under concurrency.** Two buyers reserving the same poster at once must never both succeed. Reservations use `SELECT ... FOR UPDATE` plus a partial unique index as a database-level safety net. See [`docs/database-design.md`](docs/database-design.md) for the full strategy.
- **PCI-DSS-aware payments.** The backend will only ever receive a payment token from the client — raw card data never touches this service. (Payment is not implemented yet; see status below.)

## Feature Status

| Layer | Feature | Status |
| --- | --- | --- |
| F0 | Core infrastructure (config, DB, security) | Done |
| F1 | Authentication (Firebase: email/password, phone-OTP, Google via `/auth/firebase`) | Done |
| F2 | Poster catalog & detail | Done |
| F3 | Cart & reservation (concurrency-critical) | Planned |
| F4 | Checkout & payment | Planned |
| F5 | Order history & profile | Planned |
| F6 | CI test pipeline | Done |

Full feature specs and acceptance criteria live in [`CLAUDE.md`](CLAUDE.md).

## Tech Stack

| Concern | Choice |
| --- | --- |
| Framework | FastAPI (async) |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 16 |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Auth | JWT (`python-jose`) + `passlib`/`bcrypt` |
| Firebase Auth | `firebase-admin` (ID token verification) |
| Rate limiting | slowapi |
| Testing | pytest + pytest-asyncio + httpx |
| Lint / format | ruff + black |

## Project Structure

```
app/
├── core/          # config, DB engine/session, security (JWT, hashing), rate limiter
├── models/        # SQLAlchemy ORM models
├── schemas/       # Pydantic request/response schemas
├── repositories/  # DB access — no business logic
├── services/      # business logic — one file per feature
├── api/v1/        # thin FastAPI routers, no DB queries
└── main.py        # app factory: middleware, exception handlers, routers

alembic/           # DB migrations
tests/             # pytest suite (own test DB, isolated from dev DB)
docs/              # DB design + OpenAPI contract
postman/           # ready-to-import Postman collection
```

Dependency direction is one-way: `api → services → repositories → models`.

## Getting Started

**Prerequisites:** Python 3.13, Docker Desktop.

```bash
git clone https://github.com/Chanothai/poster-nung-backend.git
cd poster-nung-backend

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env          # then fill in real values — see below

docker compose up -d db       # PostgreSQL on localhost:5432
alembic upgrade head          # create schema

uvicorn app.main:app --reload
```

The API is now at `http://localhost:8000`, with interactive docs at `/docs` (when `DOCS_ENABLED=true`).

## Environment Variables

Full reference: [`.env.example`](.env.example). Key variables:

| Variable | Default | Description |
| --- | --- | --- |
| `ENVIRONMENT` | — (required) | `sit`, `uat`, or `production` — app fails fast if missing |
| `DATABASE_URL` | — (required) | `postgresql+asyncpg://user:pass@host:port/db` |
| `JWT_SECRET` | — (required) | Generate with `openssl rand -hex 32`; never a real value in `.env.example` |
| `JWT_ACCESS_EXPIRE_MINUTES` | `30` | Access token TTL |
| `JWT_REFRESH_EXPIRE_DAYS` | `7` | Refresh token TTL |
| `OTP_RATE_LIMIT_PER_10MIN` | `5` | Max OTP requests per user per 10 minutes |
| `OTP_MAX_ATTEMPTS` | `5` | Max wrong OTP attempts before lockout |
| `DEBUG` | `false` | Enables SQL echo, etc. |
| `DOCS_ENABLED` | `true` | Toggles `/docs`, `/redoc`, `/openapi.json` |
| `CORS_ORIGINS` | — | Comma-separated allowed origins |
| `FIREBASE_PROJECT_ID` | — | Firebase project id (audience of the ID token) — empty means `/auth/firebase` returns 503 |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | — | Service account credential, full JSON on one line (dev/test) |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | — | Path to the credential file inside the container (prod, best practice — takes priority over the JSON var if both are set) |

In `production`, `DEBUG` and `DOCS_ENABLED` are enforced `false` by a config-level validator — the app refuses to boot otherwise.

## API Documentation

- Interactive Swagger UI: `GET /docs` (local/sit/uat only — disabled in production)
- OpenAPI spec: [`docs/openapi.yaml`](docs/openapi.yaml)
- Human-readable API contract (endpoints, error codes): [`docs/api-contract-f1-f3.md`](docs/api-contract-f1-f3.md)
- Postman collection: [`postman/`](postman/) — import both the collection and environment file

Auth is unified on Firebase — client apps sign in via the Firebase SDK (email/password, phone SMS-OTP, or Google) and send the resulting ID token to `POST /auth/firebase`. `POST /auth/google` still exists as a deprecated alias with identical behavior, kept only so older clients don't break.

## Testing

```bash
pytest              # runs against an isolated poster_nung_test DB, auto-created
ruff check .
black --check .
```

The test suite creates its own database and applies migrations independently — it never touches your dev database.

## Deployment

The app follows 12-factor config: one Docker image is built once per commit and promoted unchanged across `sit → uat → production`, with behavior differing only via environment variables (never `if env == "production"` in code). CI/CD is GitHub Actions; see [`.github/workflows/test.yml`](.github/workflows/test.yml) for the pipeline and [`.claude/rules/environments.md`](.claude/rules/environments.md) for the full deployment guide (Docker Compose per environment, secrets handling, promotion flow). For a copy-paste command reference (local dev, migrations, build, deploy, cleanup), see [`docs/docker-commands.md`](docs/docker-commands.md).

## Contributing

Commit messages follow Conventional Commits, scoped to the feature area:

```
feat(auth): add OTP verification endpoint
fix(docker): use !override so per-env env_file applies
```

See [`CLAUDE.md`](CLAUDE.md) for architecture rules, per-feature acceptance criteria, and the pre-merge checklist.
