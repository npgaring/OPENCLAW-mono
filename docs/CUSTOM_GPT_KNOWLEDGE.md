# OpenClaw Builder — Knowledge (attach this file to the Custom GPT)

Use this document for exact API flow, request/response shapes, and rules. The GPT Instructions should tell the assistant to follow this knowledge.

---

## Architecture

- **dude-x**: Compile-only deterministic planner. Validates human-signed specs and compiles them into execution plans. **POST /compile** with full spec → returns plan (`identity`, `ocgg_identity`, `domain`, `operations`, `plan_hash`, `integration_plan_hash`). Auth: **X-API-Key**.
- **OpenClaw Integration**: Gate + executor gateway. **POST /gate/evaluate** → get integration’s plan_hash and gate decision. **POST /task** → submit. Auth: **Authorization: Bearer \<INTEGRATION_API_KEY\>**. Integration plan_hash is computed from `{ domain, operations }` only (not dude-x’s plan_hash).
- **Flow**: Build dude-x spec → dude-x **POST /compile** → use returned `ocgg_identity` + `operations` → Integration **POST /gate/evaluate** (plan_hash `""` or `integration_plan_hash`) → Integration **POST /task** with the integration plan_hash.

---

## Dude-x spec (POST /compile)

Required shape (or send inside `params` for GPT Action compatibility):

- `spec_version`: `"1.0"`
- `identity`: `"W-OCGG"` or `"R-OCGG"`
- `intent`: `"web-build"` | `"web-maintenance"` | `"recruiting-update"` (W-OCGG → web-build or web-maintenance; R-OCGG → recruiting-update)
- `target`: `{ "resource_id": string, "environment": "preview" | "production" }`
- `decisions`: `{ "domain": "web" | "recruiting" | null, "operations": [ { "op_id", "type", "target", "inputs", optional "outputs", "addon" } ] }`
- `constraints`: object (e.g. `{}`). If `"rollback"` key present, value must be non-empty.
- `signature`: `{ "type": "human_signed", "signed_at": "<ISO8601>", "hash": "<non-empty>" }` (synthetic OK: e.g. hash = "sig_builder_" + timestamp).

**Response (PlanPayload)**: `plan_version`, `identity`, `ocgg_identity`, `domain`, `deployment_target`, `operations`, `rollback`, `plan_hash`, `integration_plan_hash`. Use **ocgg_identity**, **operations**, and **deployment_target** for Integration; use **integration_plan_hash** (or the hash returned by `/gate/evaluate`). Do **not** use dude-x’s `plan_hash` as the integration’s plan_hash.

**Errors**: IDENTITY_INTENT_MISMATCH → fix intent for identity; DOMAIN_MISMATCH → set decisions.domain; MISSING_DECISION → non-empty operations; fix and retry.

---

## API flow (strict)

1. Build dude-x spec (target, decisions.operations, constraints, signature).
2. **dude-x POST /compile** (header X-API-Key). On success → identity, ocgg_identity, domain, operations, integration_plan_hash.
3. **Integration POST /gate/evaluate**: `ocgg_identity` = plan.ocgg_identity, `integration_plan_hash: ""` (or use `integration_plan_hash`), `operations` = plan.operations; optional `goal`, `context`, `acceptance_criteria`. Use response `plan_hash` for step 4 (should match `integration_plan_hash`).
4. **Integration POST /task**: same + `integration_plan_hash` from step 3 (or compile response). Response: task_id, status, execution_id, execution_response, gate_outcome, reason_codes.
5. **Follow-up**: **POST /task/{task_id}/continue** with `{ "message": "..." }`. Task must be completed, partial, or needs_review.
6. **Status**: **GET /status/{task_id}**.

---

## Operation types

- **W-OCGG**: create_file, write_config, build, deploy, test, rollback_prep.
- **R-OCGG**: create_file, write_config.

Examples (for decisions.operations): write_config with path/content; build with command; deploy with provider, project. Recruiting: create_file/write_config for job descriptions; keep compliant.

---

## Response interpretation

- **completed**: success; summarize artifacts and steps.
- **failed**: show message; suggest fixes or new plan.
- **partial** / **needs_review**: show what’s done; offer continue or follow-up.
- **gate_outcome BLOCK**: do not submit; explain reason_codes and defect_list; fix spec or operations.

---

## Approval, BLOCK/REFORM, and Recompile

- **Who decides BLOCK/REFORM:** OpenClaw Integration (gate) returns `gate_outcome: "BLOCK"` plus `reason_codes` explaining what failed.
- **How a blocked execution gets approved:** Add `approval_reference` or `approver_id` and **re-submit** the same plan (`ocgg_identity`, `operations`, `integration_plan_hash`). The gate re-evaluates and can return **PASS**.
- **When a recompile is required:** If the reason codes indicate a plan change (e.g., invalid operation types, unauthorized network egress, domain mismatch), the user must **update the spec** and call **dude-x `/compile` again**.
- **Does dude-x auto‑recompile?** No. Dude-x compiles only when a new spec is submitted. Integration never compiles; it only evaluates and executes.

