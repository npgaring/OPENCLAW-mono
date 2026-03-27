"""OpenAI Vessel + unified evaluation frame + Substrate Adapter endpoints."""
from __future__ import annotations

import json
import hashlib
import math
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_payload
from app.core.trace_id import normalize_trace_id
from app.db.session import get_session
from app.evaluation_frame.response_mapper import to_evaluation_frame_response
from app.evaluation_frame import run_evaluation_frame
from app.evaluation_frame.build import build_shared_governable_state_from_adapter_candidate
from app.evaluation_frame.state import FrameStatus
from app.models import (
    AdapterToSubstrateRequest,
    AdapterToSubstrateResponse,
    CandidatePlan,
    InvariantCDecisionRecord,
    OpenAIPlanOutput,
    OpenAIPlanRequest,
    OpenAIVesselEvent,
    SubstrateAdapterEvent,
)
from app.services.openai_vessel import (
    OpenAIVesselClient,
    OpenAIVesselConfigError,
    OpenAIVesselSchemaError,
    OpenAIVesselUpstreamError,
    summarize_openai_upstream_error,
)

router = APIRouter()


def _derive_uato_hints_from_candidate(candidate_plan: CandidatePlan) -> dict[str, str]:
    """
    Adapter-owned UATO defaults from planner metadata.

    - low risk -> HIGH authority (normal pass path)
    - medium/high risk or requiresApproval -> LOW authority (approval-required path)
    """
    risk = candidate_plan.metadata.riskLevel.value
    authority = "LOW" if candidate_plan.metadata.requiresApproval or risk in ("medium", "high") else "HIGH"
    return {
        "trust_level": "HIGH",
        "authority_level": authority,
        "trust_source": "OPENAI_VESSEL",
        "request_source": "OPENAI_VESSEL",
    }


