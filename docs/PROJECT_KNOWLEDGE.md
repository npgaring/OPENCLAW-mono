# OpenClaw Monorepo — Project Knowledge (for Custom GPT)

This document is derived strictly from files in this repo. It is meant to be attached as a knowledge file for a Custom GPT that analyzes this project.

## What This Repo Is

OpenClaw is a monorepo containing two FastAPI services that implement governance-gated planning and execution, plus supporting docs, migrations, and tests. The main services are:

- **DUDE-X**: compile-only deterministic planner.
- **OpenClaw Integration**: governance gate + execution gateway.

A third service directory `services/runtime-worker` exists but currently has no implementation files.

## Repo Layout (Top Level)

- `services/` — service code (dude-x, openclaw-integration, runtime-worker).
- `docs/` — governance, workflow, and demo documentation.
- `migration/` — SQL migrations for shared PostgreSQL schema.
- `scripts/` — CI helper scripts.
- `tests/` — placeholder unit/e2e/security/load tests at repo root.
- `requirements.txt` — merged Python dependencies for Vercel builds.
- `docker-compose.yml` — empty scaffold for future local service definitions.
- `index.html` — static index page to link to deployed service endpoints.

## Service: DUDE-X (Planner)

Source: `services/dude-x/`

### Purpose

Compile-only deterministic planner. Validates human-signed specs and compiles them into execution plans. It does not execute tasks and does not call AI/runtime.

### Run/Deploy

- Local: `uvicorn app.main:app --reload` from `services/dude-x` (or `PYTHONPATH=services/dude-x`).
- Vercel: `services/dude-x/vercel.json` routes to `app/main.py`.

### API Endpoints (FastAPI)

From `services/dude-x/README.md` and `services/dude-x/app/main.py`:

- `POST /compile` — compile spec to plan. Requires Bearer `INTEGRATION_API_KEY`.
- `GET /plans/{plan_hash}` — fetch plan by hash. Requires auth.
- `GET /health` — health check.
- `GET /` and `GET /privacy` — HTML pages.
- `GET /docs`, `GET /redoc`, `GET /openapi.json` — OpenAPI UI/schema.

### Auth

Protected routes use Bearer auth enforced by `app/core/auth.py`.

### Determinism, Invariants, and P-Stack

Code locations:

- Invariants: `services/dude-x/app/compiler/invariants.py`
- P-Stack: `services/dude-x/app/compiler/pstack.py`
- Hashing: `services/dude-x/app/core/hashing.py`

Invariants enforced post-compile:

- `SPEC_DETERMINISTIC` — spec can be deterministically hashed.
- `PLAN_HASH_STABLE` — recomputed plan hash equals plan hash.
- `IDENTITY_BOUND` — plan identity equals spec identity.
- `NO_IMPLICIT_DEFAULTS` — plan operations and rollback align with spec.
- `NO_EXECUTION_CAPABILITY` — op identity/type matches spec (prevents upgrades).

P-Stack validation layers (run on spec before compile):

- `P1_SCHEMA` — signature checks, non-empty operations, determinism checks.
- `P2_IDENTITY` — identity-intent allowlist.
- `P3_OPERATION_SCOPE` — decisions domain must match derived domain.
- `P4_RESOURCE_ENVELOPE` — max operations, rollback constraint non-empty.
- `P5_DETERMINISM_LOCK` — reassert determinism after prior checks.
- `P6_CONSTRAINT_CONSISTENCY` — `no_network` forbids deploy to http(s) URLs.

### Models and DB

- Models: `services/dude-x/app/models/` (Spec, Plan, CompileEvent, DB models).
- Migrations: `migration/001_dude_x_tables.sql`, `002_add_identity_columns.sql`.
- DUDE-X uses the shared PostgreSQL DB (Neon recommended in docs).

### Trace ID Support

