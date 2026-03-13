# OpenClaw Integration

Governance-gated layer between callers (e.g. Builder System) and the runtime executor (OpenClaw). Evaluates specs, issues execution tokens, and forwards approved plans to the executor.

## Setup

1. Copy `example.env` to `.env` and set `DATABASE_URL` (shared Neon PostgreSQL), `OPENCLAW_BASE_URL`, `OPENCLAW_API_KEY`, `INTEGRATION_API_KEY`.
2. Run migrations (from repo root): `migration/001_dude_x_tables.sql`, `002`, `003_openclaw_integration_tables.sql`.
3. `pip install -r requirements.txt`

## Run

- Local: `uvicorn app.main:app --reload` (from `services/openclaw-integration` or with `PYTHONPATH=.`).
- All protected routes require `Authorization: Bearer <INTEGRATION_API_KEY>`.

## API

- `POST /task` — Submit task (ocgg_identity, plan_hash, operations); gate → persist → if PASS call executor.
- `POST /audit` — Callback: update task status and append audit event.
- `POST /gate/evaluate` — Evaluate spec only; return GateDecision (no DB, no execution).
- `POST /gate/verify-token` — Verify token in tenant context.
- `GET /status/{task_id}` — Task status, execution_id, audit_history.
- `GET /health` — Health check.
- `GET /`, `GET /privacy` — HTML.

## Tests

`pip install -r requirements-test.txt && PYTHONPATH=. python -m pytest tests/ -v -m "not live"`

## Executor contract

Executor must implement `POST {OPENCLAW_BASE_URL}/execute` with headers `Authorization: Bearer OPENCLAW_API_KEY` and `X-Execution-Token: <token>`. Body: plan JSON `{domain, plan_hash, operations}`. Response: `execution_id`, `status` ("success" or other).
