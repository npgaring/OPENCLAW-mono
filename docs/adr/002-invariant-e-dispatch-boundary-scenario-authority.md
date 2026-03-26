# ADR 002: Invariant-E authority for `PASS_GOV_FAIL_INVARIANT_E_CAPABILITY`

## Context

`validation.dispatch_boundary_scenario: PASS_GOV_FAIL_INVARIANT_E_CAPABILITY` is a deterministic test harness: governance is modeled as PASS while Invariant-E must deny execution on capability grounds.

The shared evaluation frame (`POST /evaluation-frame/evaluate`) builds execution envelopes with `governance_outcome="PENDING"` (governance not run yet). If that scenario were applied only when `governance_outcome == "PASS"`, the frame could report `invariant_e_result.decision: EXECUTION_ALLOWED` while `POST /task` (after governance PASS) reported `EXECUTION_DENIED`—splitting authority across layers.

## Decision

1. **Authoritative preview:** For this scenario, **Invariant-E outcome on `POST /evaluation-frame/evaluate` is the single honest preview** of execution admission for the same payload, trace, plan hash, and operations. The frame must report `EXECUTION_DENIED` with `IE_DENIED_CAPABILITY_NOT_ALLOWED` (and composite `frame_status: BLOCKED`) when the scenario is set.

2. **Envelope construction:** `build_execution_envelope` applies `PASS_GOV_FAIL_INVARIANT_E_CAPABILITY` when `governance_outcome` is **`PASS` or `PENDING`**, so the pre-governance frame and post-governance dispatch use the same capability slice.

3. **Downstream reuse:** `POST /gate/evaluate` runs the same `run_evaluation_frame` first. If the composite frame is not `PASS`, the gate returns `outcome: BLOCK` and does not evaluate GateEngine; `evaluation_frame` in that response matches the standalone frame endpoint. `POST /task` re-evaluates the same frame; when Invariant-E denies at the frame, it short-circuits with `gate_outcome: BLOCK` and `status: invariant_e_denied` without contradicting the preview.

## Consequences

- Clients cannot obtain a `governance_evaluation_id` from `POST /gate/evaluate` for requests that are already frame-blocked by this scenario; they should not expect governance PASS in the gate response when the frame shows Invariant-E denial.
- Playground and integrators should treat **frame → gate embedded frame → task `evaluation_frame`** as aligned for Invariant-E on fixed inputs.