- Optional `trace_id` in `POST /compile` body (stripped before SpecIn validation).
- Stored on compile events and returned in plan payload when provided.
- See `docs/governance-backend.md` for details and `005_trace_id.sql`.

### Tests

- `services/dude-x/tests/test_governance.py`
- `services/dude-x/tests/test_compile_adversarial.py`

## Service: OpenClaw Integration (Gate + Execution)

Source: `services/openclaw-integration/`

### Purpose

Governance gate between callers (e.g. Builder System) and runtime executor (OpenClaw Gateway). Evaluates specs, issues execution tokens, persists audit records, and forwards approved plans to the executor.

### Run/Deploy

- Local: `uvicorn app.main:app --reload` from `services/openclaw-integration` (or `PYTHONPATH=.`).
- Vercel: `services/openclaw-integration/vercel.json` routes to `app/main.py`.

### API Endpoints (FastAPI)

From `services/openclaw-integration/README.md` and `services/openclaw-integration/app/main.py`:

- `POST /task` — submit a task (gate → persist → execute if PASS).
- `POST /task/{task_id}/continue` — continue a task without full re-gate.
- `POST /test/execute` — non-governed proxy (off in production unless enabled).
- `POST /audit` — callback to append audit events.
- `GET /audit/reconstruct` — rebuild JSON snapshot for replay.
- `POST /gate/evaluate` — evaluate spec only (no DB, no execution).
- `POST /gate/verify-token` — verify token in tenant context.
- `GET /status/{task_id}` — status, execution_id, audit_history.
- `GET /health` — health check.
- `GET /` and `GET /privacy` — HTML pages.

### Auth

Protected routes require `Authorization: Bearer <INTEGRATION_API_KEY>`.

### Execution Target

- Integration calls OpenClaw Gateway OpenResponses API.
- Endpoint: `POST {OPENCLAW_BASE_URL}/v1/responses`.
- Auth: Bearer `OPENCLAW_API_KEY` (not the integration key).

### Gate Behavior and Policy

Primary reference: `docs/governance-backend.md`.

Key points:

- Gate recomputes plan hash from `{ domain, operations }` and compares to submitted `plan_hash`.
- Production deploy requires `approver_id` or `approval_reference` (presence checks only).
- Optional `trace_id` flows through gate/evaluate and task submission; persisted on `tasks` and `gate_decisions`.
- `POST /task/{id}/continue` does not re-run full gate; requires prior execution token hash.
- `POST /test/execute` is non-governed and disabled in prod unless `TEST_EXECUTE_ENABLED=true`.
- Execution-time policy version can be overridden by `POLICY_VERSION_EXECUTION_OVERRIDE`, which can force re-evaluation.

### Models and DB

- Models: `services/openclaw-integration/app/models/` (Task, GateDecision, AuditEvent, UsedToken, API models).
- Gate engine and policy: `services/openclaw-integration/app/gate/`.
- Token and ledger packages: `services/openclaw-integration/app/token/`, `services/openclaw-integration/app/ledger/`.
- Migrations: `migration/003_openclaw_integration_tables.sql`, `005_trace_id.sql`.

### Orphan Recovery

On startup, integration runs orphan recovery to mark tasks as error if tokens were consumed but no execution id was created. See `services/openclaw-integration/app/services/orphan_recovery.py` and startup logic in `app/main.py`.

### Tests

- `services/openclaw-integration/tests/test_gate_engine.py`
- `services/openclaw-integration/tests/test_gate_mutation_matrix.py`
- `services/openclaw-integration/tests/test_governance_validation.py`
- `services/openclaw-integration/tests/test_demo_governance_59s.py`
- `services/openclaw-integration/tests/test_stress_concurrency_crash.py`

## Service: Runtime Worker

Directory: `services/runtime-worker/`.

- Present but contains no implementation files in this repo snapshot.
- Mentioned in `README.md` and `docs/DEVELOPMENT_WORKFLOW.md` as security-sensitive.

## Shared Dependencies

Root `requirements.txt` is the merged dependency list for Vercel builds:

