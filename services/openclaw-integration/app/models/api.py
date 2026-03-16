"""API request/response Pydantic models."""
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: UUID | None = None
    status: str | None = None
    event_type: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class AuditAck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"


class GateEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    ocgg_identity: str | None = None
    plan_hash: str | None = None
    operations: list[Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class VerifyTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_token: str
    tenant_context: str


class VerifyTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str | None = None
    token_verified: bool
    tenant_context: str
    token_tenant: str | None = None
    result: str  # PASS | BLOCK
    reason: str | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    env: str = "development"


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
