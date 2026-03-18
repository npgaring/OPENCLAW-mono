# DEV BRIEF — 59-Second OpenClaw Governance Demo

## Goal

Build one short **real screen-recorded demo** that makes it obvious to any viewer that **OpenClaw is governed, not just automated**.

- **Not** a concept video, product promo, or happy-path-only clip.
- **Proof demo**: in under 59 seconds the viewer must understand:
  - The system **does not just execute** — it **checks the request first**.
  - It **refuses or pauses when needed**.
  - It **only executes after approval**.
  - Execution is **bounded and auditable**.

**Success condition:** After watching, a normal person can say: *“It won’t do anything unless it passes governance first.”*  
If they say *“It automates tasks”* with no notion of refusal/approval, the demo failed.

---

## Non-negotiable rule: show refusal first

The demo must **not** show only: request → pass → execute.

It must show:

1. Request submitted  
2. System returns **CLARIFY**, **REFORM**, or **BLOCK**  
3. User corrects or approves  
4. System returns **PASS**  
5. Token/authority issued  
6. OpenClaw executes  
7. Receipt/audit shown  

That contrast is what makes governance understandable.

---

## Exact demo flow to build

| Scene | What happens | What must be visible |
|-------|----------------|-----------------------|
| **1** | User submits a request that should **not** pass first time (e.g. production action without approval or with policy issue). | Request input (e.g. “deploy to production”). |
| **2** | System returns **CLARIFY**, **REFORM**, or **BLOCK**. | Decision + one or two reason lines (e.g. “Production deployment requires approval”, “Missing required approval reference”). |
| **3** | User adds missing approval or corrects the request. | Approval step / corrected request. |
| **4** | System returns **PASS**. | “Approved”, “token issued”, “execution authorised”. |
| **5** | OpenClaw runs the task. | Execution panel: queued → running → completed. |
| **6** | Receipt / audit. | Final status, execution reference, token/reference, audit/trace. |

**Suggested timeline (59s):**  
0–10s Request entered → 10–20s System returns BLOCK/REFORM/CLARIFY → 20–30s User corrects or approves → 30–40s PASS + authority issued → 40–50s OpenClaw executes → 50–59s Receipt/audit shown.

---

## UI requirements (plain and real)

- **A. Request panel** — Where the instruction is entered.  
- **B. Governance panel** — Decision (PASS/REFORM/CLARIFY/BLOCK), reason, approval requirement if relevant.  
- **C. Approval panel** — Approved / not approved, authority granted.  
- **D. Execution panel** — Queued → running → completed.  
- **E. Receipt panel** — Execution reference, token/reference, final status, audit/trace.

Words that must appear (or close equivalents): **CLARIFY**, **REFORM**, **BLOCK**, **PASS**, **approval required**, **execution authorised**, **execution running**, **receipt** or **audit**.

---

## Technical implementation (this repo)

The demo flow is **implemented and testable** in the OpenClaw integration. The following maps the brief to real APIs and tests.

### How we get “refusal first”

- **Production deploy without approval** → gate returns **BLOCK** with reason **PROD_DEPLOY_NO_APPROVAL** and a defect message like *“Production deploy requires approver_id or approval_reference”*.
- Same request **with** `approval_reference` (or `approver_id` from a different identity) → gate returns **PASS** → token issued → execution allowed.

### API flow used in the demo

1. **Request (Scene 1)**  
   - **POST /task** (or **POST /gate/evaluate** for evaluate-only) with:
     - `ocgg_identity`: `"W-OCGG"`
     - `plan_hash`: (integration hash for `{ domain, operations }`, e.g. `integration_plan_hash` from dude-x or from `/gate/evaluate`)
     - `operations`: e.g. one `deploy` operation to a production target
     - `deployment_target`: `"production"`
     - **No** `approval_reference` or `approver_id`

2. **Governance decision (Scene 2)**  
   - Response: `gate_outcome: "BLOCK"`, `reason_codes: ["PROD_DEPLOY_NO_APPROVAL"]`.  
   - For **POST /gate/evaluate**: `outcome: "BLOCK"`, `defect_list` with message containing “approval”.

3. **User corrects (Scene 3)**  
   - Same request with `approval_reference: "demo-ref-001"` (or valid `approver_id`).

4. **PASS and authority (Scene 4)**  
   - **POST /task** with approval → `gate_outcome: "PASS"` → execution token issued → OpenClaw Gateway called.

5. **Execution (Scene 5)**  
   - Integration calls OpenClaw Gateway; response includes `execution_id`, `execution_response`.

6. **Receipt (Scene 6)**  
   - **GET /status/{task_id}** → `audit_history` with `gate_decision` and `execution_response` (execution reference, status, trace).

### Sample testing (Custom GPT / builder)

The **exact demo flow** is covered by automated tests so the system stays demo-ready and the Custom GPT (or any builder) can rely on it:

- **Test file:** `services/openclaw-integration/tests/test_demo_governance_59s.py`
- **Tests:**
  - **Scene 1–2:** Request without approval → BLOCK, `PROD_DEPLOY_NO_APPROVAL`, no execution.
  - **Scene 3–4:** Same plan with `approval_reference` → PASS, execution authorised (OpenClaw mocked).
  - **Full flow:** BLOCK → then PASS with approval → then GET status shows audit/receipt (gate_decision + execution_response).
  - **Gate evaluate:** POST /gate/evaluate with production and no approval → BLOCK and defect message containing “approval”.

Run the demo tests:

```bash
cd services/openclaw-integration
pip install -r requirements-test.txt
PYTHONPATH=. python -m pytest tests/test_demo_governance_59s.py -v
```

### Technical truth preserved

- No execution without **PASS**.
- No execution without **token/authority** (execution token bound to spec_hash, plan_hash, policy_version, identity).
- No raw request directly triggers the runtime; the integration gate and token step sit in front.
- Execution is bounded (plan operations only).
- Decisions and execution are recorded in `audit_history` and gate/task records.

---

## What not to do

- Do not make a feature video, narrated explainer, or deck.
- Do not show only a successful execution.
- Do not overcomplicate the UI or hide CLARIFY/REFORM/BLOCK/PASS behind vague UX.
- Do not fake a flow that breaks the real system (no execution without PASS and token).

---

## Recording requirements

- **Length:** max 59 seconds.  
- **Style:** real screen recording only.  
- **Edits:** minimal (trim dead time, zoom if needed, simple callouts only if necessary).

---

## Final instruction

Build the shortest real flow that proves:

**“OpenClaw is governed before it executes.”**

If the video does not clearly show **refusal first**, do not treat it as complete.
