# Atomic evaluation architecture (Integration service)

## Overview

One immutable **`EvaluationState`** per request; one **`EvaluationEngine.evaluate(state)`** runs **all four laws** every time (no partial modes, no `include_grl` flags):

- **Invariant-C** — semantic / constraint admissibility  
- **UATO** — trust × authority (`ESCALATE` / `REQUIRE_APPROVAL` are UATO-level; final aggregate uses `REQUIRE_APPROVAL` + `uato_approval_kind`)  
- **GRL** — governance rule layer (wraps legacy `GateEngine`)  
- **Invariant-E (decision mode)** — envelope from **`derive_execution_envelope_from_state(state)`** only (fixed structural phase constant in `invariant_e_view`, **no** GRL-derived fields on `EvaluationState`)

**Aggregation** is **set-based**: every law is classified into failures and/or approval sources; then exactly one **`AtomicFinalDecision`**: `STOP` (any failure), else `REQUIRE_APPROVAL` (any approval need), else `EXECUTE`. No sequential “first failure wins” ordering among laws. Implemented in `app.evaluation.aggregator.aggregate_atomic` and `build_atomic_evaluation_result`.

**`CompositeFrameResult.frame_status`** is derived **only** from `final_decision` via `frame_status_from_final_decision` (no GRL-only or partial-law overrides). HTTP clients may still see legacy **`ESCALATED`** via `app.api.response_mapper.presentation_frame_status_value` when `uato_approval_kind == "ESCALATION"`.

## `plan_hash` vs `state_hash`

- **`plan_hash`** — `hash_payload({ domain, operations })` (builder / client contract). Unchanged.  
- **`shared_state_hash`** — legacy frame fingerprint in audit.  
- **`state_hash`** — full `EvaluationState` canonical material (governable + UATO trust snapshot fields in `builder._canonical_evaluation_material`).

## Invariant-E: decision vs dispatch

| Mode | Path | When |
|------|------|------|
| **Decision** | `derive_execution_envelope_from_state` → `evaluate_invariant_e_decision(envelope)` | Inside `EvaluationEngine.evaluate` |
| **Dispatch** | `build_execution_envelope(..., governance_outcome="PASS")` → `enforce_invariant_e_dispatch` | After aggregate `EXECUTE`, before token/Gateway |

## Evaluator input trace

`AtomicEvaluationResult.evaluator_input_hashes` maps each law id to **`state_hash`** (must all match). Persisted under `evaluation_records.payload_json.evaluator_input_hashes` (short keys `C`, `UATO`, `GRL`, `E`). Non-production `app_env` asserts state hash unchanged after evaluation and `composite_frame_from_atomic` asserts `frame_status` matches `final_decision`.

## Endpoints

- **`POST /gate/evaluate`**, **`POST /task`**, **`POST /evaluation-frame/evaluate`** — all call **`default_engine.evaluate(ev_state)`**. Responses may **filter** fields (e.g. evaluation-frame JSON shape) without skipping laws.

## Approvals

**`build_evaluation_state_with_resolved_approval(body, trace_id)`** rebuilds state with approval fields merged into the spec / `ApprovalFrameContext` (state transformation). **`POST /task`** resume uses that builder then **`evaluate(new_state)`** — not a procedural “continue”.

## Persistence

**`evaluation_records`** payload includes `state_hash`, `evaluator_input_hashes`, structured **`results`** (`C` / `UATO` / `GRL` / `E`), `failed_laws`, `approval_sources`, `final_decision`, per-law **`laws`** rows, and optional `uato_approval_kind`.
