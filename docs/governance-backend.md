# Governance backend (DUDE-X + OpenClaw integration)

This document ties together **hashing**, **gate behavior**, **correlation IDs**, **bypass surfaces**, and **replay** for audits and demos.

## Correlation: `trace_id`

- **Optional on input**, UUID-shaped string (version 4 recommended). Invalid values are replaced server-side; omission causes generation.
- **DUDE-X `POST /compile`**: Accepts optional `trace_id` on the request body (stripped before `SpecIn` validation). Returned on the plan payload and stored on compile events metadata when applicable.
- **Integration `POST /gate/evaluate`**: Optional `trace_id`; echoed on the response when provided or normalized. When the outcome is **BLOCK** with **PROD_DEPLOY_NO_APPROVAL** (and UATO has **PASS**), the integration persists the same **task** + **approval_requests** (GOVERNANCE, PENDING) as **`POST /task`** for that checkpoint, so **`GET /approvals?trace_id=`** is populated without a prior **`POST /task`**. Idempotent on `(trace_id, resume snapshot)` with **`POST /task`**.
- **Integration `POST /task`**: Optional `trace_id`; persisted on `tasks` and `gate_decisions`, included in the signed execution token payload, returned as `trace_id` / `audit_trace_id` on `TaskSubmitResponse`.
- **Integration `POST /task/{id}/continue`**: If the task has `trace_id` set, the body **must** include the same `trace_id` (otherwise 422 / `TRACE_ID_MISMATCH`). The task must already have **`execution_token_hash`** from a successful gated `POST /task` (no hash → 422 `CONTINUE_REQUIRES_PRIOR_EXECUTION`).

**DB migration**: `005_trace_id.sql` (columns on `tasks`, `gate_decisions`).

## Bypass surfaces (P0 policy)

| Surface | Behavior |
|---------|----------|
| `POST /test/execute` | **Non-governed** proxy to OpenResponses. **Disabled in production** unless `TEST_EXECUTE_ENABLED=true`. In non-prod, allowed by default. |
| `POST /task/{id}/continue` | Does **not** re-run full gate; uses stored plan context. Guarded by `TASK_CONTINUE_ENABLED` (default on; set `false`/`0`/`no`/`off` to disable). Requires the task to have been created via a gated run that stored **`execution_token_hash`**. Not a substitute for a fresh gated submit. |

Prod gate rules (e.g. production deploy approval) are **not** relaxed on any path.

## Hashing and normalization

### DUDE-X (`services/dude-x/app/core/hashing.py`)

- **`canonical_json` / `hash_payload`**: Recursive **float→int** when the float equals an integer (e.g. `1.0` → `1`), then `json.dumps(..., sort_keys=True, ...)`.
- **`integration_hash_payload`**: Sorted dict keys, **no** float/int normalization — use this when computing a `plan_hash` that must match **openclaw-integration**’s `hash_payload`.

### Integration (`services/openclaw-integration/app/core/security.py`)

- **`hash_payload`**: Sorted dict keys recursively, `sort_keys=True` on `json.dumps` — **no** float/int normalization (same as DUDE-X `integration_hash_payload`).

**When hashes can diverge**: If DUDE-X uses `hash_payload` (with numeric normalization) for integration-facing hashes, results can differ from the integration gate for specs that contain non-integer floats that normalize. For **compile → gate** contracts, use **`integration_hash_payload`** on the DUDE-X side for the value sent as `plan_hash`.

**Full spec hash**: The gate computes `spec_hash` from the **entire** submitted spec dict (after any API processing). Clients should not assume `spec_hash` equals only `plan` fields.

## Staging vs production

- **`POLICY_VERSION_EXECUTION_OVERRIDE`**: If set, `get_policy_version_at_execution()` returns this value instead of `POLICY_VERSION`. After a successful gate, if this does not equal the decision’s `policy_version`, execution is **blocked** with `RE_EVALUATION_REQUIRED` (see `app/api/task.py`). Use deliberately in CI/staging to simulate drift; leave unset in prod unless you intend that behavior.
- **`APP_ENV`**: Drives default for `TEST_EXECUTE_ENABLED` (see `app/core/config.py`).

## Replay / audit (without browser storage)

- **`GET /audit/reconstruct?task_id=<uuid>`** and/or **`trace_id=<uuid>`** (Bearer auth): Returns a JSON snapshot of task row, latest gate decision row, and a short note that compile artifacts live in DUDE-X.
- **SQL**: Operators can also join `tasks` and `gate_decisions` on `task_id`, and correlate `trace_id` across both.

## Tests (evidence)

- **Compile adversarial**: `services/dude-x/tests/test_compile_adversarial.py` (key order, extra fields, float/int, `op_id` sensitivity).
- **Gate engine**: `services/openclaw-integration/tests/test_gate_engine.py`.
- **Task mutation matrix**: `services/openclaw-integration/tests/test_gate_mutation_matrix.py` → **`docs/GATE_MUTATION_MATRIX.md`**.

## OpenAPI

FastAPI exposes **`/openapi.json`**. New optional fields (`trace_id`, reconstruct query params) appear there automatically when models/routes are updated.

## Approval limitation (explicit)

`approver_id` / `approval_reference` are **presence checks** in policy; they are **not** verified against an external approval registry in this service.

---

## For **monoclaw-demo** (frontend): breaking vs non-breaking

### Non-breaking (additive)

- Optional **`trace_id`** on compile request, gate evaluate, task submit; responses echo/generate it.
- **`GET /audit/reconstruct`** (new).
- Task submit response fields **`trace_id`** / **`audit_trace_id`** (optional).

### Breaking / client action required

- **`POST /task/{task_id}/continue`**: If the task has a **`trace_id`**, the continue body **must** include the same **`trace_id`**. Omitting or mismatching → **422** with `TRACE_ID_MISMATCH`. (New tasks get a server-generated `trace_id` if the client omits it on submit.)
- Continue only works if the task has **`execution_token_hash`** from the initial gated execution path; otherwise **422** `CONTINUE_REQUIRES_PRIOR_EXECUTION`.
- **`POST /test/execute`**: **403** in production unless ops set `TEST_EXECUTE_ENABLED=true` (demo should not rely on this in prod).