---

## Rules

- dude-x: X-API-Key. Integration: Bearer INTEGRATION_API_KEY. Never expose OpenClaw Gateway key.
- Only allowed operation types per identity. Integration plan_hash comes from the integration canonical hash (`{ domain, operations }`), available via `/gate/evaluate` or as `integration_plan_hash` from dude-x.
- Production deploy may require approver_id or approval_reference; on PROD_DEPLOY_NO_APPROVAL or SOD_VIOLATION, explain and ask user.
- After API calls, briefly summarize what you did and the outcome (e.g. "Compiled with dude-x; submitted; task_id …" and status, message, artifacts).
- If dude-x or Integration base URL/API key is missing, ask user to set them in GPT configuration.

---

## 59-second governance demo (verification & narrative)

**What it is:** A short story the integration enforces: production deploy without approval is **BLOCK**; the same plan with **approval_reference** (or **approver_id**) can **PASS** and execute. The Custom GPT should mirror that story when explaining governance to users (e.g. “without approval the gate blocks; add an approval reference and resubmit”).

**User-facing flow (matches API, compiler first):**

0. **dude-x (compiler):** User submits a **human-signed spec** via **POST /compile** → dude-x validates and returns a **plan** (`identity`, `ocgg_identity`, `domain`, `operations`, `plan_hash`, `integration_plan_hash`). That plan is the *compiled* intent; the integration gate does not use dude-x’s `plan_hash` for submission—it uses the integration hash (`integration_plan_hash` or from `/gate/evaluate`).
1. User sends **POST /gate/evaluate** (optional dry run) and/or **POST /task** with `ocgg_identity` = plan’s `identity`, `operations` = plan’s `operations`, `deployment_target: "production"`, and **no** `approval_reference` / `approver_id` → integration returns **BLOCK** / **gate_outcome: BLOCK**, **reason_codes** including `PROD_DEPLOY_NO_APPROVAL`; no execution.
2. User adds **approval_reference** (or valid **approver_id**) and resubmits **POST /task** → **gate_outcome: PASS**, **task_id**, **execution_id** / **execution_response** when execution succeeds.
3. **Receipt:** **GET /status/{task_id}** shows **audit_history** with events like `gate_decision` and `execution_response`.

**Optional dry run:** **POST /gate/evaluate** with `plan_hash: ""` (or `integration_plan_hash`) and the compiled `operations` returns **outcome**, **reason_codes**, **defect_list** — useful before **POST /task**. For **PROD_DEPLOY_NO_APPROVAL** (after UATO PASS), the integration also persists a **PENDING** **GOVERNANCE** **approval_requests** row (same **trace_id**) and returns **approval_request_id**; operators can use **GET /approvals?trace_id=** without submitting **POST /task** first solely to create that row.

**Developer verification (automated tests):** In the repo, `services/openclaw-integration/tests/test_demo_governance_59s.py` prints each scenario in narrative form when run with **`pytest … -s`**:

- **User sending this request:** method, path, and JSON body.
- **The system returns:** status and response JSON.
- **Verification receipts:** database rows for **tasks**, **gate_decisions**, **used_execution_tokens** (what was persisted for audit and replay protection).

Run (from `services/openclaw-integration`):

```bash
PYTHONPATH=. python3 -m pytest tests/test_demo_governance_59s.py -v -s
```

Full technical mapping: **`docs/DEV_BRIEF_59_SECOND_DEMO.md`**.

**If a user asks how we know the demo works:** Point them to that test file and brief, or summarize: production without approval → BLOCK; with approval → PASS + execution; status endpoint shows the receipt trail.

---

## Sample demo scenes (for simulation)

Use these exact payloads and expected responses when the user asks to **simulate** the 59-second demo or a specific scene (e.g. “simulate scene 1”, “show me the block then pass flow”). **Always start with dude-x compile** so the story is: *spec → compiler plan → gate → task*. You can either call the real APIs if configured, or **narrate** each step.

**Auth:** dude-x **POST /compile** → header **X-API-Key**. Integration → **Authorization: Bearer \<INTEGRATION_API_KEY\>**.

---

### Scene 0: dude-x — compile spec → plan (compiler)

**User sends:** **POST /compile** (dude-x base URL):

```json
{
  "spec_version": "1.0",
  "identity": "W-OCGG",
  "intent": "web-build",
  "target": {
    "resource_id": "site:marketing",
    "environment": "production"
  },
  "decisions": {
    "domain": "web",
    "operations": [
      {
        "op_id": "op-001",
        "type": "deploy",
        "target": "web/app",
        "inputs": { "provider": "vercel", "project": "marketing-site" },
        "outputs": {}
      }
    ]
  },
  "constraints": {},
  "signature": {
    "type": "human_signed",
    "signed_at": "2026-03-17T12:00:00Z",
    "hash": "sig_demo_59s_governance"
  }
}
```

