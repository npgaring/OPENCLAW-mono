"""POST /compile: parse body, validate, build plan, persist, return plan."""
import logging

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.compiler.invariants import validate_invariants
from app.compiler.planner import build_plan
from app.compiler.validator import validate_spec
from app.core.errors import DUDEXError, ErrorCode
from app.core.hashing import hash_payload
from app.db.session import get_session
from app.models import CompileEvent, PlanRecord, PlanPayload, SpecIn, SpecRecord

logger = logging.getLogger(__name__)

router = APIRouter()


def parse_compile_body(body: dict) -> SpecIn:
    """Handle raw JSON: unwrap GPT Action params if present, ensure constraints key."""
    if "params" in body and isinstance(body["params"], dict):
        params = dict(body["params"])
        if "constraints" not in params:
            params["constraints"] = body.get("constraints", {})
        return SpecIn.model_validate(params)
    if "constraints" not in body:
        body = {**body, "constraints": {}}
    return SpecIn.model_validate(body)


@router.post("/compile", response_model=PlanPayload)
async def compile_spec(
    body: dict = Body(
        ...,
        examples={
            "compile_request": {
                "summary": "Compile spec",
                "value": {
                    "spec_version": "1.0",
                    "identity": "W-OCGG",
                    "intent": "web-build",
                    "target": {"resource_id": "site:marketing", "environment": "production"},
                    "decisions": {
                        "domain": "web",
                        "operations": [
                            {
                                "op_id": "op-001",
                                "type": "write_config",
                                "target": "web/app",
                                "inputs": {
                                    "path": "app/config.json",
                                    "content": "{\"featureFlags\":{\"newHomepage\":true}}",
                                },
                            },
                            {
                                "op_id": "op-002",
                                "type": "build",
                                "target": "web/app",
                                "inputs": {"command": "npm run build"},
                            },
                        ],
                    },
                    "constraints": {"no_external_network": True, "max_runtime_seconds": 900},
                    "signature": {
                        "type": "human_signed",
                        "signed_at": "2026-03-17T10:12:00Z",
                        "hash": "sig_9f3d2b5a1c",
                    },
                },
            }
        },
    ),
    session: AsyncSession = Depends(get_session),
):
    """Compile spec to plan; persist spec, plan, and compile event."""
    if not isinstance(body, dict):
        raise DUDEXError(ErrorCode.INVALID_SPEC, "Body must be a JSON object", details={})
    spec = parse_compile_body(body)
    spec_payload = spec.model_dump(mode="python")
    spec_hash = hash_payload(spec_payload)

    try:
        validate_spec(spec)
        plan = build_plan(spec)
        validate_invariants(spec, plan)

        existing_spec = await session.get(SpecRecord, spec_hash)
        if existing_spec is None:
            session.add(
                SpecRecord(
                    spec_hash=spec_hash,
                    identity=spec.identity,
                    payload=spec_payload,
                )
            )
        existing_plan = await session.get(PlanRecord, plan.plan_hash)
        if existing_plan is None:
            session.add(
                PlanRecord(
                    plan_hash=plan.plan_hash,
                    identity=plan.identity,
                    payload=plan.model_dump(),
                    domain=plan.domain,
                )
            )
        session.add(
            CompileEvent(
                event_type="COMPILE_OK",
                spec_hash=spec_hash,
                plan_hash=plan.plan_hash,
                metadata_={"intent": spec.intent},
            )
        )
        await session.commit()
        return plan
    except DUDEXError as e:
        session.add(
            CompileEvent(
                event_type="COMPILE_FAILED",
                spec_hash=spec_hash,
                plan_hash=None,
                metadata_={"code": e.code.value, "message": e.message},
            )
        )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
        raise
    except Exception as e:
        logger.exception("Compile failed")
        session.add(
            CompileEvent(
                event_type="COMPILE_FAILED",
                spec_hash=spec_hash,
                plan_hash=None,
                metadata_={"code": ErrorCode.INVALID_SPEC.value, "message": str(e)},
            )
        )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
        raise
