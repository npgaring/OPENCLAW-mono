"""Persist atomic evaluation results (evaluation_records)."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.models import AtomicEvaluationResult, LawId
from app.models.evaluation_record import EvaluationRecord

_LAW_KEY = {
    LawId.INVARIANT_C.value: "C",
    LawId.UATO.value: "UATO",
    LawId.GRL.value: "GRL",
    LawId.INVARIANT_E_DECISION.value: "E",
}


def atomic_evaluation_to_payload(atomic: AtomicEvaluationResult) -> dict[str, Any]:
    ev_hashes = {_LAW_KEY.get(k, k): v for k, v in atomic.evaluator_input_hashes}
    results: dict[str, Any] = {
        "C": {
            "decision": atomic.invariant_c.decision,
            "reason_codes": list(atomic.invariant_c.reason_codes),
        },
        "UATO": {
            "decision": atomic.uato.decision,
            "reason_codes": list(atomic.uato.reason_codes),
        },
        "GRL": {
            "outcome": atomic.grl.decision.outcome.value,
            "reason_codes": list(atomic.grl.decision.reason_codes),
        },
        "E": {
            "decision": atomic.invariant_e_decision.decision,
            "reason_codes": list(atomic.invariant_e_decision.reason_codes),
        },
    }
    return {
        "state_hash": atomic.state_hash,
        "evaluator_input_hashes": ev_hashes,
        "results": results,
        "failed_laws": list(atomic.failed_laws),
        "approval_sources": list(atomic.approval_sources),
        "uato_approval_kind": atomic.uato_approval_kind,
        "final_decision": atomic.final_decision.value,
        "approval_required_governance": atomic.approval_required_governance,
        "laws": [
            {
                "law_id": lr.law_id,
                "passed": lr.passed,
                "reason_codes": list(lr.reason_codes),
                "policy_or_version": lr.policy_or_version,
                "extra": lr.extra,
            }
            for lr in atomic.law_records
        ],
    }


async def persist_evaluation_record(
    session: AsyncSession,
    atomic: AtomicEvaluationResult,
    *,
    task_id: Optional[str] = None,
) -> str:
    row = EvaluationRecord(
        trace_id=atomic.trace_id,
        state_hash=atomic.state_hash,
        task_id=task_id,
        payload_json=atomic_evaluation_to_payload(atomic),
    )
    session.add(row)
    await session.flush()
    return row.evaluation_id
