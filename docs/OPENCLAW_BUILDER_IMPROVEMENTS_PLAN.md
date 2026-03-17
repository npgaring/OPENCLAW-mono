# OpenClaw Builder Improvements — Implementation Plan (Top 5)

This plan implements five improvements in a **backward-compatible** way. Existing clients, gate logic, and task flow remain valid; new behavior is additive and opt-in where possible.

---

## Principles

- **No breaking changes**: Current `POST /task` request (ocgg_identity, plan_hash, operations only) continues to work. New fields are optional.
- **Hash unchanged**: `plan_hash` is still computed from `{ domain, operations }` only. Richer fields (goal, context, acceptance_criteria) are not part of the hash so existing dude-x / builders keep the same hashes.
- **Graceful fallback**: When new features are absent (e.g. no goal, no structured response), behavior matches today (single turn, status completed/failed only).
- **Phased rollout**: Implement in order so each phase can be tested before the next.

---

## Improvement 1: Richer plan (goal, context, acceptance criteria)

**Goal:** Send optional `goal`, `context`, and `acceptance_criteria` so OpenClaw has clear intent and success criteria.

**Contract:**

- **Request (POST /task):** Add optional fields to the body (existing `extra="allow"` already accepts them; we document and type them).
  - `goal`: `str | None` — e.g. "Create a simple homepage hero section for a dental clinic."
  - `context`: `str | None` — e.g. "React app, Tailwind, brand colors #0A2463."
  - `acceptance_criteria`: `list[str] | None` — e.g. ["Hero has headline and CTA", "Mobile responsive"].
- **Gate:** Do **not** include these in `plan_canonical` (hash stays `{ domain, operations }`). Copy them into `plan_json` only when present: `plan_json = { domain, plan_hash, operations, goal?, context?, acceptance_criteria? }`.
- **Execution client:** No change to URL or auth; `input` is already `json.dumps(plan)`, so the Gateway will receive the richer plan automatically.

**Files to touch:**

- `app/models/task.py`: Add optional `goal`, `context`, `acceptance_criteria` to `TaskSubmitRequest` (and optional in schema/docs). Keep `operations` and `plan_hash` required.
- `app/gate/engine.py`: When building `plan_json`, copy `goal`, `context`, `acceptance_criteria` from `spec` into `plan_json` if present. In `_result()`, do the same when building `plan_json` for BLOCK/REFORM paths so audit has them.
- **dude-x (optional, later):** Extend spec/plan to include goal, context, acceptance_criteria when the builder provides them; no change required for Phase 1.

**Backward compatibility:** Clients that do not send goal/context/acceptance_criteria get the same hash and same behavior as today.

---

## Improvement 2: Structured response schema + validation

**Goal:** Expect a strict JSON shape from the model (status, message, optional artifacts/steps), validate it, and fall back cleanly when invalid.

**Contract:**

- **Expected agent response (documented in instructions):**  
  `{ "status": "success" | "failed" | "partial" | "needs_review", "message": string, "artifacts": [{ "path": string, "type": string, "summary": string }]?, "steps_completed": string[]? }`
- **Integration:** After receiving Gateway response, extract text from `output` (existing `_extract_text_from_output`). Try to parse as JSON; if parsing succeeds, validate against a Pydantic model. If valid, use `status` (and optional artifacts/steps) from the parsed object. If parsing fails or validation fails, fall back to current heuristic (infer status from text + item.status) and optionally set a flag `response_parse_failed: true` in the stored result so the builder can show "needs review."

**Files to touch:**

- `app/services/execution_client.py`:
  - Add a Pydantic model `AgentResponseSchema` (status, message, artifacts optional, steps_completed optional).
  - In `_plan_to_openresponses_body`, update `instructions` to state this exact JSON shape (so the model knows what to return).
  - In `_parse_gateway_response`: (1) extract text; (2) try parse JSON and validate with `AgentResponseSchema`; (3) if valid, use parsed `status` (and map to our status); (4) if invalid, keep current heuristic and set `response_parse_failed: true` in the returned dict.
- **No change** to task API request/response; only the shape of `execution_response` may include new keys (`artifacts`, `steps_completed`, `response_parse_failed`).

