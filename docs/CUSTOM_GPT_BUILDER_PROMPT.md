# Custom GPT Builder — Instructions & Configuration

Reference for building the Custom GPT that acts as the Builder System for OpenClaw. The flow uses **dude-x** (planner/compiler) and the **OpenClaw Integration API** (gate + execution).

- **Building from scratch with ChatGPT?** You can skip section 1 (Instructions) and use this doc as the **single reference** for architecture, API flow, endpoints, auth, and request/response shapes. ChatGPT can help you design the GPT’s behavior; sections 2–4 give it (and you) the exact contracts.
- **Want a ready-made prompt?** Use the **short instructions** in section 1 (under 8000 characters) and **attach** `CUSTOM_GPT_KNOWLEDGE.md` as a knowledge file.

---

## 1. Custom GPT instructions (under 8000 characters)

**Instructions field limit: 8000 characters.** Use the text below in the Instructions field, and **attach `docs/CUSTOM_GPT_KNOWLEDGE.md`** as a knowledge document so the GPT has full API and flow details.

```markdown
You are the **OpenClaw Builder**: you turn user requests into executable plans using **dude-x** (planner/compiler), then submit them via the **OpenClaw Integration API**. You support web (W-OCGG) and recruiting (R-OCGG) deliverables, interpret execution results, and support follow-up (multi-turn) via the continue endpoint.

**Follow the attached knowledge document** for:
- Exact API flow: dude-x POST /compile → Integration POST /gate/evaluate (plan_hash "" or `integration_plan_hash`) → Integration POST /task with integration’s plan_hash; then optional POST /task/{task_id}/continue and GET /status/{task_id}.
- Dude-x spec shape (spec_version, identity, intent, target, decisions, constraints, signature) and that the integration uses its own plan_hash (from /gate/evaluate or `integration_plan_hash`), not dude-x’s.
- Allowed operation types per identity, response interpretation (completed/failed/partial/needs_review, gate BLOCK), and rules (auth: dude-x X-API-Key, Integration Bearer; no Gateway key; production approval when required).
- The **59-second governance demo** story (production deploy needs approval; how BLOCK vs PASS and receipts work; optional pointer to automated narrative tests for verification).

**Your behavior**: Understand what the user wants; choose identity (W-OCGG or R-OCGG) and intent (web-build, web-maintenance, or recruiting-update); build a valid dude-x spec and compile it; use the returned `ocgg_identity` and `operations` plus the integration plan hash (`integration_plan_hash` or `/gate/evaluate` response) to submit the task; summarize outcomes and offer continue when status is partial or needs_review. If dude-x or Integration URL/API key is missing, ask the user to set them in your configuration.
```

---

## 2. Actions (API) configuration

Configure **two** APIs in the Custom GPT editor: **dude-x** (planner/compiler) and **OpenClaw Integration** (gate + execution).

### 2.1 Dude-x (planner and compiler)

- **Base URL**: Your dude-x service URL (e.g. `https://your-dude-x.vercel.app` or local tunnel).
- **Authentication**: Custom header:
  - **Header**: `X-API-Key`
  - **Value**: `YOUR_DUDE_X_DUSKY_API_KEY` (same as dude-x’s `DUDE_X_DUSKY_API_KEY` env var.)

| Operation   | Method | Path               | Body / params |
|------------|--------|--------------------|---------------|
| Compile    | POST   | `/compile`         | JSON: dude-x spec (spec_version, identity, intent, target, decisions, constraints, signature) |
| Get plan   | GET    | `/plans/{plan_hash}` | Path param: `plan_hash` (from compile response) |

**POST /compile** body (dude-x spec; can also be sent as `{ "params": { ...spec } }` for GPT Action compatibility):  
- `spec_version`: `"1.0"`  
- `identity`: `"W-OCGG"` \| `"R-OCGG"`  
- `intent`: `"web-build"` \| `"web-maintenance"` \| `"recruiting-update"`  
- `target`: `{ "resource_id": string, "environment": "preview" \| "production" }`  
- `decisions`: `{ "domain": "web" \| "recruiting" \| null, "operations": [ { "op_id", "type", "target", "inputs", optional "outputs", "addon" } ] }`  
- `constraints`: object (e.g. `{}`)  
- `signature`: `{ "type": "human_signed", "signed_at": "<ISO8601>", "hash": "<non-empty>" }`  

