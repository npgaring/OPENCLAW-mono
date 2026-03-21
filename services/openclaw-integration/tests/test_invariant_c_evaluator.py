"""Invariant-C evaluator unit tests (Meaning, ConstraintCompliance, TemporalConsistency, GoalCoherence, Convergence)."""
from app.invariant_c import evaluate_invariant_c
from app.models.openai_flow import CandidatePlan, CandidatePlanMetadata, CandidatePlanStep


def _base_plan() -> CandidatePlan:
    return CandidatePlan(
        steps=[
            CandidatePlanStep(id="s1", type="write_config", action="write_config", target="web/app", inputs={}),
            CandidatePlanStep(
                id="s2",
                type="build",
                action="build",
                target="web/app",
                inputs={"depends_on": ["s1"]},
            ),
        ],
        metadata=CandidatePlanMetadata(requiresApproval=False, riskLevel="low"),
    )


def test_meaning_blocks_duplicate_step_ids():
    plan = CandidatePlan(
        steps=[
            CandidatePlanStep(id="same", type="write_config", action="write_config", target="web/app", inputs={}),
            CandidatePlanStep(id="same", type="build", action="build", target="web/app", inputs={}),
        ],
        metadata=CandidatePlanMetadata(requiresApproval=False, riskLevel="low"),
    )
    result = evaluate_invariant_c(candidate_plan=plan, ocgg_identity="W-OCGG", intent="web-build", objective="Build the website")
    assert result.decision == "BLOCK"
    assert "INVARIANT_C_MEANING_DUPLICATE_STEP_ID" in result.reason_codes


def test_constraint_compliance_blocks_identity_forbidden_operation():
    plan = CandidatePlan(
        steps=[CandidatePlanStep(id="s1", type="deploy", action="deploy", target="recruiting/db", inputs={})],
        metadata=CandidatePlanMetadata(requiresApproval=False, riskLevel="low"),
    )
    result = evaluate_invariant_c(candidate_plan=plan, ocgg_identity="R-OCGG", intent="recruiting-update", objective="Update recruiting content")
    assert result.decision == "BLOCK"
    assert "INVARIANT_C_CONSTRAINT_IDENTITY_OPERATION_NOT_ALLOWED" in result.reason_codes


def test_temporal_consistency_blocks_backward_dependency():
    plan = CandidatePlan(
        steps=[
            CandidatePlanStep(id="s1", type="write_config", action="write_config", target="web/app", inputs={"depends_on": ["s2"]}),
            CandidatePlanStep(id="s2", type="build", action="build", target="web/app", inputs={}),
        ],
        metadata=CandidatePlanMetadata(requiresApproval=False, riskLevel="low"),
    )
    result = evaluate_invariant_c(candidate_plan=plan, ocgg_identity="W-OCGG", intent="web-build", objective="Build the website")
    assert result.decision == "BLOCK"
    assert "INVARIANT_C_TEMPORAL_BACKWARD_DEPENDENCY" in result.reason_codes


def test_goal_coherence_blocks_identity_intent_mismatch():
    result = evaluate_invariant_c(candidate_plan=_base_plan(), ocgg_identity="R-OCGG", intent="web-build", objective="Build the website")
    assert result.decision == "BLOCK"
    assert "INVARIANT_C_GOAL_DOMAIN_MISMATCH" in result.reason_codes or "INVARIANT_C_GOAL_IDENTITY_INTENT_MISMATCH" in result.reason_codes


def test_convergence_blocks_adjacent_repeated_step():
    plan = CandidatePlan(
        steps=[
            CandidatePlanStep(id="s1", type="write_config", action="write_config", target="web/app", inputs={"path": "a"}),
            CandidatePlanStep(id="s2", type="write_config", action="write_config", target="web/app", inputs={"path": "a"}),
        ],
        metadata=CandidatePlanMetadata(requiresApproval=False, riskLevel="low"),
    )
    result = evaluate_invariant_c(candidate_plan=plan, ocgg_identity="W-OCGG", intent="web-maintenance", objective="Maintain the website")
    assert result.decision == "BLOCK"
    assert "INVARIANT_C_CONVERGENCE_REPEATED_ADJACENT_STEP" in result.reason_codes


def test_pass_valid_candidate_plan():
    result = evaluate_invariant_c(candidate_plan=_base_plan(), ocgg_identity="W-OCGG", intent="web-build", objective="Build the website")
    assert result.decision == "PASS"
    assert result.reason_codes == ()


def test_goal_coherence_blocks_missing_objective():
    result = evaluate_invariant_c(candidate_plan=_base_plan(), ocgg_identity="W-OCGG", intent="web-build")
    assert result.decision == "BLOCK"
    assert "INVARIANT_C_GOAL_MISSING_OBJECTIVE" in result.reason_codes
