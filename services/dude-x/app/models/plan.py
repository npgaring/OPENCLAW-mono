"""Plan output models."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str
    type: str
    target: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    addon: Optional[str] = None


class PlanPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "plan_version": "1.0",
                    "identity": "W-OCGG",
                    "ocgg_identity": "W-OCGG",
                    "domain": "web",
                    "deployment_target": "production",
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
                        {
                            "op_id": "op-003",
                            "type": "deploy",
                            "target": "web/app",
                            "inputs": {"provider": "vercel", "project": "marketing-site"},
                        },
                    ],
                    "rollback": {"strategy": "revert_commit", "target": "web/app"},
                    "plan_hash": "plan_8e7c8b20b2",
                    "integration_plan_hash": "d3766f8069971c10e20eb62ba566d8ac54f35b1f7dbfb4ad38cd0e41dd147761",
                }
            ]
        },
    )

    plan_version: Literal["1.0"] = "1.0"
    identity: Literal["W-OCGG", "R-OCGG"]
    ocgg_identity: Optional[Literal["W-OCGG", "R-OCGG"]] = None
    domain: Literal["web", "recruiting"]
    deployment_target: Optional[str] = None
    operations: list[PlanOperation]
    rollback: dict[str, Any] = Field(default_factory=dict)
    plan_hash: str
    integration_plan_hash: Optional[str] = None
    trace_id: Optional[str] = Field(
        default=None,
        description="Server-generated or echoed correlation id; not part of plan_hash.",
    )

    @model_validator(mode="after")
    def _default_ocgg_identity(self):
        if self.ocgg_identity is None:
            self.ocgg_identity = self.identity
        return self
