# Realism evaluation: OpenClaw builder improvements plan

This document evaluates the implementation plan against **actually existing sources** (codebase and OpenClaw docs). It distinguishes what is **sourced** (verified from code or docs) from what is **designed** (our choices, not guaranteed by an external spec).

---

## Sources used

| Source | What was verified |
|--------|-------------------|
| **openclaw-integration** (gate/engine.py, models/task.py, api/task.py, execution_client.py, identity.py) | plan_hash formula, plan_json shape, request model, task flow, Gateway payload |
| **openclaw-integration** (db/migrations/003) | taskstatus ENUM, tasks table columns |
| **dude-x** (models/plan.py, compiler) | Plan has domain, operations, plan_hash, integration_plan_hash; no goal/context/acceptance_criteria today |
| **OpenClaw docs** (docs.openclaw.ai/gateway/openresponses-http-api) | input string or array; instructions merged into system prompt; user for session; message roles |
| **PostgreSQL** | ALTER TYPE ... ADD VALUE [ IF NOT EXISTS ] for enums (supported in current PG) |

---

## Improvement 1: Richer plan (goal, context, acceptance_criteria)

| Claim | Source / status |
|-------|-----------------|
| plan_hash is computed only from `{ domain, operations }` | **Sourced.** gate/engine.py line 52–53: `plan_canonical = {"domain": domain, "operations": operations}`; `computed_plan_hash = hash_payload(plan_canonical)`. No other keys. |
| plan_json today is `{ domain, plan_hash, operations }` | **Sourced.** gate/engine.py line 92: `plan_json = {"domain": domain, "plan_hash": plan_hash, "operations": operations}`. |
| Request can already carry extra fields | **Sourced.** TaskSubmitRequest has `model_config = ConfigDict(extra="allow")`, so goal/context/acceptance_criteria can be sent today; we just don’t use them. |
| Adding optional fields to plan_json without touching hash is backward compatible | **Correct.** Hash input is unchanged. plan_json is JSONB; adding keys is backward compatible. |
| dude-x has no goal/context/acceptance_criteria today | **Sourced.** Grep in dude-x: no such fields in plan or spec models. Plan says “dude-x optional later”—realistic. |

**Verdict:** **Realistic.** All behavior is grounded in current code. The only “design” is the field names (goal, context, acceptance_criteria) and that we copy them into plan_json when present.

---

## Improvement 2: Structured response schema + validation

| Claim | Source / status |
|-------|-----------------|
| We currently ask the model for “JSON with status, message” | **Sourced.** execution_client.py lines 40–42: instructions include “Return valid JSON only with keys: status (success or failed), message (optional).” |
| OpenClaw Gateway does not define a response schema | **Sourced.** The OpenResponses/OpenClaw doc describes request shape (input, instructions, user, model) and that we get output/usage/id; it does **not** specify the format of the text inside output. So any “expected” JSON shape is **our** contract in the instructions, not the Gateway’s. |
| We can parse and validate in our code | **Sourced.** We already extract text from output and infer status. Adding JSON parse + Pydantic validation is a normal code change. |
| Fallback when parse/validation fails | **Designed.** Plan proposes falling back to current heuristic and optionally setting a flag. No doc requires this; it’s a safe design choice. |
| Exact schema (artifacts, steps_completed) | **Designed.** The plan’s schema (e.g. artifacts with path/type/summary) is **not** from OpenClaw docs; it’s a proposed contract we would document in our instructions. The model may or may not comply; validation + fallback handles that. |

**Verdict:** **Realistic.** The implementation is feasible and based on existing behavior. The “structured response” is our chosen contract (enforced by our instructions and our validation), not something the Gateway guarantees. We must not assume the Gateway returns that shape; we only assume we can send instructions and parse the text we get.

---

## Improvement 3: Domain-specific instructions

| Claim | Source / status |
|-------|-----------------|
| We have exactly two domains: web, recruiting | **Sourced.** identity.py: `IDENTITY_DOMAIN_MAP = {"W-OCGG": "web", "R-OCGG": "recruiting"}`. |
| instructions are merged into the system prompt | **Sourced.** OpenClaw doc: “instructions: merged into the system prompt.” So appending more text to the instruction string is valid. |
| We can append a domain-specific snippet in code | **Sourced.** execution_client already builds one instruction string; appending is a trivial change. |
| Wording like “You are implementing front-end deliverables…” | **Designed.** Not from any doc. The plan should treat this as example text; real wording can be tuned later. |

**Verdict:** **Realistic.** Domain set and use of `instructions` are from the codebase and OpenClaw docs. Only the snippet content is our design.

---

## Improvement 4: Session continuity / multi-turn

