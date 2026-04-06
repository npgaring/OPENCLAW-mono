"""Service for recording and querying deployment results."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.deployment import DeploymentRecord

logger = logging.getLogger(__name__)


async def record_deployment(
    session: AsyncSession,
    *,
    result: dict[str, Any],
    task_id: str,
    trace_id: str,
    build_sot_hash: Optional[str] = None,
    execution_plan_hash: Optional[str] = None,
    project_name: Optional[str] = None,
) -> DeploymentRecord:
    """Parse the deterministic executor result and persist a DeploymentRecord."""
    repo_url = _str(result.get("repository_url"))
    deployment_url = _str(result.get("deployment_url"))
    preview_url = _str(result.get("preview_url"))
    commit_sha = _str(result.get("repo_commit_sha"))
    deployment_id_val = _str(result.get("deployment_id"))
    provider_ids = result.get("provider_ids") if isinstance(result.get("provider_ids"), dict) else {}

    github_owner = ""
    github_repo_name = ""
    github_branch = ""
    if repo_url:
        parts = repo_url.rstrip("/").split("/")
        if len(parts) >= 2:
            github_repo_name = parts[-1]
            github_owner = parts[-2]

    artifacts = result.get("artifacts", [])
    if isinstance(artifacts, list):
        for art in artifacts:
            if isinstance(art, dict) and art.get("type") == "repository" and not repo_url:
                repo_url = _str(art.get("path"))

    status = "success" if result.get("status") == "success" else (result.get("status") or "unknown")

    record = DeploymentRecord(
        id=str(uuid.uuid4()),
        trace_id=trace_id,
        task_id=task_id,
        build_sot_hash=build_sot_hash,
        execution_plan_hash=execution_plan_hash,
        project_name=project_name or github_repo_name or "unknown",
        github_owner=github_owner,
        github_repo_name=github_repo_name,
        github_repo_url=repo_url,
        github_branch=github_branch,
        github_commit_sha=commit_sha,
        vercel_project_id=_str(provider_ids.get("vercel_project_id")),
        vercel_project_name=project_name or github_repo_name,
        vercel_deployment_id=deployment_id_val,
        vercel_deployment_url=deployment_url,
        vercel_preview_url=preview_url,
        vercel_deploy_target="preview" if preview_url else "production",
        status=status,
        error_message=_str(result.get("message")) if status != "success" else None,
        build_logs=_str(result.get("build_logs")) or None,
        fix_attempts=int(result.get("fix_attempts") or 0),
        vercel_ready_state=_str(result.get("vercel_ready_state")) or None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(record)
    logger.info(
        "deployment_tracker.recorded deployment_id=%s task_id=%s repo=%s deploy_url=%s",
        record.id, task_id, repo_url, deployment_url,
    )
    return record


async def get_deployments_for_trace(
    session: AsyncSession,
    trace_id: str,
) -> list[DeploymentRecord]:
    stmt = (
        select(DeploymentRecord)
        .where(DeploymentRecord.trace_id == trace_id)
        .order_by(DeploymentRecord.created_at.desc())
    )
    results = await session.execute(stmt)
    return list(results.scalars().all())


async def get_deployment_for_task(
    session: AsyncSession,
    task_id: str,
) -> Optional[DeploymentRecord]:
    stmt = (
        select(DeploymentRecord)
        .where(DeploymentRecord.task_id == task_id)
        .order_by(DeploymentRecord.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_deployment_by_id(
    session: AsyncSession,
    deployment_id: str,
) -> Optional[DeploymentRecord]:
    return await session.get(DeploymentRecord, deployment_id)


async def list_all_deployments(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[DeploymentRecord]:
    """Paginated listing of all deployments, newest first."""
    stmt = (
        select(DeploymentRecord)
        .order_by(DeploymentRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    results = await session.execute(stmt)
    return list(results.scalars().all())


async def update_deployment_fields(
    session: AsyncSession,
    deployment_id: str,
    **fields: Any,
) -> Optional[DeploymentRecord]:
    """Update specific fields on a deployment record."""
    rec = await session.get(DeploymentRecord, deployment_id)
    if rec is None:
        return None
    for k, v in fields.items():
        if hasattr(rec, k):
            setattr(rec, k, v)
    rec.updated_at = datetime.now(timezone.utc)
    session.add(rec)
    return rec


def _str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()