Response: `plan_version`, `identity`, `ocgg_identity`, `domain`, `deployment_target`, `operations`, `rollback`, `plan_hash`, `integration_plan_hash`.

### 2.2 OpenClaw Integration (gate + execution)

- **Base URL**: Your integration base URL (e.g. `https://your-openclaw-integration.vercel.app` or local tunnel).
- **Authentication**: Bearer token:
  - **Header**: `Authorization`
  - **Value**: `Bearer YOUR_INTEGRATION_API_KEY`  
  (Same as the integration’s `INTEGRATION_API_KEY`; do **not** use the OpenClaw Gateway key.)

| Operation        | Method | Path                     | Body / params |
|-----------------|--------|--------------------------|---------------|
| Evaluate gate   | POST   | `/gate/evaluate`         | JSON: `ocgg_identity`, `plan_hash` (use `""` or `integration_plan_hash`), `operations`, optional `goal`, `context`, `acceptance_criteria` |
| Submit task     | POST   | `/task`                  | JSON: `ocgg_identity`, `plan_hash` (use `integration_plan_hash` or gate response), `operations`, optional `goal`, `context`, `acceptance_criteria` |
| Continue task   | POST   | `/task/{task_id}/continue` | JSON: `message`, optional `prior_context` |
| Task status     | GET    | `/status/{task_id}`      | Path param: `task_id` |

Schema hints for the Integration API:

- **POST /gate/evaluate**  
  - `ocgg_identity`: string (required), enum: `W-OCGG`, `R-OCGG`  
  - `plan_hash`: string (required by gate; send `""` to get server-computed hash in response or use `integration_plan_hash`)  
  - `operations`: array of objects; each has `type`, optional `op_id`, `target`, `inputs` (object), optional `outputs`  
  - `goal`, `context`, `acceptance_criteria`: optional  

- **POST /task**  
  - Same as evaluate but `plan_hash` is **required** (use value from evaluate response or `integration_plan_hash`).  

- **POST /task/{task_id}/continue**  
  - `message`: string (required)  
  - `prior_context`: string (optional)  

- **GET /status/{task_id}**  
  - Path parameter: `task_id` (UUID).  

---

## 3. User-facing setup (what to tell the GPT user)

- "This GPT uses **dude-x** to plan and compile your request, then submits the plan to **OpenClaw** via the Integration API. Configure both dude-x and the Integration API (base URLs and API keys) in this GPT’s Actions."
- "Plans are for **web** (W-OCGG) or **recruiting** (R-OCGG). Describe what you want; I’ll build a spec, compile it with dude-x, pass the gate, and submit the task. For follow-ups, I’ll use the continue endpoint so the same task keeps context."

---

## 4. Summary

- **Instructions**: Paste the short instructions from section 1 (under 8000 chars) and **attach** `CUSTOM_GPT_KNOWLEDGE.md` as a knowledge file.
- **Actions**: Add **two** APIs:
  1. **dude-x**: base URL + **X-API-Key**; operations: POST `/compile`, GET `/plans/{plan_hash}`.
  2. **OpenClaw Integration**: base URL + **Bearer INTEGRATION_API_KEY**; operations: POST `/gate/evaluate`, POST `/task`, POST `/task/{task_id}/continue`, GET `/status/{task_id}`.
- **Behavior**: The GPT builds a dude-x spec → compiles with dude-x → uses returned `ocgg_identity`, `operations`, and integration plan hash (`integration_plan_hash` or `/gate/evaluate`) to pass the gate → submits the task → interprets outcomes and supports continue/status. Single, aligned builder experience: dude-x (planner/compiler) + OpenClaw Integration (gate + execution).

- **59-second governance demo & verification:** The flow (BLOCK without approval → PASS with **approval_reference** → receipt via **GET /status/{task_id}**) is documented for the Custom GPT in **`CUSTOM_GPT_KNOWLEDGE.md`** (section *59-second governance demo*). Developers can run narrative + DB verification tests: `PYTHONPATH=. python3 -m pytest tests/test_demo_governance_59s.py -v -s` from `services/openclaw-integration`. Technical mapping: **`docs/DEV_BRIEF_59_SECOND_DEMO.md`**.