| Claim | Source / status |
|-------|-----------------|
| Same `user` → stable session, repeated calls can share session | **Sourced.** OpenClaw doc (openresponses-http-api): “If the request includes an OpenResponses `user` string, the Gateway derives a stable session key from it, so repeated calls can share an agent session.” |
| We currently send `user = "project:{domain}"` | **Sourced.** execution_client.py line 46: `"user": f"project:{domain}"`. |
| We have task_id when we call the Gateway | **Sourced.** api/task.py: task is created and flushed (task_id set), then after token logic we call `client.execute(plan_json, execution_token)`. So task_id is available; we’d need to pass it into the client. |
| Using `user = "project:{domain}:{task_id}"` gives one session per task | **Designed.** The doc only says that a stable `user` gives a stable session; it does not define the format of `user`. Using a task-scoped value is a reasonable design so that follow-up requests for the same task reuse the same session. |
| New endpoint POST /task/{task_id}/continue with body `{ "message": str }` | **Designed.** Not from any doc. Endpoint name and body are our API design. |
| Sending a new request with same user and new input as “follow-up” | **Sourced.** OpenClaw doc: “The most recent user or function_call_output item becomes the ‘current message’”; “Earlier user/assistant messages are included as history.” So sending a new request with the same user and new input is the intended way to continue. |

**Caveat:** The doc does not guarantee that the Gateway actually persists session state across HTTP requests; it describes intended behavior (“repeated calls can share an agent session”). If the Gateway implementation is stateless or short-lived, multi-turn might not work. That’s a deployment/runtime assumption, not something we can prove from the doc.

**Verdict:** **Realistic** given the documented behavior. Session key and follow-up semantics are from the doc; task_id in user and the continue endpoint are our design. One unverifiable assumption: Gateway actually keeps session per user across requests.

---

## Improvement 5: Partial / needs_review + audit

| Claim | Source / status |
|-------|-----------------|
| status is stored in a PostgreSQL ENUM type | **Sourced.** 003_openclaw_integration_tables.sql: `CREATE TYPE taskstatus AS ENUM ('submitted', 'completed', 'failed', ...)` and `status taskstatus NOT NULL`. |
| We must add new values via ALTER TYPE | **Sourced.** PostgreSQL enums are extended with `ALTER TYPE ... ADD VALUE`. |
| ADD VALUE IF NOT EXISTS exists in PostgreSQL | **Sourced.** PostgreSQL docs (current) support `ALTER TYPE type_name ADD VALUE [ IF NOT EXISTS ] value`. |
| Audit accepts arbitrary event_type and payload | **Sourced.** api/audit.py: AuditRequest has event_type and uses to_payload(); audit_events has event_type and payload JSONB. So we can send new event types and shapes. |
| “partial” and “needs_review” as task statuses | **Designed.** Not in current enum; we add them. Naming is our choice. |
| human_approved, human_rejected, refine_requested as audit event types | **Designed.** Not from any existing spec; proposed for builder use. |

**Verdict:** **Realistic.** DB and audit behavior are from the codebase; new enum values and event type names are our design and consistent with existing patterns.

---

## What is not from an existing source (summary)

- **Structured response schema** (artifacts, steps_completed, etc.): Our chosen contract; not defined by OpenClaw. We enforce it via instructions and validation.
- **Domain instruction wording**: Example text; should be tuned, not taken as authoritative.
- **Session key format** `project:{domain}:{task_id}`: Our design to scope session to task.
- **Continue endpoint** path and body: Our API design.
- **Audit event type names** (human_approved, etc.): Our design for the builder.
- **Assumption that Gateway keeps session across requests**: Documented as intended behavior but not something we can verify from code.

---

## Risks and gaps

1. **Gateway session persistence:** If the Gateway does not actually retain session state for the same `user` across requests, multi-turn (Improvement 4) will not work as intended. Mitigation: test with the real Gateway or confirm with OpenClaw.
2. **Model compliance with JSON schema:** The model might not always return valid JSON or the exact keys we request. The plan’s fallback (heuristic + optional needs_review) is appropriate; we should not assume 100% compliance.
3. **PostgreSQL enum migration:** If the deployment uses an older PostgreSQL version, `IF NOT EXISTS` for ADD VALUE might not be available. The plan should note the minimum PG version or use a one-off migration without IF NOT EXISTS and document “run once.”

---

## Overall verdict

- **Improvements 1, 3, 5:** Strongly grounded in the current codebase and (where relevant) OpenClaw docs. No hallucination.
- **Improvement 2:** Feasible and aligned with existing code; the “schema” is our contract, not the Gateway’s—plan is realistic as long as we treat it that way.
- **Improvement 4:** Aligned with OpenClaw’s documented session semantics; endpoint and user format are our design. Only uncertainty is whether the Gateway actually persists sessions in practice.

The plan is **realistic and based on actually existing source** where applicable. Parts that are **designed** (schema, wording, endpoint names, event types) are clearly separable from what is **sourced** (hash formula, plan_json, identity map, doc quotes, DB schema). Nothing in the plan relies on capabilities the docs or code do not support.
