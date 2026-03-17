# DUDE-X

Compile-only deterministic planner: validates human-signed specs and expands them into execution plans. No execution, no AI, no inference.

## Setup

1. Copy `example.env` to `.env` and set `DATABASE_URL` (Neon PostgreSQL) and `INTEGRATION_API_KEY`.
2. Run migrations on the shared DB (from repo root): `psql $DATABASE_URL -f migration/001_dude_x_tables.sql` then `002_add_identity_columns.sql` if needed.
3. `pip install -r requirements.txt`

## Run

- Local: `uvicorn app.main:app --reload` (from `services/dude-x` or with `PYTHONPATH=services/dude-x`).
- Vercel: deploy with `vercel.json`; all routes go to `app/main.py`.

## API

- `POST /compile` — compile spec to plan (requires `Authorization: Bearer <INTEGRATION_API_KEY>`).
- `GET /plans/{plan_hash}` — fetch plan by hash.
- `GET /health` — health check.
- `GET /`, `GET /privacy` — HTML pages.
- `GET /docs` — Swagger UI.

## Tests

`pip install -r requirements-test.txt && PYTHONPATH=. python -m pytest tests/ -v`

Tests use in-memory SQLite (see `tests/conftest.py`).
