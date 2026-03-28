"""
GRL (governance rule layer): policy evaluation previously implemented as GateEngine.

This module wraps the existing engine so governance stays one law in the atomic evaluation model
without re-homing all policy tables or defect types.
"""
from __future__ import annotations

from typing import Any

from app.evaluation.state import EvaluationState
from app.gate.engine import GateEngine
from app.gate.models import GateEvaluation


def evaluate_grl(state: EvaluationState) -> GateEvaluation:
    g = state.governable
    spec: dict[str, Any] = dict(g.spec_for_gate)
    return GateEngine().evaluate(spec, g.ocgg_identity)