**Backward compatibility:** Existing Gateway responses that are valid JSON with status/message still work; invalid or legacy responses still produce a status (via heuristic) and don’t break the task.

---

## Improvement 3: Domain-specific instructions

**Goal:** Append domain-specific instructions (web vs recruiting) so the agent behaves more appropriately per product.

**Contract:**

- **Execution client:** Keep a single **mandatory** “response format” instruction (from Improvement 2). Add a mapping `domain -> optional instruction snippet` (e.g. web: “You are implementing front-end deliverables. Prefer semantic HTML and accessibility.”; recruiting: “You are generating job descriptions or screening criteria. Be consistent and compliant.”). Build `instructions = base_format_instruction + "\n\n" + (domain_snippet or "")`.
- **Config:** Snippets can be hardcoded in code (or later in config/env). Unknown domain gets no snippet.

**Files to touch:**

- `app/services/execution_client.py`: In `_plan_to_openresponses_body`, after building the base instruction string, append domain-specific snippet from a dict keyed by `domain`. Base instruction must always come first.

**Backward compatibility:** Same request/response; only the prompt seen by the model changes. Unknown domains behave as today.

---

## Improvement 4: Session continuity / multi-turn

**Goal:** Allow follow-up messages for the same task so the user can refine or continue (e.g. “Add a footer”) in the same Gateway session.

**Contract:**

- **Session key:** Use `user` for Gateway = `project:{domain}:{task_id}` so each task has a stable session. (First request creates the session; follow-up reuses it.)
- **First turn (existing):** `POST /task` unchanged; when we call the Gateway we use `user = f"project:{domain}:{task_id}"` (we have task_id after we create the task). So we need to create the task first, then call the Gateway with that task_id in the user field. Currently we use `project:{domain}` so all tasks in the same domain share a session; changing to `project:{domain}:{task_id}` gives one session per task and enables follow-up.
- **Follow-up:** New endpoint `POST /task/{task_id}/continue` (or `POST /task/continue` with body `task_id` + `message`). Checks: task exists, task is in a continuable status (e.g. submitted, completed, partial, needs_review — not failed/auth_error/invalid_plan), optional: only allow if execution_token was used for first turn (no new token for continue). Then call Gateway with same `user` (project:{domain}:{task_id}), and `input` = the follow-up message (string or single user message item). Do not send the full plan again; send only the new message. Response: same as execution (execution_id, status, execution_response); append to task’s audit_history and update task status/execution_id if desired.
- **Task model:** No new columns required. Optionally store `last_execution_id` or rely on audit_history.

**Files to touch:**

- `app/services/execution_client.py`: Add an optional parameter to `execute()` or add a new method `execute_follow_up(task_id, domain, message)` that builds OpenResponses body with same `user` and `input` = message. Or add a helper that builds the request with `user` and `input`; first turn uses plan as input, follow-up uses message.
- `app/api/task.py`: (1) In `submit_task`, after creating the task, pass `task_id` into the client so we can set `user = f"project:{domain}:{task_id}"`. (2) Add new route `POST /task/{task_id}/continue` with body `{ "message": str }`. Load task, check status, call Gateway with same user and message, update task and audit, return execution_response.
- **Gate:** No change. Continue does not re-run the gate.

**Backward compatibility:** Existing single-turn flow still works. If clients never call `/continue`, behavior is as today. Changing `user` from `project:{domain}` to `project:{domain}:{task_id}` means each task gets its own session (better for multi-turn); old behavior (shared session per domain) is no longer used but no API contract breaks.

---

## Improvement 5: Success / partial / needs_review + audit

**Goal:** Support task statuses `partial` and `needs_review`, and allow audit to carry partial results and human-review actions.

**Contract:**

