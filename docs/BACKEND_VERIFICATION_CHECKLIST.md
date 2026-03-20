# Backend verification checklist (before expanding governance proofs)

Use this to **confirm with the backend / integration owners** what is guaranteed today and what is out of scope. Paste answers and evidence (sample responses, test output links) back into your runbook or ticket.

> **Repo snapshot:** OpenClaw-mono (`services/dude-x`, `services/openclaw-integration`).  
> **Filled answers below** reflect code inspection of this monorepo; **1.1 team names** and **staging URLs** must be completed by owners.

---

## 1. Ownership and surfaces

| # | Question | Answer (backend) | Evidence |
|---|----------|------------------|----------|
| 1.1 | Which service owns **`POST …/compile`** and **`POST …/gate/evaluate`** (repo, team)? | **`POST /compile`** → **DUDE-X** service: `services/dude-x/` (FastAPI router in `app/api/compile.py`). **`POST /gate/evaluate`** → **OpenClaw Integration** service: `services/openclaw-integration/` (`app/api/gate.py`). **Team / on-call:** *TBD — fill org name.* | Code: `services/dude-x/app/main.py` (`compile_api.router`); `services/openclaw-integration/app/main.py` (`gate.router` prefix `/gate`). |
| 1.2 | Is there a **published API contract** (OpenAPI, internal doc) for compile + gate request/response? | **Yes (generated OpenAPI).** Both apps are FastAPI with **`/docs`**, **`/redoc`**, **`/openapi.json`** (protected routes on integration also appear in schema with `bearerAuth`). No separate “governance contract” PDF in-repo beyond code + examples on models. | `services/openclaw-integration/app/main.py` (`docs_url`, `redoc_url`, `custom_openapi`); `services/dude-x/app/main.py` (FastAPI app). Example bodies on `POST /compile` in `services/dude-x/app/api/compile.py`. |
| 1.3 | Are **staging** and **production** behavior identical for hashing and gate policy, or documented differences? | **Code is the same** per deploy artifact; **runtime can differ** via env. Integration: **`POLICY_VERSION_EXECUTION_OVERRIDE`** can change effective policy version at execution time (`app/gate/policy.py` → `get_policy_version_at_execution()`). **Hashing** is code-defined (no env flag for canonical JSON); **DB URL / SSL** differ by env. **Documented differences:** *TBD — owner to confirm staging env vars and any forked config.* | `services/openclaw-integration/app/gate/policy.py` (`get_policy_version_at_execution`); `services/openclaw-integration/app/core/config.py` (settings). |

---

## 2. Determinism (compile)

| # | Question | Answer (backend) | Evidence |
|---|----------|------------------|----------|
| 2.1 | For **identical** request body (byte-identical), is **`plan_hash` / `integration_plan_hash`** guaranteed stable across repeated calls? | **Yes** for the **same validated spec → same `build_plan` output**: `plan_hash` and `integration_plan_hash` are deterministic functions of the normalized plan body (see 2.4). Repeated compiles of the **same** `SpecIn` produce the same hashes. **Caveat:** DB may **dedupe** by `spec_hash` / `plan_hash` on insert; behavior is still deterministic. | `services/dude-x/app/compiler/planner.py` (`integration_hash_payload`, `hash_payload` on `plan_hash_body`); `services/dude-x/tests/test_governance.py` (`test_deterministic_hash_with_identity`, `test_identity_included_in_plan_hash`). |
| 2.2 | For **semantically identical** JSON (e.g. different **key order**, or **extra unknown top-level fields**), does compile still produce the **same** hashes, or is that undefined? | **Key order (JSON):** After `model_validate`, dict order does not affect hashing — **same semantic content → same hashes** (canonical JSON uses sorted keys). **Extra unknown top-level fields:** **Rejected** — `SpecIn` uses **`extra="forbid"`** (`services/dude-x/app/models/spec.py`). Request fails validation; **not** “same hash with extras stripped.” | `services/dude-x/app/core/hashing.py` (`canonical_json`, `hash_payload`, `integration_hash_payload`); `services/dude-x/app/models/spec.py` (`SpecIn` `extra="forbid"`); `services/dude-x/app/api/compile.py` (`parse_compile_body` → `SpecIn.model_validate`). |
| 2.3 | Which fields are **intentionally non-deterministic** (timestamps, ids inside `operations`)? | **Not explicitly documented** in a single spec. **In practice:** `spec_hash` includes full validated spec payload (e.g. `signature.signed_at`, `signature.hash` strings) — if those strings change, **`spec_hash` changes**. **`plan_hash`** / **`integration_plan_hash`** are built from **structured plan fields** in `planner.py` (version, identity, domain, operations, rollback) — **no wall-clock timestamp** is injected into the hash inputs there. **Operation `op_id`:** client-supplied strings; **same logical plan with different `op_id` values → different hashes.** | `services/dude-x/app/compiler/planner.py`; `services/dude-x/app/api/compile.py` (`spec_hash = hash_payload(spec_payload)`). |
| 2.4 | Is there a **documented normalization** step (what the server canonicalizes before hashing)? | **Implemented, not a standalone policy doc.** **DUDE-X:** `canonical_json` + `hash_payload` apply **recursive float→int** for integer-valued floats, then **`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True)`**. **`integration_plan_hash`** uses **sorted dict keys recursively** without the float normalization — **explicitly noted as compatibility** with OpenClaw integration. **Integration gate** uses `services/openclaw-integration/app/core/security.py` **`hash_payload`** (sorted recursive structure, no float normalization in that file). | `services/dude-x/app/core/hashing.py` (comments + `integration_hash_payload`); `services/openclaw-integration/app/core/security.py`. |

