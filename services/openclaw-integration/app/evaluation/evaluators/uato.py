"""UATO law: trust × authority admissibility over EvaluationState."""
from __future__ import annotations

from app.evaluation.state import EvaluationState
from app.uato import build_uato_input_from_spec, evaluate_uato
from app.uato.types import UatoResult


def evaluate_uato_law(state: EvaluationState) -> UatoResult:
    g = state.governable
    uato_in = build_uato_input_from_spec(
        g.spec_for_gate,
        ocgg_identity=g.ocgg_identity,
        trace_id=g.trace_id,
        uato_hints=g.uato_hints,
        validation_controls=g.validation_controls,
    )
    return evaluate_uato(uato_in)