**dude-x returns (200):** `plan_version`, `identity` (`W-OCGG`), `ocgg_identity` (`W-OCGG`), `domain` (`web`), `operations` (same deploy op, normalized), `rollback`, **`plan_hash`** (dude-x’s plan fingerprint), **`integration_plan_hash`** (integration-compatible hash).

**For integration:** Use **`ocgg_identity`** and **`operations`** from this response for **POST /gate/evaluate** and **POST /task**. Use **`integration_plan_hash`** (or the hash returned by `/gate/evaluate`). Do **not** paste dude-x’s `plan_hash` into the integration as the integration’s `plan_hash`.

---

### Shared integration building blocks

- **Operations for gate/task:** Use the **`operations`** array returned by **POST /compile** (must match what you send to the gate; include **`outputs: {}`** on ops if present in the compiled plan).
- **Integration `plan_hash`:** For **POST /gate/evaluate** send `"integration_plan_hash": ""` (or a real value from compile). The response includes the integration’s **`plan_hash`**. For **POST /task**, use **`integration_plan_hash`** (or the response `plan_hash`) from the prior **POST /gate/evaluate** (same `ocgg_identity`, `operations`, `deployment_target`).

---

### Scene 1–2: After compile — request without approval → BLOCK

**User sends:** **POST /task** (integration):

```json
{
  "ocgg_identity": "W-OCGG",
  "integration_plan_hash": "<from dude-x compile or from POST /gate/evaluate>",
  "operations": [
    {
      "op_id": "op-001",
      "type": "deploy",
      "target": "web/app",
      "inputs": { "provider": "vercel", "project": "marketing-site" },
      "outputs": {}
    }
  ],
  "deployment_target": "production"
}
```

(Use the exact `operations` from dude-x’s compile response if they differ slightly; always keep them in sync with the evaluate step. No `approval_reference` or `approver_id`.)

**Integration returns (200):**

- `gate_outcome`: `"BLOCK"`
- `reason_codes`: includes `"PROD_DEPLOY_NO_APPROVAL"`
- `execution_id`: `null` (or absent)
- No execution is run.

---

### Scene 3–4: Same plan with approval → PASS and execution

**User sends (POST /task):** Same as Scene 1–2, plus:

```json
"approval_reference": "demo-approval-ref-001"
```

**Integration returns (200):**

- `gate_outcome`: `"PASS"`
- `task_id`: non-null UUID string
- `execution_id` or `execution_response`: present (execution authorised and run)

---

### Gate evaluate (dry run, after compile)

**User sends:** **POST /gate/evaluate** — same shape as task, with `"integration_plan_hash": ""` (or a real value) and **`operations`** copied from dude-x compile response:

```json
{
  "ocgg_identity": "W-OCGG",
  "integration_plan_hash": "",
  "operations": [
    {
      "op_id": "op-001",
      "type": "deploy",
      "target": "web/app",
      "inputs": { "provider": "vercel", "project": "marketing-site" },
      "outputs": {}
    }
  ],
  "deployment_target": "production"
}
```

**Integration returns (200):**

- `outcome`: `"BLOCK"`
- `reason_codes`: includes `"PROD_DEPLOY_NO_APPROVAL"`
- `defect_list`: at least one defect whose `message` mentions “approval”.

Use the response’s **`plan_hash`** (or the compile response’s `integration_plan_hash`) for **POST /task** when the user adds approval and submits.

---

### Receipt (after a PASS)

**User sends:** `GET /status/{task_id}` (use the `task_id` from the PASS response).

**Integration returns (200):**

- `execution_id` or `status` (e.g. `completed`, `failed`, `partial`, `needs_review`)
- `audit_history`: list of events; must include `event_type`: `"gate_decision"` and `"execution_response"` (or equivalent).

---

**Simulation instructions for the Custom GPT:** When the user asks to simulate the demo (or “run the 59s demo”, etc.), walk through in order:

1. **dude-x POST /compile** — show the signed spec and the returned **plan** (`identity`, `operations`); explain that dude-x is compile-only (no execution).
2. **POST /gate/evaluate** (optional) — same `operations` as compile, `integration_plan_hash: ""` (or a real value) → BLOCK + defect message + integration **`plan_hash`**.
3. **POST /task** without approval → **BLOCK** (same narrative as tests).
4. **POST /task** with **`approval_reference`** → **PASS** + execution.
5. **GET /status/{task_id}** — receipt / audit trail.

If APIs are not configured, narrate each step with the payloads and outcomes above. If only integration is available, say: “In production you would compile first with dude-x; here are the `operations` that came from compile…” and continue from step 2.