**Suggested self-checks (if allowed on staging):**  
Three calls with canonical body → compare hashes.  
Optional: same payload with reordered keys → compare to canonical hashes.

---

## 3. Gate / enforcement

| # | Question | Answer (backend) | Evidence |
|---|----------|------------------|----------|
| 3.1 | What **invariants** does the gate enforce (e.g. binding `integration_plan_hash` to body, rejecting missing fields, production rules)? | **GateEngine** (`openclaw-integration`) enforces, among others: **schema** (dict, required fields including **`plan_hash`**, **`operations`** list), **identity** (`ocgg_identity` matches context and known identities), **canonical plan hash**: recomputes `hash_payload({"domain", "operations"})` and compares to submitted **`plan_hash`** (**`PLAN_HASH_MISMATCH`** if wrong), **operation count**, **forbidden op types**, **allowed ops per identity**, **contradictions**, **prod deploy** rules (`deployment_target` in prod set → requires **`approver_id`** or **`approval_reference`**, SOD on approver), **path / network / resource / plugin** policy hooks (see `engine.py` + `policy.py`). **`integration_plan_hash`:** accepted as **alias for `plan_hash`** on **task** request model only (`TaskSubmitRequest` validator); gate still validates **equality to computed** canonical hash for that body. | `services/openclaw-integration/app/gate/engine.py`; `services/openclaw-integration/app/gate/policy.py`; `services/openclaw-integration/app/models/task.py` (`_alias_integration_plan_hash`). |
| 3.2 | Is **`plan_hash` required** on the gate request, or optional? What happens if it is **wrong** vs **absent** vs **from another plan**? | **Effectively required** for a passing evaluation: `GateEngine` treats missing/empty **`plan_hash`** as **`MISSING_FIELD`** (BLOCK). **Wrong hash** (does not match server canonical for `domain` + `operations`): **`PLAN_HASH_MISMATCH`** (BLOCK). **“From another plan”:** if client sends **another plan’s operations** with **that plan’s hash**, the hash still must match **canonical for those operations** — mismatch if they don’t align. **No cryptographic link** to DUDE-X compile record in this path. | `services/openclaw-integration/app/gate/engine.py` (lines ~43–69). |
| 3.3 | Is there a **test suite** or policy regression suite for gate outcomes the team can point to? | **Yes (automated tests in repo).** Examples: `services/openclaw-integration/tests/test_gate_engine.py`, `services/openclaw-integration/tests/test_governance_validation.py`, `services/openclaw-integration/tests/test_demo_governance_59s.py`. **DUDE-X:** `services/dude-x/tests/test_governance.py`. **Evidence to attach:** CI job output or `pytest … -v` log. | Paths above; run: `cd services/openclaw-integration && pytest tests/ -v` (with test deps). |
| 3.4 | Can any path **bypass** gate for execution (direct task API, internal admin, feature flag)? | **Partial bypasses / caveats:** (1) **`POST /task/{id}/continue`** — **does not re-run the full gate**; calls OpenClaw client with Bearer only (follow-up after an already-gated task). (2) **`POST /test/execute`** — **proxies raw OpenResponses body to the gateway** with **integration API key only**; **does not require** execution token or gate pass in **current** `task.py` (treat as **non-governed test surface** unless removed or hardened). (3) **Main `POST /task`** — runs **GateEngine** before token + execute. | `services/openclaw-integration/app/api/task.py` (`submit_task`, `continue_task`, `test_execute`). |

---

## 4. Replay / audit (server-side)

