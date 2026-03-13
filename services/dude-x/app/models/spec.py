"""Spec input and stored models."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Signature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["human", "human_signed"]
    signed_at: str
    hash: str = Field(..., min_length=1)


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    environment: Literal["preview", "production"]


class OperationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str
    type: str  # create_file, write_config, build, deploy, test, rollback_prep, addon_execute
    target: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    addon: str | None = None


class Decisions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[OperationSpec]
    domain: str | None = None


class SpecIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_version: Literal["1.0"] = "1.0"
    identity: Literal["W-OCGG", "R-OCGG"]
    intent: Literal["web-build", "web-maintenance", "recruiting-update"]
    target: Target
    decisions: Decisions
    constraints: dict[str, Any] = Field(default_factory=dict)
    signature: Signature


class SpecStored(BaseModel):
    """Response model for stored spec (e.g. get spec by hash)."""

    model_config = ConfigDict(extra="forbid")

    spec_hash: str
    payload: dict[str, Any]
    received_at: str
