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

- `POST /compile` — compile spec to plan (requires `Authorization: Bearer <INTEGRATION_API_KEY>`). Optional **`trace_id`** (UUID) on the JSON body is accepted for correlation with OpenClaw integration (`POST /gate/evaluate`, `POST /task`); returned on the plan payload and stored on compile events when present. Use **`integration_hash_payload`** from `app/core/hashing.py` when computing `plan_hash` for the integration gate (see [Governance backend](../../docs/governance-backend.md)).
- `GET /plans/{plan_hash}` — fetch plan by hash.
- Governed v2 dual-engine endpoints (feature-flagged by `DUDEX_V2_ENABLED=true`):
  - `POST /v2/raw-intents` — cognitive mode (raw intent -> Build SoT).
  - `GET /v2/build-sot/{build_sot_hash}` — fetch Build SoT artifact.
  - `POST /v2/build-sot/{build_sot_hash}/revise` — deterministic SoT revision.
  - `POST /v2/build-sot/{build_sot_hash}/governance/evaluate` — Build SoT lock evaluation.
  - `POST /v2/build-sot/{build_sot_hash}/approval/decide` — explicit approval gate (required before compile).
  - `POST /v2/build-sot/{build_sot_hash}/compile` — compiler mode (locked SoT -> ExecutionPlan v2).
  - `GET /v2/execution-plans/{execution_plan_hash}` — fetch deterministic execution plan.
- `GET /health` — health check.
- `GET /`, `GET /privacy` — HTML pages.
- `GET /docs` — Swagger UI.

## Governed v2 Deploy Defaults

Set these env vars for GitHub + Vercel auto-provisioning metadata emitted by v2 compiler plans:

- `GOVERNED_V2_GITHUB_OWNER` — primary GitHub owner slug.
- `GOVERNED_V2_GITHUB_OWNER_TYPE` — `org` or `user` (default: `org`).
- `GOVERNED_V2_GITHUB_OWNER_FALLBACK` — optional fallback owner slug.
- `GOVERNED_V2_REPO_NAME_TEMPLATE` — default `cdmbr-{projectname}-{timestamp}`.
- `GOVERNED_V2_DEFAULT_BRANCH` — default `prod`.
- `GOVERNED_V2_VERCEL_TEAM_ID` — Vercel team id used for project provisioning.
- `GOVERNED_V2_DOMAIN_BEHAVIOR` — default `vercel_default_only`.
- `GOVERNED_V2_STACK_PRESET` — default `nextjs-typescript-react`.

## Tests

`pip install -r requirements-test.txt && PYTHONPATH=. python -m pytest tests/ -v`

Tests use in-memory SQLite (see `tests/conftest.py`).
