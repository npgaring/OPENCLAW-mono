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
    model_config = ConfigDict(extra="forbid")

    plan_version: Literal["1.0"] = "1.0"
    identity: Literal["W-OCGG", "R-OCGG"]
    domain: Literal["web", "recruiting"]
    operations: list[PlanOperation]
    rollback: dict[str, Any] = Field(default_factory=dict)
    plan_hash: str
