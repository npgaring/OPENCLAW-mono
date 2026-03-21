"""UATO: upstream admissibility (trust × authority) before governance gate evaluation."""
from app.uato.build_input import build_uato_input_from_spec
from app.uato.evaluator import evaluate_uato
from app.uato.trace import redacted_trace_json, to_trace_record, uato_input_hash
from app.uato.types import UATO_DECISION_VERSION, UatoDecision, UatoInput, UatoResult

__all__ = [
    "UATO_DECISION_VERSION",
    "UatoDecision",
    "UatoInput",
    "UatoResult",
    "build_uato_input_from_spec",
    "evaluate_uato",
    "redacted_trace_json",
    "to_trace_record",
    "uato_input_hash",
]
