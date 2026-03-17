# OpenClaw Builder Improvements — Full Proposal (Pre-Implementation)

This is the definitive, detailed proposal for the five builder improvements. It merges the implementation plan, the realism evaluation, and the **instruction-driven session** strategy (agent saves/uses session via instructions; we optionally inject prior context in follow-ups). Use this document as the spec for implementation.

---

## 1. Principles and constraints

- **No breaking changes:** Current `POST /task` with only `ocgg_identity`, `plan_hash`, `operations` continues to work. New fields are optional.
- **Hash unchanged:** `plan_hash` is computed only from `{ domain, operations }` (see gate/engine.py). Richer fields (goal, context, acceptance_criteria) are never part of the hash.
- **Graceful fallback:** When structured response is missing or invalid, we use the current heuristic and optionally set `needs_review` / `response_parse_failed`. Single-turn behavior remains when follow-up is not used.
- **Phased implementation:** Build in order (Phases 1–5) so each phase can be tested before the next.
- **Sourced vs designed:** Where behavior is from existing code or OpenClaw docs, the proposal follows it. Where it is our design (response schema, session format, endpoint names, audit event types), that is stated explicitly.

---

## 2. Improvement 1 — Richer plan (goal, context, acceptance criteria)

### 2.1 Goal

Give OpenClaw optional **goal**, **context**, and **acceptance_criteria** so the agent has clear intent and success criteria. The plan hash and gate logic stay the same.

### 2.2 Contract (exact)

**Request (POST /task):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| ocgg_identity | string | Yes | W-OCGG \| R-OCGG (unchanged) |
| plan_hash | string | Yes | Unchanged |
| operations | array | Yes | Unchanged |
| **goal** | string | No | e.g. "Create a simple homepage hero section for a dental clinic." |
| **context** | string | No | e.g. "React app, Tailwind, brand colors #0A2463." |
| **acceptance_criteria** | array of string | No | e.g. ["Hero has headline and CTA", "Mobile responsive"] |

- `plan_canonical` for hash remains exactly `{ "domain": domain, "operations": operations }`. Do **not** include goal, context, or acceptance_criteria in the hash.
- When building `plan_json` (success path and _result path), set:
  - `plan_json = { "domain", "plan_hash", "operations" }` as today,
  - then if `spec.get("goal")` is present and non-empty, set `plan_json["goal"] = spec["goal"]`,
  - same for `context` and `acceptance_criteria` (only if present).

**Execution:** No change to Gateway URL or auth. `input` is already `json.dumps(plan)`; the Gateway will receive the richer plan when those keys are in `plan_json`.

### 2.3 Files and changes

| File | Change |
|------|--------|
| `app/models/task.py` | On `TaskSubmitRequest`, add optional fields: `goal: str \| None = None`, `context: str \| None = None`, `acceptance_criteria: list[str] \| None = None`. Document in docstring or schema. Keep `extra="allow"`. |
| `app/gate/engine.py` | After building `plan_json = {"domain": domain, "plan_hash": plan_hash, "operations": operations}`, add: `if spec.get("goal"): plan_json["goal"] = spec["goal"]`, and similarly for `context` and `acceptance_criteria`. In `_result()`, when building `plan_json`, do the same from `spec` so BLOCK/REFORM paths also carry these for audit. |

### 2.4 Backward compatibility

- Clients that omit goal, context, acceptance_criteria: hash and behavior unchanged.
- dude-x: No change required for Phase 1; can add these fields later when the builder provides them.

---

## 3. Improvement 2 — Structured response schema + validation

### 3.1 Goal

Define a **contract** for the agent’s JSON response (status, message, optional artifacts/steps). Validate it in the integration; on parse/validation failure, fall back to the current heuristic and optionally mark `response_parse_failed` or `needs_review`.

### 3.2 Contract (exact)

**Our required response format (we enforce via instructions; Gateway does not guarantee it):**