- **Task status:** Allow `partial` and `needs_review` in addition to existing statuses. When we parse the structured response (Improvement 2), if the agent returns `status: "partial"` or `status: "needs_review"`, set `task.status` to that. If parsing fails and we fall back to heuristic, we can set `needs_review` when `response_parse_failed: true` (optional).
- **DB:** PostgreSQL uses enum `taskstatus`. Add two values: `ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'partial';` and `ADD VALUE IF NOT EXISTS 'needs_review';` (or equivalent). Migration file: e.g. `004_task_status_partial_needs_review.sql`.
- **Audit:** Current `POST /audit` already accepts `task_id`, `status`, `event_type`, and arbitrary payload. Use it to: (1) Update task status to `partial` or `needs_review` when the integration sets it from the agent response; (2) Allow the builder to send audit events with `event_type` e.g. `human_approved`, `human_rejected`, `refine_requested` with payload `{ "partial_results": ..., "feedback": "..." }`. No schema change to audit_events; just document and use these event types.
- **Response model:** `TaskSubmitResponse` and `TaskStatusResponse` already return `status: str`; they will naturally return `partial` or `needs_review` when set.

**Files to touch:**

- New migration `app/db/migrations/004_task_status_partial_needs_review.sql`: Add `partial` and `needs_review` to `taskstatus` enum (PostgreSQL: `ALTER TYPE ... ADD VALUE`).
- `app/models/task.py`: Add `partial` and `needs_review` to `TaskStatus` enum (for docs and validation). Ensure task status column still accepts any string if we use varchar elsewhere; if DB is enum-only, migration covers it.
- `app/services/execution_client.py`: In `_parse_gateway_response`, when we have a validated structured response, map agent `status` to task status: success -> completed, failed -> failed, partial -> partial, needs_review -> needs_review.
- `app/api/task.py`: When setting `task.status` from `result.get("status")`, allow "partial" and "needs_review" (no special case; just set whatever we return).
- **Docs:** In README or API docs, document the new statuses and optional audit event types (human_approved, human_rejected, refine_requested).

**Backward compatibility:** Existing tasks remain submitted/completed/failed. New statuses are additive. Clients that don’t know about partial/needs_review can still treat them as “non-success” or show them in a generic “needs attention” bucket.

---

## Implementation order (phases)

| Phase | Improvement | Rationale |
|-------|-------------|-----------|
| **1** | Richer plan (goal, context, acceptance_criteria) | Purely additive request + gate; no Gateway contract change. Safe and quick. |
| **2** | Structured response schema + validation | Defines the response shape we’ll use for status mapping and for partial/needs_review. |
| **3** | Domain-specific instructions | Uses existing domain; small change in execution_client only. |
| **4** | Success / partial / needs_review + audit | Adds DB enum values and status handling; depends on structured response (Phase 2) for partial/needs_review from agent. |
| **5** | Session continuity / multi-turn | Depends on task_id being available when we call the Gateway (already is after task create); add continue endpoint and user format change. |

Implement in this order so that: (1) Richer plan is in place before we tighten response format; (2) Structured response and new statuses are in place before we rely on them in continue flows; (3) Multi-turn is last so session format and continue endpoint are clearly defined.

---

## Testing and rollback

- **Tests:** Add/update tests for: (1) Task submit with and without goal/context/acceptance_criteria; (2) Parsing valid and invalid structured response; (3) Domain-specific instructions for web/recruiting/unknown; (4) Task status partial and needs_review; (5) Continue endpoint (task exists, valid status, message sent to Gateway). Keep existing tests green.
- **Rollback:** Each phase can be reverted independently: remove optional fields from request/gate (Phase 1); revert parsing to heuristic-only (Phase 2); remove domain snippets (Phase 3); stop setting partial/needs_review and leave migration in place (Phase 4); remove continue endpoint and revert user to project:{domain} (Phase 5). DB enum values, once added, can remain (no need to remove).

---

## Summary

- **1. Richer plan:** Optional goal, context, acceptance_criteria in request and plan_json; hash unchanged.
- **2. Structured response:** Pydantic schema + validation; fallback to heuristic and optional response_parse_failed.
- **3. Domain instructions:** Append domain-specific snippet to instructions in execution_client.
- **4. Multi-turn:** user = project:{domain}:{task_id}; new POST /task/{task_id}/continue with message.
- **5. Partial/needs_review:** New enum values and status mapping from agent response; audit event types documented.

All changes stay aligned with the current project (openclaw-integration, dude-x, OpenClaw Gateway) and are designed not to break existing behavior or make the system worse.
