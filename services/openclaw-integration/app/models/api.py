"""API request/response Pydantic models."""
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: Optional[UUID] = None
    status: Optional[str] = None
    event_type: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class AuditAck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"


class GateEvaluateRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "ocgg_identity": "W-OCGG",
                    "integration_plan_hash": "",
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
                            "type": "deploy",
                            "target": "web/app",
                            "inputs": {"provider": "vercel", "project": "marketing-site"},
                        },
                    ],
                    "deployment_target": "production",
                },
                {
                    "ocgg_identity": "W-OCGG",
                    "integration_plan_hash": "integration_plan_hash_from_dudex",
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
                            "type": "deploy",
                            "target": "web/app",
                            "inputs": {"provider": "vercel", "project": "marketing-site"},
                        },
                    ],
                    "deployment_target": "production",
                },
            ]
        },
    )

    ocgg_identity: Optional[str] = None
    plan_hash: Optional[str] = None
    integration_plan_hash: Optional[str] = None
    operations: Optional[List[Any]] = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)

    @model_validator(mode="before")
    @classmethod
    def _alias_integration_plan_hash(cls, values):
        if isinstance(values, dict):
            if not values.get("plan_hash") and values.get("integration_plan_hash"):
                values["plan_hash"] = values["integration_plan_hash"]
        return values


class VerifyTokenRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "execution_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token_payload.signature",
                    "tenant_context": "W-OCGG",
                }
            ]
        },
    )

    execution_token: str
    tenant_context: str


class VerifyTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: Optional[str] = None
    token_verified: bool
    tenant_context: str
    token_tenant: Optional[str] = None
    result: str  # PASS | BLOCK
    reason: Optional[str] = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    env: str = "development"


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
