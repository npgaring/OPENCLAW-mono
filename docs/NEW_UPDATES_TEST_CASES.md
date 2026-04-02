# New Updates Test Cases (UI-Only Execution)

Use only browser UIs for all steps:
- Open index page: `https://openclaw-mono.vercel.app/`
- Open **OpenClaw Integration -> Swagger UI** (`/openclaw-integration/docs`)
- Click **Authorize** and enter `Bearer <INTEGRATION_API_KEY>`
- Use **Try it out** for each endpoint
- For DB validation, use Neon Console SQL Editor (web UI)

Precondition for adapter/openai test cases:
- `OPENAI_FLOW_ENABLED=true` in the target environment (so `/adapter/*` and `/openai/*` routes exist in Swagger)

Reusable setup data (UI-only):
- First run `POST /adapter/to-substrate` once (see Test Case 1 payload)
- Reuse returned values in later tests:
  - `governance_plan_hash` -> use as `plan_hash`
  - `operations`
  - `trace_id`

Test Case 1:

[INPUT]

intent: Create canonical governance payload from the Adapter UI flow.
Objective: Generate valid `plan_hash` + `operations` without terminal/hash tooling.
Context: In Swagger UI, call `POST /adapter/to-substrate` with this body:
`{
  "ocgg_identity": "W-OCGG",
  "intent": "web-build",
  "deployment_target": "preview",
  "objective": "Build and verify a web release candidate",
  "context": "Use the current web pipeline",
  "candidate_plan": {
    "steps": [
      {"id": "s1", "type": "write_config", "action": "write_config", "target": "web/app", "inputs": {"path": "app/config.json", "content": "{}"}},
      {"id": "s2", "type": "build", "action": "build", "target": "web/app", "inputs": {"depends_on": ["s1"]}}
    ],
    "metadata": {"requiresApproval": false, "riskLevel": "low"}
  }
}`
target_deployment: preview

[OUTPUT]

Expected outcome:

Invariant C = PASS
Invariant E = PASS
GRL = PASS

Additional explanation: Response should be `200` and include `governance_plan_hash`, `integration_plan_hash` (same value), `operations`, and `trace_id`. Use these values in the next test cases.

Test Case 2:

[INPUT]

intent: Validate frame preview PASS in UI.
Objective: Verify the new atomic evaluation-frame endpoint returns passable frame output.
Context: In Swagger UI, call `POST /evaluation-frame/evaluate` using `ocgg_identity`, `plan_hash` (from Test 1 `governance_plan_hash`), and `operations` (from Test 1).
target_deployment: preview

[OUTPUT]

Expected outcome:

Invariant C = PASS
Invariant E = PASS (EXECUTION_ALLOWED)
GRL = PASS

Additional explanation: Response should include `frame_status=PASS`, `governance_reached=false`, `dispatch_reached=false`.

Test Case 3:

[INPUT]

intent: Validate deterministic UATO stop path from UI.
Objective: Confirm validation control `PASS_C_FAIL_UATO_BLOCK` blocks before governance.
Context: In Swagger UI, call `POST /evaluation-frame/evaluate` and `POST /gate/evaluate` with the same valid payload plus:
`"validation": {"uato_scenario": "PASS_C_FAIL_UATO_BLOCK"}`
target_deployment: preview

[OUTPUT]

Expected outcome:

Invariant C = PASS
Invariant E = PASS (or not reached)
GRL = NOT_REACHED

Additional explanation: Expect frame `BLOCKED`, gate `uato_skipped_gate=true`, and `governance_reached=false`.

Test Case 4:

[INPUT]

intent: Validate dispatch-boundary denial from UI.
Objective: Confirm `PASS_GOV_FAIL_INVARIANT_E_CAPABILITY` produces an Invariant-E deny path.
Context: In Swagger UI, call `POST /evaluation-frame/evaluate`, `POST /gate/evaluate`, and `POST /task` with the valid payload plus:
`"validation": {"dispatch_boundary_scenario": "PASS_GOV_FAIL_INVARIANT_E_CAPABILITY"}`
target_deployment: preview

[OUTPUT]

Expected outcome:

Invariant C = PASS
Invariant E = BLOCK (EXECUTION_DENIED)
GRL = NOT_REACHED

Additional explanation: Expect `IE_DENIED_CAPABILITY_NOT_ALLOWED`, `dispatch_blocked=true`, and task `status=invariant_e_denied`.

Test Case 5:

[INPUT]

intent: Validate gate continuity token generation in UI.
Objective: Confirm `/gate/evaluate` emits `governance_evaluation_id` for continuity checks.
Context: In Swagger UI, call `POST /gate/evaluate` with valid `ocgg_identity`, `plan_hash`, and `operations` from Test 1.
target_deployment: staging

[OUTPUT]

Expected outcome:

Invariant C = PASS
Invariant E = PASS
GRL = PASS

Additional explanation: Response should include non-empty `governance_evaluation_id` and `evaluation_frame.governance_reached=true`.

Test Case 6:

[INPUT]