- `fastapi`, `uvicorn`, `sqlmodel`, `SQLAlchemy[asyncio]`, `asyncpg`, `aiosqlite`, `pydantic`, `pydantic-settings`, `httpx`.

## Database Migrations (Shared PostgreSQL)

Source: `migration/README.md`

- `001_dude_x_tables.sql` — creates `specs`, `plans`, `compile_events`.
- `002_add_identity_columns.sql` — adds `identity` columns to specs/plans (idempotent).
- `003_openclaw_integration_tables.sql` — creates `tasks`, `gate_decisions`, `audit_events`, `used_execution_tokens`.
- `005_trace_id.sql` — trace_id columns for task/gate correlation.

Both services run migrations on startup when `DATABASE_URL` points to PostgreSQL.

## Hashing and Normalization Rules

Primary reference: `docs/governance-backend.md`.

- DUDE-X `hash_payload` does recursive float→int normalization, then JSON dumps with sorted keys.
- DUDE-X `integration_hash_payload` uses sorted keys without float normalization; use for integration-facing plan hashes.
- Integration uses its own `hash_payload` with sorted keys and no float normalization.

## Trace and Audit

Primary reference: `docs/governance-backend.md`.

- `trace_id` is optional and propagated through compile, gate, and task flows.
- `GET /audit/reconstruct` returns task + latest gate decision for replay.
- Audit and gate decision records are persisted in the shared DB.

## CI/CD

From `.github/workflows/ci.yml` and `deploy.yml`:

- CI runs on PRs to `develop`/`main` and pushes to `develop`.
- Jobs: lint (ruff/mypy), unit tests (pytest with coverage), determinism assertion, security scans (Trivy + Bandit), integration tests via docker-compose.
- Deployment to Vercel on push to `main` when `ENABLE_DEPLOY=true` and Vercel secrets are configured.

## Scripts

- `scripts/assert_determinism.py` — placeholder script that currently prints a message and exits success. It does not yet call DUDE-X.

## Root Tests

- `tests/test_placeholder.py`
- `tests/e2e/test_placeholder_e2e.py`
- `tests/security/` and `tests/load/` exist but are currently empty in this snapshot.

## Docs Index

Notable documents under `docs/`:

- `governance-backend.md` — hashing, trace_id, bypass surfaces, replay.
- `GATE_MUTATION_MATRIX.md` — mutation matrix for gate decisions.
- `GOVERNANCE_VALIDATION_REPORT.md` — governance validation report (content defined in file).
- `DEV_BRIEF_59_SECOND_DEMO.md` — 59-second governance demo narrative.
- `CUSTOM_GPT_KNOWLEDGE.md` — existing knowledge file focused on Builder GPT workflows.
- `BACKEND_VERIFICATION_CHECKLIST.md` — checklist for backend guarantees.
- `DEVELOPMENT_WORKFLOW.md` — branching, commits, CI/CD policy.

## Static Index Page

`index.html` is a static page linking to DUDE-X and OpenClaw Integration endpoints. It includes default base URLs pointing at `https://openclaw-mono.vercel.app` with service prefixes.

## Known Gaps and Placeholders

- `docker-compose.yml` contains no service definitions yet.
- `scripts/assert_determinism.py` is a placeholder implementation.
- `services/runtime-worker` is present but not implemented in this repo snapshot.
- Root-level tests include placeholder files; real tests live under the services.

## Recommended Starting Points for Code Reading

- DUDE-X: `services/dude-x/app/main.py`, `services/dude-x/app/api/compile.py`, `services/dude-x/app/compiler/`.
- Integration: `services/openclaw-integration/app/main.py`, `services/openclaw-integration/app/api/task.py`, `services/openclaw-integration/app/gate/engine.py`.
- Governance details: `docs/governance-backend.md`, `docs/GATE_MUTATION_MATRIX.md`.
- Migrations: `migration/README.md` and SQL files.