```json
{
  "status": "success" | "failed" | "partial" | "needs_review",
  "message": "string",
  "artifacts": [
    { "path": "string", "type": "string", "summary": "string" }
  ],
  "steps_completed": [ "string" ],
  "session_summary": "string"
}
```

- `status`: required. We map to task status (success → completed, failed → failed, partial → partial, needs_review → needs_review).
- `message`: required string (can be empty).
- `artifacts`, `steps_completed`, `session_summary`: optional. `session_summary` is for instruction-driven session (see Improvement 4).

**Pydantic model (in execution_client or a shared models module):**

- `AgentResponseSchema` with fields: `status: Literal["success","failed","partial","needs_review"]`, `message: str`, `artifacts: list[ArtifactItem] | None = None`, `steps_completed: list[str] | None = None`, `session_summary: str | None = None`. `ArtifactItem`: `path: str`, `type: str`, `summary: str`. Use `model_config = ConfigDict(extra="allow")` so unknown keys don’t break validation.

**Instructions text (to send to OpenClaw):**

- Include in the system instruction something like: “You must respond with valid JSON only, in this exact shape: {\"status\": \"success\"|\"failed\"|\"partial\"|\"needs_review\", \"message\": \"...\", \"artifacts\": [{\"path\": \"...\", \"type\": \"...\", \"summary\": \"...\"}], \"steps_completed\": [\"...\"], \"session_summary\": \"...\"}. All keys except status and message are optional.”

**Parsing flow in _parse_gateway_response:**

1. Extract text from `output` using existing `_extract_text_from_output(output)`.
2. Try to find a JSON object in the text (e.g. strip markdown code fences if present, then `json.loads` on the first `{...}` or the whole string).
3. If parse succeeds, validate with `AgentResponseSchema`. If valid: use `parsed.status` for `status`, include `artifacts`, `steps_completed`, `session_summary` in the returned dict, and do **not** set `response_parse_failed`.
4. If parse or validation fails: keep current heuristic (infer status from text + item `status`), and set `response_parse_failed: true` in the returned dict. Optionally map to `status = "needs_review"` when `response_parse_failed` is true (configurable or default).

**Returned shape (execution_response):**

- Always: `execution_id`, `status`, `output`, `usage`, `id` (as today).
- When validation succeeds: add `artifacts`, `steps_completed`, `session_summary` from parsed object.
- When fallback: add `response_parse_failed: true`.

### 3.3 Files and changes

| File | Change |
|------|--------|
| `app/services/execution_client.py` | Add `ArtifactItem` and `AgentResponseSchema` (Pydantic). In `_plan_to_openresponses_body`, set instructions to the full format string above (including response shape). In `_parse_gateway_response`: implement parse → validate → use parsed status and optional fields; on failure use heuristic and set `response_parse_failed`. |

### 3.4 Backward compatibility

- Valid JSON with at least `status` and `message` (and optional extra keys) still works. Invalid or legacy responses get heuristic status and optional `response_parse_failed`; no exception.

---

## 4. Improvement 3 — Domain-specific instructions

### 4.1 Goal

Append domain-specific instruction snippets (web vs recruiting) so the agent behaves appropriately per product. Base “response format” instruction always comes first.

### 4.2 Contract (exact)

- **Domains (from identity.py):** `web` (W-OCGG), `recruiting` (R-OCGG).
- **Instruction build order:** `instructions = base_instruction + "\n\n" + (DOMAIN_INSTRUCTIONS.get(domain) or "")`.
- **Base instruction:** The full response-format instruction from Improvement 2 (including JSON shape).
- **Domain snippets (example text; tune as needed):**
  - `web`: “You are implementing front-end deliverables for the web. Prefer semantic HTML, accessibility, and clear structure. Output artifacts (path, type, summary) when you create or modify files.”
  - `recruiting`: “You are generating or editing job descriptions and screening criteria. Be consistent with company tone and compliance. Do not include discriminatory or non-compliant content.”
  - Unknown domain: no snippet (empty string).

Store snippets in a module-level dict in execution_client, e.g. `DOMAIN_INSTRUCTIONS: dict[str, str] = {"web": "...", "recruiting": "..."}`.

### 4.3 Files and changes

| File | Change |
|------|--------|
| `app/services/execution_client.py` | Define `DOMAIN_INSTRUCTIONS`. In `_plan_to_openresponses_body`, after building `base_instruction`, set `instructions = base_instruction + "\n\n" + (DOMAIN_INSTRUCTIONS.get(domain) or "")`. |

### 4.4 Backward compatibility

- Same request/response; only the prompt changes. Unknown domain gets no extra text.

---

## 5. Improvement 4 — Session continuity / multi-turn (with instruction-driven session)

### 5.1 Goal

Allow follow-up messages for the same task. Session continuity is achieved by:

1. **Gateway session (if supported):** Use `user = "project:{domain}:{task_id}"` so the same task maps to one logical session.
2. **Instruction-driven session:** Instruct the agent to save and use session data (e.g. return `session_summary` in the structured response). On follow-up, we **inject prior context** (e.g. last `session_summary` or last execution_response summary) into the request so the agent can continue even if the Gateway does not persist session state.

### 5.2 Contract (exact)

**User (session key):**

- First turn and follow-up: `user = f"project:{domain}:{task_id}"`. So we need `task_id` when calling the Gateway on the first turn (we have it after task create and flush).

**First turn (POST /task):**

- After creating the task and passing the gate, call the Gateway with:
  - `user = "project:{domain}:{task_id}"`,
  - `input` = full plan as JSON string (as today),
  - instructions as in Improvements 2 and 3, **plus** an optional line: “If this is a multi-step task, include a concise session_summary in your JSON so the next message can continue from it.”
- Store the full `execution_response` (including `session_summary` if present) in the task’s `audit_history` and in the response. No new DB columns required; we can derive “last context” from the latest execution_response in audit_history.

**Follow-up endpoint:**

- **Method and path:** `POST /task/{task_id}/continue`
- **Auth:** Same as other protected routes: `Authorization: Bearer <INTEGRATION_API_KEY>`.
- **Body:** `{ "message": string }` (required). Optional: `"prior_context": string` to override what we’d derive from the last execution (e.g. last `session_summary` or a short summary of last response).
- **Behavior:**
  - Load task by `task_id`. If not found → 404.
  - Check task is in a continuable status: one of `submitted`, `completed`, `partial`, `needs_review`. If status is `failed`, `error`, `auth_error`, `invalid_plan`, `domain_rejected` → 403 or 422 with a clear message.
  - Build prior context: if body has `prior_context`, use it; else from the last audit entry of type `execution_response`, take `payload.session_summary` or a short summary of `payload` (e.g. first 500 chars of message + “Artifacts: …” if present). If no prior context, use empty string.
  - Call the Gateway with:
    - Same `user` = `"project:{domain}:{task_id}"`,
    - `input` = a single string that includes prior context and the new message, e.g. “Prior context for this task:\n{prior_context}\n\nUser’s new message: {body.message}” (or use an array of message items if we prefer).
  - Instructions for continue: same base + domain instructions, plus: “The user has sent a follow-up. Use the prior context above and respond with the same JSON format (status, message, artifacts, steps_completed, session_summary).”
  - On success: append to task’s `audit_history` an entry `{ "event_type": "execution_response", "payload": result }`, update `task.execution_id` and `task.status` from the result, commit, return the same shape as POST /task execution (execution_id, status, execution_response).
- **Response:** Same as first-turn execution: e.g. `TaskContinueResponse` or reuse a shape with `task_id`, `execution_id`, `status`, `execution_response`.

**Instruction-driven session (explicit in instructions):**

- First turn: “When you finish, if the user might send a follow-up, set session_summary to a short summary of what was done and the current state (artifacts, next steps).”
- Continue: We send prior context in `input` and instruct the agent to use it. We do **not** rely solely on Gateway session persistence; we guarantee continuity by sending context ourselves.

### 5.3 Files and changes

| File | Change |
|------|--------|
| `app/services/execution_client.py` | Add `execute_follow_up(task_id: UUID, domain: str, message: str, prior_context: str = "")` (or equivalent). Build OpenResponses body: same `model`, `user = f"project:{domain}:{task_id}"`, `input` = combined prior context + message, instructions as above. Reuse same Gateway POST and response parsing. Optionally refactor so `execute(plan, token, task_id=None)` sets `user` to `project:{domain}:{task_id}` when task_id is provided. |
| `app/api/task.py` | (1) When calling the client on first turn, pass `task_id` (e.g. `client.execute(plan_json, execution_token, task_id=task.task_id)`). (2) Add route `POST /task/{task_id}/continue` with body model `TaskContinueRequest(message: str, prior_context: str | None = None)`. Load task, check status, build prior_context, call `execute_follow_up`, update task and audit, return response. |
| `app/models/task.py` (or api.py) | Add `TaskContinueRequest` and, if needed, `TaskContinueResponse` (or reuse existing response shape). |

### 5.4 Backward compatibility

- Single-turn flow unchanged except `user` becomes `project:{domain}:{task_id}` (per-task session). Clients that never call `/continue` see no API change. If the Gateway does not persist session, follow-up still works because we inject prior context.

---

## 6. Improvement 5 — Success / partial / needs_review + audit

### 6.1 Goal

Support task statuses **partial** and **needs_review**, and use audit for partial results and human-review actions.

### 6.2 Contract (exact)

**Task status:**

- Allowed values (after migration): `submitted`, `completed`, `failed`, `error`, `auth_error`, `invalid_plan`, `domain_rejected`, **partial**, **needs_review**.
- When we have a validated structured response (Improvement 2), map agent `status` to task status: success → completed, failed → failed, partial → partial, needs_review → needs_review.
- When we fall back (parse failed): optionally set task status to `needs_review` when `response_parse_failed` is true; otherwise keep current heuristic (completed/failed).

**DB migration:**

- File: `app/db/migrations/004_task_status_partial_needs_review.sql`.
- Content (PostgreSQL):  
  `ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'partial';`  
  `ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'needs_review';`  
- Note: If PostgreSQL version does not support `IF NOT EXISTS`, run once without it and document. Add to the same migration list in init_db/run_migrations so it runs after 003.

**Audit (POST /audit):**

- No schema change. Use existing `event_type` and `payload`.
- Document these **event types** for the builder:
  - `human_approved` — payload may include `{ "feedback": "...", "approved_artifacts": [...] }`.
  - `human_rejected` — payload may include `{ "reason": "...", "feedback": "..." }`.
  - `refine_requested` — payload may include `{ "message": "...", "partial_results": ... }`.
- Integration already appends to `audit_history` and stores in `audit_events`; no code change required for these event types beyond documentation.

**Response models:**

- `TaskSubmitResponse` and `TaskStatusResponse` already return `status: str`; they will return `partial` or `needs_review` when set. No change.

### 6.3 Files and changes

| File | Change |
|------|--------|
| `app/db/migrations/004_task_status_partial_needs_review.sql` | New file: two ALTER TYPE lines above. |
| `app/db/init_db.py` (or run_migrations) | Append `004_task_status_partial_needs_review.sql` to the migration list so it runs in order. |
| `app/models/task.py` | Add `partial` and `needs_review` to the `TaskStatus` enum (for docs and any validation). DB column is already enum; migration adds values. |
| `app/services/execution_client.py` | In `_parse_gateway_response`, when we have a validated structured response, map `parsed.status` to task status (completed/failed/partial/needs_review). Return that status in the dict. |
| `app/api/task.py` | When setting `task.status` from `result.get("status")`, no special case; allow any returned status (including partial, needs_review). |
| README or API docs | Document new statuses and optional audit event types (human_approved, human_rejected, refine_requested). |

### 6.4 Backward compatibility

- Existing tasks keep existing statuses. New statuses are additive. Clients can treat partial/needs_review as “needs attention” if they don’t yet handle them explicitly.

---

## 7. Implementation order (phases)

| Phase | Improvement | Delivers |
|-------|-------------|----------|
| **1** | Richer plan | Optional goal, context, acceptance_criteria in request and plan_json; gate and execution_client updated. |
| **2** | Structured response | AgentResponseSchema, instructions update, parse/validate + fallback, response_parse_failed. |
| **3** | Domain instructions | DOMAIN_INSTRUCTIONS and appending in _plan_to_openresponses_body. |
| **4** | Partial / needs_review + audit | Migration 004, TaskStatus enum, status mapping in _parse_gateway_response and task.py, docs. |
| **5** | Session + continue | user = project:{domain}:{task_id}, execute_follow_up, POST /task/{task_id}/continue, prior_context injection, session_summary in instructions. |

Implement in this order. After each phase, run existing tests and add/update tests for the new behavior.

---

## 8. Testing and rollback

**Tests to add or update:**

1. **Phase 1:** Task submit with and without goal/context/acceptance_criteria; assert plan_json contains them when sent and hash unchanged.
2. **Phase 2:** Parse valid JSON matching schema → correct status and optional fields; parse invalid JSON or wrong shape → heuristic used and response_parse_failed true.
3. **Phase 3:** Assert domain web/recruiting get correct snippet in instructions; unknown domain gets no snippet.
4. **Phase 4:** Agent returns status partial/needs_review → task.status set; migration runs; audit event types documented.
5. **Phase 5:** First turn receives task_id in user; POST /task/{task_id}/continue with message and optional prior_context returns execution_response and updates task/audit.

**Rollback (per phase):**

- Phase 1: Remove optional fields from request and gate; stop copying into plan_json.
- Phase 2: Revert to heuristic-only parsing; remove AgentResponseSchema and response_parse_failed.
- Phase 3: Remove DOMAIN_INSTRUCTIONS and append logic.
- Phase 4: Stop setting partial/needs_review in task; keep migration (enum values can stay).
- Phase 5: Remove continue endpoint; revert user to `project:{domain}` if desired; remove execute_follow_up and prior_context handling.

---

## 9. Summary of what is sourced vs designed

**Sourced (from code or OpenClaw docs):**

- plan_hash from `{ domain, operations }` only; plan_json shape; TaskSubmitRequest extra="allow"; identity map (web, recruiting); instructions merged into system prompt; user for session; task_id available before execute; audit event_type and payload; taskstatus ENUM; PostgreSQL ADD VALUE.

**Designed (our choices):**

- Field names goal, context, acceptance_criteria; structured response schema (status, message, artifacts, steps_completed, session_summary); domain snippet wording; user format `project:{domain}:{task_id}`; continue endpoint path and body; prior_context injection; audit event type names human_approved, human_rejected, refine_requested; status names partial, needs_review.

**Session strategy:**

- We do not rely only on Gateway session persistence. We instruct the agent to return session_summary and we inject prior context on follow-up so that session continuity is achieved via instructions and our own context passing.

---

## 10. Document history and references

- **Plan:** `docs/OPENCLAW_BUILDER_IMPROVEMENTS_PLAN.md`
- **Evaluation:** `docs/OPENCLAW_BUILDER_IMPROVEMENTS_EVALUATION.md`
- **This proposal:** `docs/OPENCLAW_BUILDER_IMPROVEMENTS_PROPOSAL.md` — use as the single spec for implementation.