intent: Validate continuity success (gate -> task) with UI-only steps.
Objective: Confirm matching `governance_evaluation_id` is accepted by `/task`.
Context: In Swagger UI:
1. Call `POST /gate/evaluate` with `deployment_target=production`, valid hash/ops, no approval fields.
2. Copy returned `governance_evaluation_id`.
3. Call `POST /task` using the same payload + copied `governance_evaluation_id`.
target_deployment: staging

[OUTPUT]

Expected outcome:

Invariant C = PASS
Invariant E = PASS
GRL = BLOCK (PROD_DEPLOY_NO_APPROVAL)

Additional explanation: `/task` should return `approval_status=PENDING` and `governance_continuity_verified=true` without requiring terminal tooling.

Test Case 7:

[INPUT]

intent: Validate continuity mismatch guardrail from UI.
Objective: Confirm `/task` rejects mismatched `governance_evaluation_id`.
Context: In Swagger UI, call `POST /task` with valid hash/ops but set `governance_evaluation_id` to a fake value like `"bad-ref"`.
target_deployment: staging

[OUTPUT]

Expected outcome:

Invariant C = N/A (request rejected before continuity passes)
Invariant E = N/A
GRL = N/A

Additional explanation: Expect `422` with `detail.code=GOVERNANCE_CONTINUITY_MISMATCH`.

Test Case 8:

[INPUT]

intent: Validate adapter block for malformed temporal dependencies in UI.
Objective: Confirm Invariant-C temporal consistency failure is exposed in UI response.
Context: In Swagger UI, call `POST /adapter/to-substrate` with candidate plan where step `s1` depends on future step `s2`.
target_deployment: preview

[OUTPUT]

Expected outcome:

Invariant C = BLOCK
Invariant E = PASS (not primary blocker)
GRL = NOT_REACHED

Additional explanation: Expect `422` with `code=EVALUATION_FRAME_BLOCK`, `frame_status=BLOCKED`, and canonical `governance_plan_hash` in response detail.

Test Case 9:

[INPUT]

intent: Validate prod-approval requirement from adapter UI path.
Objective: Confirm production deployment without approval is blocked at frame/governance boundary.
Context: In Swagger UI, call `POST /adapter/to-substrate` with `deployment_target=production`, `requiresApproval=false`, and no `approval_reference`/`approver_id`.
target_deployment: production

[OUTPUT]

Expected outcome:

Invariant C = PASS
Invariant E = PASS
GRL = BLOCK (APPROVAL_REQUIRED)

Additional explanation: Expect `422`, `code=EVALUATION_FRAME_BLOCK`, `frame_status=APPROVAL_REQUIRED`, and reason code containing `PROD_DEPLOY_NO_APPROVAL`.

Test Case 10:

[INPUT]

intent: Validate adapter metadata approval guardrail in UI.
Objective: Confirm adapter metadata can require approval before full evaluation flow.
Context: In Swagger UI, call `POST /adapter/to-substrate` with candidate plan metadata `requiresApproval=true` and omit approval fields.
target_deployment: production

[OUTPUT]

Expected outcome:

Invariant C = NOT_REACHED
Invariant E = NOT_REACHED
GRL = NOT_REACHED

Additional explanation: Expect `422` with `code=METADATA_APPROVAL_REQUIRED`, plus `approval_request_id`, `approval_status=PENDING`, and `source_layer=ADAPTER`.

Test Case 11:

[INPUT]

intent: Validate malformed OpenAI-plan chain from UI only.
Objective: Confirm `/openai/plan-malformed` returns schema-valid output that later fails adapter frame checks.
Context: In Swagger UI:
1. Call `POST /openai/plan-malformed`.
2. Copy `candidate_plan` from the response.
3. Paste it into `POST /adapter/to-substrate` with valid identity/intent/deployment_target.
target_deployment: preview

[OUTPUT]

Expected outcome:

Invariant C = BLOCK (at adapter stage)
Invariant E = PASS (not primary blocker)
GRL = NOT_REACHED

Additional explanation: Step 1 returns `200` with trace/hash headers; Step 2 returns `422 EVALUATION_FRAME_BLOCK`.

Test Case 12:

[INPUT]

intent: Validate persistence/audit outputs through UI surfaces only.
Objective: Confirm new evaluation artifacts are visible via service UI and Neon web UI.
Context: In Swagger UI run one `POST /task` scenario and capture `task_id` + `trace_id`; then:
1. Call `GET /status/{task_id}` in Swagger.
2. Call `GET /audit/reconstruct?task_id=<task_id>` in Swagger.
3. In Neon SQL Editor (web UI), run checklist queries from `docs/NEON_DB_MANUAL_CHECKLIST.md` for `evaluation_records`, `tasks`, and `gate_decisions`.
target_deployment: staging

[OUTPUT]

Expected outcome:

Invariant C = PASS/BLOCK (depends on submitted scenario)
Invariant E = PASS/BLOCK (depends on submitted scenario)
GRL = PASS/BLOCK (depends on submitted scenario)

Additional explanation: UI responses should show replayable `trace_id` linkage and persisted decision context; Neon UI query results should confirm schema + rows exist for new evaluation/gate fields.
