# ADR 001: `POST /gate/evaluate` materializes prod-deploy governance approval

## Status

Accepted.

## Context

Operators run `POST /gate/evaluate` with production-style payloads before `POST /task`. When the gate returns **BLOCK** with **PROD_DEPLOY_NO_APPROVAL**, they need a durable **approval_request_id** tied to the same **trace_id** so `GET /approvals?trace_id=` works and approve/resume stays on one trace—without a “phantom” task submit whose only purpose was to create the row.

## Decision

When **UATO** returns **PASS** and **GateEngine** blocks with **PROD_DEPLOY_NO_APPROVAL**, `POST /gate/evaluate` calls the same materialization path as `POST /task`: **Task** + **gate_decisions** + **PENDING** **GOVERNANCE** **approval_requests**, with **trace_id** on the approval row matching the request.

Idempotency: **(trace_id, resume checkpoint snapshot hash)**. Repeating evaluate or calling `POST /task` with the same body + trace reuses the same approval (no duplicate rows).

## Consequences

- **Not** a pure read-only dry-run for that single outcome; clients that only want in-memory evaluation must avoid prod-no-approval scenarios or accept persistence.
- **Invariant-E / UATO** rules are unchanged; materialization runs only after UATO PASS and only for this governance stop.
- **Resume**: `POST /approvals/{id}/approve` then `POST /approvals/{id}/resume` unchanged; works for gate-created approvals.
- OpenAPI: **GateDecisionResponse** optional fields **task_id**, **approval_request_id**, **approval_status**, etc., populated for this case; app version bumped to reflect contract clarification (see `services/openclaw-integration/app/main.py`).

## Alternatives considered

- Return only **`approval_eligible: true`** and **`creates_approval_on: "POST /task"`** without persisting on evaluate—rejected as the preferred product path was first-class approval before task submit.
