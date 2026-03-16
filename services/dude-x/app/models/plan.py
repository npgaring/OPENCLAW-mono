"""Plan output models."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlanOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str
    type: str
    target: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    addon: str | None = None


class PlanPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "plan_version": "1.0",
                    "identity": "W-OCGG",
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
                        {
                            "op_id": "op-003",
                            "type": "deploy",
                            "target": "web/app",
                            "inputs": {"provider": "vercel", "project": "marketing-site"},
                        },
                    ],
                    "rollback": {"strategy": "revert_commit", "target": "web/app"},
                    "plan_hash": "plan_8e7c8b20b2",
                }
            ]
        },
    )

    plan_version: Literal["1.0"] = "1.0"
    identity: Literal["W-OCGG", "R-OCGG"]
    domain: Literal["web", "recruiting"]
    operations: list[PlanOperation]
    rollback: dict[str, Any] = Field(default_factory=dict)
    plan_hash: str
