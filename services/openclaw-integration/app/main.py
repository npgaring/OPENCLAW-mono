"""FastAPI app: startup, routes, OpenAPI override."""
import sys
from pathlib import Path

# Vercel runs from repo root; entrypoint is services/openclaw-integration/app/main.py
_svc_root = Path(__file__).resolve().parent.parent
if str(_svc_root) not in sys.path:
    sys.path.insert(0, str(_svc_root))

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi

from app.api import approvals, audit, evaluation_frame, gate, health, public, status, task
from app.api import openai_flow
from app.core.config import settings
from app.core.auth import require_integration_auth
from app.db.init_db import init_db
from app.logging.logger import configure_logging

logger = logging.getLogger(__name__)

OPENCLAW_ROOT_PATH = os.getenv("OPENCLAW_INTEGRATION_ROOT_PATH")
if not OPENCLAW_ROOT_PATH and os.getenv("VERCEL") == "1":
    OPENCLAW_ROOT_PATH = "/openclaw-integration"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run on every cold start (Vercel serverless). Migrations also run on first request if this fails."""
    configure_logging()
    try:
        await init_db()
    except Exception as e:
        logger.warning("Startup init_db failed (migrations will run on first request): %s", e)
    # H4: Recover tasks orphaned by gate restart (token consumed, no execution_id)
    try:
        from app.db.session import get_sessionmaker
        from app.services.orphan_recovery import recover_orphaned_tasks
        async with get_sessionmaker()() as session:
            n = await recover_orphaned_tasks(session)
            if n:
                logger.info("Orphan recovery: marked %d task(s) as error", n)
    except Exception as e:
        logger.warning("Orphan recovery failed (non-fatal): %s", e)
    yield


class PrefixMiddleware:
    def __init__(self, app, prefix: str):
        self.app = app
        self.prefix = prefix.rstrip("/") if prefix != "/" else ""

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and self.prefix:
            path = scope.get("path", "")
            if path.startswith(self.prefix):
                scope = dict(scope)
                scope["root_path"] = self.prefix
                scope["path"] = path[len(self.prefix):] or "/"
        await self.app(scope, receive, send)


app = FastAPI(
    title="OpenClaw Integration",
    description=(
        "Governance-gated layer between callers and runtime executor. "
        "POST /gate/evaluate may persist task + approval_requests when blocking with PROD_DEPLOY_NO_APPROVAL "
        "(see operation docs on that path)."
    ),
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    root_path=OPENCLAW_ROOT_PATH or "",
    lifespan=lifespan,
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    public_base = os.getenv("OPENCLAW_PUBLIC_BASE_URL")
    if public_base:
        schema["servers"] = [{"url": f"{public_base}{OPENCLAW_ROOT_PATH or ''}", "description": "Production"}]
    elif os.getenv("VERCEL") == "1" and OPENCLAW_ROOT_PATH:
        schema["servers"] = [{"url": f"https://openclaw-mono.vercel.app{OPENCLAW_ROOT_PATH}", "description": "Production"}]
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["bearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "Bearer",
    }
    for path in schema.get("paths", {}):
        if path in ("/", "/health", "/privacy", "/openapi.json", "/docs", "/redoc"):
            continue
        schema["paths"][path] = dict(schema["paths"][path])
        for method in schema["paths"][path]:
            if method in ("get", "post", "put", "delete", "patch"):
                schema["paths"][path][method]["security"] = [{"bearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
if OPENCLAW_ROOT_PATH:
    app.add_middleware(PrefixMiddleware, prefix=OPENCLAW_ROOT_PATH)

# Protected routes (Bearer)
app.include_router(task.router, tags=["task"], dependencies=[Depends(require_integration_auth)])
app.include_router(approvals.router, tags=["approvals"], dependencies=[Depends(require_integration_auth)])
app.include_router(audit.router, tags=["audit"], dependencies=[Depends(require_integration_auth)])
app.include_router(
    evaluation_frame.router,
    prefix="/evaluation-frame",
    tags=["evaluation-frame"],
    dependencies=[Depends(require_integration_auth)],
)
app.include_router(gate.router, prefix="/gate", tags=["gate"], dependencies=[Depends(require_integration_auth)])
app.include_router(status.router, tags=["status"], dependencies=[Depends(require_integration_auth)])
if settings.openai_flow_enabled:
    app.include_router(openai_flow.router, tags=["openai-flow"], dependencies=[Depends(require_integration_auth)])
# Public
app.include_router(health.router, tags=["health"])
app.include_router(public.router, tags=["public"])