@router.post("/openai/plan", response_model=OpenAIPlanOutput)
async def openai_plan(
    body: OpenAIPlanRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    trace_id = normalize_trace_id(body.trace_id)
    request_payload = body.model_dump(mode="python")
    request_payload["trace_id"] = trace_id
    request_hash = hash_payload(request_payload)
    vessel = OpenAIVesselClient()
    try:
        output, raw_response = await vessel.generate_candidate_plan(body)
        candidate_plan_hash = hash_payload(output.candidate_plan.model_dump(mode="python"))
        session.add(
            OpenAIVesselEvent(
                trace_id=trace_id,
                ocgg_identity=body.ocgg_identity,
                intent=body.intent,
                request_hash=request_hash,
                candidate_plan_hash=candidate_plan_hash,
                model=settings.openai_plan_model,
                request_payload=request_payload,
                raw_response=raw_response,
                schema_valid=True,
                outcome="PASS",
                reason_codes=[],
            )
        )
        await session.commit()
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Candidate-Plan-Hash"] = candidate_plan_hash
        return output
    except OpenAIVesselConfigError as e:
        await _persist_vessel_block(
            session=session,
            trace_id=trace_id,
            body=body,
            request_hash=request_hash,
            reason_codes=e.reason_codes,
            raw_response=e.raw_response,
            code="OPENAI_CONFIG_ERROR",
            status_code=503,
        )
    except OpenAIVesselSchemaError as e:
        await _persist_vessel_block(
            session=session,
            trace_id=trace_id,
            body=body,
            request_hash=request_hash,
            reason_codes=e.reason_codes,
            raw_response=e.raw_response,
            code="OPENAI_SCHEMA_VIOLATION",
            status_code=422,
        )
    except OpenAIVesselUpstreamError as e:
        await _persist_vessel_block(
            session=session,
            trace_id=trace_id,
            body=body,
            request_hash=request_hash,
            reason_codes=e.reason_codes,
            raw_response=e.raw_response,
            code="OPENAI_UPSTREAM_ERROR",
            status_code=502,
        )


@router.post("/openai/plan-malformed", response_model=OpenAIPlanOutput)
async def openai_plan_malformed(
    body: OpenAIPlanRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Intentional failure-test planner output: schema-valid plan that should fail adapter/substrate checks."""
    trace_id = normalize_trace_id(body.trace_id)
    request_payload = body.model_dump(mode="python")
    request_payload["trace_id"] = trace_id
    request_hash = hash_payload(request_payload)
    output = OpenAIPlanOutput.model_validate(
        {
            "candidate_plan": {
                "steps": [
                    {
                        "id": "s1",
                        "type": "write_config",
                        "action": "write_config",
                        "target": "web/app",
                        # Dependency on a later step is schema-valid but fails Invariant-C temporal consistency.
                        "inputs": {"path": "app/config.json", "content": "{}", "depends_on": ["s2"]},
                    },
                    {
                        "id": "s2",
                        "type": "build",
                        "action": "build",
                        "target": "web/app",
                        "inputs": {"depends_on": [], "command": None},
                    },
                ],
                "metadata": {"requiresApproval": False, "riskLevel": "low"},
            }
        }
    )
    raw_response = output.model_dump(mode="python")
    candidate_plan_hash = hash_payload(output.candidate_plan.model_dump(mode="python"))
    session.add(
        OpenAIVesselEvent(
            trace_id=trace_id,
            ocgg_identity=body.ocgg_identity,
            intent=body.intent,
            request_hash=request_hash,
            candidate_plan_hash=candidate_plan_hash,
            model=settings.openai_plan_model,
            request_payload=request_payload,
            raw_response=raw_response,
            schema_valid=True,
            outcome="PASS",
            reason_codes=["OPENAI_ADAPTER_FAILURE_TEST_PLAN"],
        )
    )
    await session.commit()
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-Candidate-Plan-Hash"] = candidate_plan_hash
    return output


@router.post("/openai/plan-to-substrate", response_model=AdapterToSubstrateResponse)
async def openai_plan_to_substrate(
    body: OpenAIPlanRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    trace_id = normalize_trace_id(body.trace_id)
    request_payload = body.model_dump(mode="python")
    request_payload["trace_id"] = trace_id
    request_hash = hash_payload(request_payload)
    vessel = OpenAIVesselClient()
    try:
        output, raw_response = await vessel.generate_candidate_plan(body)
        candidate_plan_hash = hash_payload(output.candidate_plan.model_dump(mode="python"))
        session.add(
            OpenAIVesselEvent(
                trace_id=trace_id,
                ocgg_identity=body.ocgg_identity,
                intent=body.intent,
                request_hash=request_hash,
                candidate_plan_hash=candidate_plan_hash,
                model=settings.openai_plan_model,
                request_payload=request_payload,
                raw_response=raw_response,
                schema_valid=True,
                outcome="PASS",
                reason_codes=[],
            )
        )
        substrate_payload = await _adapt_candidate_to_substrate(
            session=session,
            trace_id=trace_id,
            ocgg_identity=body.ocgg_identity,
            intent=body.intent,
            candidate_plan=output.candidate_plan,
            deployment_target=body.deployment_target,
            objective=body.objective,
            context=body.context,
            acceptance_criteria=None,
            constraints=body.constraints,
            approval_reference=body.approval_reference,
            approver_id=body.approver_id,
        )
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Candidate-Plan-Hash"] = candidate_plan_hash
        return substrate_payload
    except OpenAIVesselConfigError as e:
        await _persist_vessel_block(
            session=session,
            trace_id=trace_id,
            body=body,
            request_hash=request_hash,
            reason_codes=e.reason_codes,
            raw_response=e.raw_response,
            code="OPENAI_CONFIG_ERROR",
            status_code=503,
        )
    except OpenAIVesselSchemaError as e:
        await _persist_vessel_block(
            session=session,
            trace_id=trace_id,
            body=body,
            request_hash=request_hash,
            reason_codes=e.reason_codes,
            raw_response=e.raw_response,
            code="OPENAI_SCHEMA_VIOLATION",
            status_code=422,
        )
    except OpenAIVesselUpstreamError as e:
        await _persist_vessel_block(
            session=session,
            trace_id=trace_id,
            body=body,
            request_hash=request_hash,
            reason_codes=e.reason_codes,
            raw_response=e.raw_response,
            code="OPENAI_UPSTREAM_ERROR",
            status_code=502,
        )


@router.post("/adapter/to-substrate", response_model=AdapterToSubstrateResponse)
async def adapter_to_substrate(
    body: AdapterToSubstrateRequest,
    session: AsyncSession = Depends(get_session),
):
    trace_id = normalize_trace_id(body.trace_id)
    vessel_context = await _load_vessel_context(session=session, trace_id=trace_id)
    objective = _first_non_empty(body.objective, vessel_context.get("objective"))
    context = _first_non_empty(body.context, vessel_context.get("context"))
    acceptance_criteria = _first_non_empty_list(body.acceptance_criteria, vessel_context.get("acceptance_criteria"))
    approval_reference = _first_non_empty(body.approval_reference, vessel_context.get("approval_reference"))
    approver_id = _first_non_empty(body.approver_id, vessel_context.get("approver_id"))
    deployment_target = _first_non_empty(body.deployment_target, vessel_context.get("deployment_target"))
    return await _adapt_candidate_to_substrate(
        session=session,
        trace_id=trace_id,
        ocgg_identity=body.ocgg_identity,
        intent=body.intent,
        candidate_plan=body.candidate_plan,
        deployment_target=deployment_target,
        objective=objective,
        context=context,
        acceptance_criteria=acceptance_criteria,
        constraints=body.constraints,
        approval_reference=approval_reference,
        approver_id=approver_id,
    )


async def _adapt_candidate_to_substrate(
    *,
    session: AsyncSession,
    trace_id: str,
    ocgg_identity: str,
    intent: str,
    candidate_plan: CandidatePlan,
    deployment_target: str | None,
    objective: str | None,
    context: str | None,
    acceptance_criteria: list[str] | None,
    constraints: dict[str, Any] | None,
    approval_reference: str | None,
    approver_id: str | None,
) -> AdapterToSubstrateResponse:
    candidate_payload = candidate_plan.model_dump(mode="python")
    candidate_plan_hash = hash_payload(candidate_payload)
    shared = build_shared_governable_state_from_adapter_candidate(
        trace_id=trace_id,
        ocgg_identity=ocgg_identity,
        intent=intent,
        candidate_plan=candidate_plan,
        deployment_target=deployment_target,
        objective=objective,
        context=context,
        acceptance_criteria=acceptance_criteria,
        constraints=constraints,
        approval_reference=approval_reference,
        approver_id=approver_id,
    )
    frame = run_evaluation_frame(shared)
    frame_response = to_evaluation_frame_response(
        frame,
        governance_reached=False,
        dispatch_reached=False,
    )
    ic_res = frame.invariant_c_result
    session.add(
        InvariantCDecisionRecord(
            trace_id=trace_id,
            ocgg_identity=ocgg_identity,
            intent=intent,
            candidate_plan_hash=candidate_plan_hash,
            decision=ic_res.decision,
            reason_codes=list(ic_res.reason_codes),
            check_results=ic_res.to_persisted_checks(),
            decision_version=ic_res.decision_version,
        )
    )
    if frame.frame_status != FrameStatus.PASS:
        session.add(
            SubstrateAdapterEvent(
                trace_id=trace_id,
                ocgg_identity=ocgg_identity,
                intent=intent,
                candidate_plan_hash=candidate_plan_hash,
                integration_plan_hash=None,
                outcome="BLOCK",
                reason_codes=list(frame.reason_codes),
                payload={
                    "frame_status": frame.frame_status.value,
                    "shared_state_hash": frame.shared_state_hash,
                    "uato_decision": frame.uato_result.decision,
                    "invariant_e_decision": frame.invariant_e_result.decision,
                },
            )
        )
        await session.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EVALUATION_FRAME_BLOCK",
                "reason_codes": list(frame.reason_codes),
                "trace_id": trace_id,
                "frame_status": frame.frame_status.value,
                "evaluation_frame": jsonable_encoder(frame_response),
            },
        )

    # Candidate metadata approval flag: enforced here as structural pre-check only. Production deploy and
    # SoD are owned by GateEngine on POST /task (see app/gate/engine.py). Reason code is distinct from gate.
    if candidate_plan.metadata.requiresApproval and not (approval_reference or approver_id):
        reason_codes = ["ADAPTER_METADATA_REQUIRES_APPROVAL"]
        from app.services.approvals_service import create_adapter_approval_request

        checkpoint: dict[str, Any] = {
            "v": 1,
            "kind": "adapter_resume",
            "trace_id": trace_id,
            "ocgg_identity": ocgg_identity,
            "intent": intent,
            "candidate_plan": candidate_plan.model_dump(mode="python"),
            "deployment_target": deployment_target,
            "objective": objective,
            "context": context,
            "acceptance_criteria": acceptance_criteria,
            "constraints": constraints,
        }
        ar = await create_adapter_approval_request(
            session,
            trace_id=trace_id,
            reason_code="ADAPTER_METADATA_REQUIRES_APPROVAL",
            resume_from_stage="ADAPTER_SUBSTRATE",
            approval_scope="adapter_metadata",
            checkpoint=checkpoint,
        )
        session.add(
            SubstrateAdapterEvent(
                trace_id=trace_id,
                ocgg_identity=ocgg_identity,
                intent=intent,
                candidate_plan_hash=candidate_plan_hash,
                integration_plan_hash=None,
                outcome="BLOCK",
                reason_codes=reason_codes,
                payload={"approval_request_id": str(ar.id), "event_type": "approval_requested"},
            )
        )
        await session.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "METADATA_APPROVAL_REQUIRED",
                "reason_codes": reason_codes,
                "trace_id": trace_id,
                "approval_request_id": str(ar.id),
                "approval_status": "PENDING",
                "source_layer": "ADAPTER",
                "resume_available": True,
                "evaluation_frame": jsonable_encoder(frame_response),
            },
        )

    operations = list(shared.spec_for_gate.get("operations") or [])
    domain = shared.domain
    rollback: dict[str, Any] = {}
    governance_plan_hash = shared.plan_hash
    substrate_envelope_hash = _substrate_envelope_hash(
        {
            "plan_version": "1.0",
            "identity": ocgg_identity,
            "domain": domain,
            "operations": operations,
            "rollback": rollback,
        }
    )
    response = AdapterToSubstrateResponse(
        identity=ocgg_identity,
        ocgg_identity=ocgg_identity,
        domain=domain,
        deployment_target=deployment_target,
        operations=operations,
        rollback=rollback,
        governance_plan_hash=governance_plan_hash,
        substrate_envelope_hash=substrate_envelope_hash,
        integration_plan_hash=governance_plan_hash,
        plan_hash=substrate_envelope_hash,
        goal=objective,
        context=context,
        acceptance_criteria=acceptance_criteria,
        approval_reference=approval_reference,
        approver_id=approver_id,
        uato=_derive_uato_hints_from_candidate(candidate_plan),
        trace_id=trace_id,
        evaluation_frame=frame_response,
    )
    session.add(
        SubstrateAdapterEvent(
            trace_id=trace_id,
            ocgg_identity=ocgg_identity,
            intent=intent,
            candidate_plan_hash=candidate_plan_hash,
            integration_plan_hash=governance_plan_hash,
            outcome="PASS",
            reason_codes=[],
            payload=response.model_dump(mode="python"),
        )
    )
    await session.commit()
    return response


async def resume_adapter_from_approval(
    session: AsyncSession,
    approval: Any,
    *,
    actor: str,
) -> AdapterToSubstrateResponse:
    """Backend-controlled resume: rerun adapter substrate conversion after approval (Invariant-C + structural checks)."""
    cp = approval.checkpoint_payload_json
    candidate_plan = CandidatePlan.model_validate(cp["candidate_plan"])
    return await _adapt_candidate_to_substrate(
        session=session,
        trace_id=cp["trace_id"],
        ocgg_identity=cp["ocgg_identity"],
        intent=cp["intent"],
        candidate_plan=candidate_plan,
        deployment_target=cp.get("deployment_target"),
        objective=cp.get("objective"),
        context=cp.get("context"),
        acceptance_criteria=cp.get("acceptance_criteria"),
        constraints=cp.get("constraints"),
        approval_reference=str(approval.id),
        approver_id=approval.approved_by or actor,
    )


async def _persist_vessel_block(
    *,
    session: AsyncSession,
    trace_id: str,
    body: OpenAIPlanRequest,
    request_hash: str,
    reason_codes: list[str],
    raw_response: dict,
    code: str,
    status_code: int,
):
    request_payload = body.model_dump(mode="python")
    request_payload["trace_id"] = trace_id
    session.add(
        OpenAIVesselEvent(
            trace_id=trace_id,
            ocgg_identity=body.ocgg_identity,
            intent=body.intent,
            request_hash=request_hash,
            candidate_plan_hash=None,
            model=settings.openai_plan_model,
            request_payload=request_payload,
            raw_response=raw_response or {},
            schema_valid=False,
            outcome="BLOCK",
            reason_codes=reason_codes,
        )
    )
    await session.commit()
    detail: dict[str, Any] = {"code": code, "reason_codes": reason_codes, "trace_id": trace_id}
    if code == "OPENAI_UPSTREAM_ERROR":
        summary = summarize_openai_upstream_error(raw_response if isinstance(raw_response, dict) else {})
        if summary:
            detail["upstream"] = summary
    raise HTTPException(status_code=status_code, detail=detail)


async def _load_vessel_context(*, session: AsyncSession, trace_id: str) -> dict[str, Any]:
    result = await session.execute(
        select(OpenAIVesselEvent)
        .where(OpenAIVesselEvent.trace_id == trace_id)
        .order_by(OpenAIVesselEvent.created_at.desc())
        .limit(1)
    )
    row = result.scalars().first()
    if not row or not isinstance(row.request_payload, dict):
        return {}
    payload = dict(row.request_payload)
    raw_constraints = payload.get("constraints")
    if isinstance(raw_constraints, dict):
        if payload.get("acceptance_criteria") is None and isinstance(raw_constraints.get("acceptance_criteria"), list):
            payload["acceptance_criteria"] = raw_constraints.get("acceptance_criteria")
    return payload


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            s = value.strip()
            if s:
                return s
    return None


def _first_non_empty_list(*values: Any) -> list[str] | None:
    for value in values:
        if isinstance(value, list):
            items = [str(x).strip() for x in value if str(x).strip()]
            if items:
                return items
    return None


def _substrate_envelope_hash(value: dict[str, Any]) -> str:
    def _normalize_numbers(data: Any) -> Any:
        if isinstance(data, dict):
            return {k: _normalize_numbers(v) for k, v in data.items()}
        if isinstance(data, list):
            return [_normalize_numbers(x) for x in data]
        if isinstance(data, float) and math.isfinite(data) and data == int(data):
            return int(data)
        return data

    canonical = json.dumps(
        _normalize_numbers(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
