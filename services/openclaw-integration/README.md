# OpenClaw Integration

Governance-gated layer between callers (e.g. Builder System) and the runtime executor (OpenClaw). Evaluates specs, issues execution tokens, and forwards approved plans to the executor.

## Setup

1. Copy `example.env` to `.env` and set `DATABASE_URL` (shared Neon PostgreSQL), `OPENCLAW_BASE_URL`, `OPENCLAW_API_KEY`, `INTEGRATION_API_KEY`.
2. Run migrations (from repo root): `migration/001_dude_x_tables.sql`, `002`, `003_openclaw_integration_tables.sql`, and integration SQL through **`005_trace_id.sql`** (see `app/db/migrations/`).
3. `pip install -r requirements.txt`

## Run

- Local: `uvicorn app.main:app --reload` (from `services/openclaw-integration` or with `PYTHONPATH=.`).
- All protected routes require `Authorization: Bearer <INTEGRATION_API_KEY>`.

## API

- `POST /task` — Submit task (ocgg_identity, plan_hash, operations; optional goal, context, acceptance_criteria, **trace_id**); gate → persist → if PASS call executor. Response includes **`trace_id`** / **`audit_trace_id`** for correlation with DUDE-X compile.
- `POST /task/{task_id}/continue` — Follow-up for an existing task (`message`, optional `prior_context`, **`trace_id` when the task has one**). Task must be `completed`, `partial`, or `needs_review`, and must have `execution_token_hash` from the initial gated run. **Does not re-run the full gate** — see [Governance backend](../../docs/governance-backend.md).
- `POST /test/execute` — **Non-governed** OpenResponses proxy. **Off in production** unless `TEST_EXECUTE_ENABLED=true`. Prefer `POST /task` for demos.
- `POST /audit` — Callback: update task status and append audit event.
- `GET /audit/reconstruct` — `task_id` and/or `trace_id`: JSON snapshot for replay (task + latest gate row). See [Governance backend](../../docs/governance-backend.md).
- `POST /gate/evaluate` — Evaluate spec only; return GateDecision (no DB, no execution). Optional **trace_id** echoed in response.
- `POST /gate/verify-token` — Verify token in tenant context.
- `GET /status/{task_id}` — Task status, execution_id, audit_history.
- `GET /health` — Health check.
- `GET /`, `GET /privacy` — HTML.

**OpenAPI**: `GET /openapi.json` (includes new optional fields when the app is running).

## Tests

`pip install -r requirements-test.txt && PYTHONPATH=. python -m pytest tests/ -v -m "not live"`

## Executor (OpenClaw Gateway)

Execution is sent to the **OpenClaw Gateway** OpenResponses API. Set `OPENCLAW_BASE_URL` to your Gateway URL (e.g. `https://api.cdopenclaw.com`).

- **Endpoint**: `POST {OPENCLAW_BASE_URL}/v1/responses`
- **Auth**: Use **OPENCLAW_API_KEY** as Bearer when calling the Gateway (OpenClaw requires it). **INTEGRATION_API_KEY** is only for authorizing callers to our API (/task, /audit, etc.), not for the Gateway.
- The integration maps each plan to an OpenResponses request and maps the Gateway response to `execution_id` and task `status`. Task statuses: `submitted`, `completed`, `failed`, `partial`, `needs_review`, plus error types (`error`, `auth_error`, etc.). Ensure the Gateway has `gateway.http.endpoints.responses.enabled: true`. See [OpenResponses HTTP API](https://docs.openclaw.ai/gateway/openresponses-http-api).