| # | Question | Answer (backend) | Evidence |
|---|----------|------------------|----------|
| 4.1 | Is there an **append-only audit log** (or equivalent) that records compile + gate + task with a shared **trace / correlation id**? | **Partial, not unified.** **DUDE-X:** `compile_events` (+ `specs`, `plans`) in SQL migrations. **Integration:** `gate_decisions`, `tasks` (incl. **`audit_history`** JSON), `audit_events` (via **`POST /audit`**), `used_execution_tokens`. **Shared trace/correlation id** across compile → gate → task: **not implemented** as a first-class field in code reviewed (no standard `trace_id` plumbed end-to-end). **`task_id`** links integration rows; **compile** uses **`spec_hash` / `plan_hash`**. | `migration/001_dude_x_tables.sql` (and copies under services); `services/openclaw-integration/app/models/gate_decision.py`, `task.py`, `audit_event.py`; `services/openclaw-integration/app/api/audit.py`. |
| 4.2 | Can **decisions be reconstructed** from **logs only** (no client `localStorage`)? If yes, what format and retention? | **Partially.** An operator with **DB access** can reconstruct **gate outcome + hashes + plan_json + audit_history** for tasks and **compile_events** for DUDE-X. **Not guaranteed “logs only”** in the sense of a single append-only event stream; **no** packaged replay tool documented here. **Retention:** *TBD — database / hosting policy (Neon, Vercel, etc.).* | DB schemas + API handlers above. |
| 4.3 | Are request/response bodies **logged**, **hashed**, or **omitted** (PII / size policy)? | **Default app logging** is minimal in snippets reviewed; **persistence** stores **JSON payloads** on tasks/plans/specs (size/PII = **data classification / retention policy**, *TBD*). **Hashes** (`spec_hash`, `plan_hash`, `execution_token_hash`) stored on decisions/tokens. | `services/openclaw-integration/app/logging/logger.py` (if present); model fields in `Task`, `GateDecisionRecord`. |

---

## 5. Human approval

| # | Question | Answer (backend) | Evidence |
|---|----------|------------------|----------|
| 5.1 | Who is authoritative for **`approval_reference` / `approver_id`** validation—the gate only, task API, both? | **Gate only** for **policy enforcement**: if `deployment_target` is **prod/production**, gate requires **non-empty** **`approver_id`** OR **`approval_reference`** (and SOD: approver ≠ `ocgg_identity`). **No external approval registry** lookup in code — **presence/format not cryptographically verified** against a ticketing system. **Task API** persists `approver_id` on `GateDecisionRecord` from gate decision; does not independently “approve.” | `services/openclaw-integration/app/gate/engine.py` (prod deploy block); `services/openclaw-integration/app/api/task.py` (`GateDecisionRecord`); `services/openclaw-integration/app/gate/policy.py` (`APPROVER_FIELD`, `APPROVAL_REFERENCE_FIELD`). |
| 5.2 | Can **`POST /task`** succeed **without** approval when policy requires it (any known gap)? | **Should not pass gate** without `approver_id` or `approval_reference` when `deployment_target` ∈ prod set — **BLOCK** with **`PROD_DEPLOY_NO_APPROVAL`**. **Gaps:** if **`deployment_target` omitted or not prod**, prod rules don’t apply; **approval strings are not validated** against a real system. **Tests:** `test_demo_governance_59s.py` scenes for prod without approval. | `services/openclaw-integration/app/gate/engine.py`; `services/openclaw-integration/tests/test_demo_governance_59s.py`. |

---

## 6. What you need back from backend (minimum)

1. **Written answers** to the tables above (even “not supported yet”).  
   → *This file is a first pass from code; owners should correct **1.1**, **1.3**, **4.2 retention**, **4.3 logging**, and confirm **3.4** if `/test/execute` is exposed in prod.*

2. **One** pointer to contract or runbook.  
   → *Suggested:* link to **`/openapi.json`** for each deployed service + path to **`docs/GOVERNANCE_VALIDATION_REPORT.md`** (if used) or internal runbook URL.

3. **Optional:** confirmation email or ticket comment you can attach to your governance evidence pack.

Until those are answered, treat **adversarial determinism**, **full bypass formalisation**, and **log-only replay** as **not verified**—only **demo-scoped** behavior is proven.

---

## Appendix — quick reference (paths)

| Concern | Location |
|---------|----------|
| Compile | `services/dude-x/app/api/compile.py`, `app/compiler/planner.py`, `app/core/hashing.py` |
| Gate evaluate | `services/openclaw-integration/app/api/gate.py`, `app/gate/engine.py` |
| Task submit | `services/openclaw-integration/app/api/task.py` |
| Policy constants | `services/openclaw-integration/app/gate/policy.py` |
| Integration hash | `services/openclaw-integration/app/core/security.py` |
| Compile + DB schema | `migration/001_dude_x_tables.sql` (and copies under `services/*/`) |
| Governance / trace_id / bypass policy | `docs/governance-backend.md`, `docs/GATE_MUTATION_MATRIX.md` |
| Replay API | `services/openclaw-integration/app/api/audit.py` (`GET /audit/reconstruct`) |
