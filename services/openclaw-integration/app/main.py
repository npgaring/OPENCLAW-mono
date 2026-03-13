"""FastAPI app: startup, routes, OpenAPI override."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi

from app.api import audit, gate, health, public, status, task
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
    description="Governance-gated layer between callers and runtime executor",
    version="1.0.0",
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
app.include_router(audit.router, tags=["audit"], dependencies=[Depends(require_integration_auth)])
app.include_router(gate.router, prefix="/gate", tags=["gate"], dependencies=[Depends(require_integration_auth)])
app.include_router(status.router, tags=["status"], dependencies=[Depends(require_integration_auth)])
# Public
app.include_router(health.router, tags=["health"])
app.include_router(public.router, tags=["public"])
</think>
Fixing main: we included routers twice. Applying a single include with dependencies:
<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>
StrReplace
