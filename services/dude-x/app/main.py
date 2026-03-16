"""FastAPI app: routers, exception handlers, startup."""
import sys
from pathlib import Path

# Vercel runs from repo root; entrypoint is services/dude-x/app/main.py
_svc_root = Path(__file__).resolve().parent.parent
if str(_svc_root) not in sys.path:
    sys.path.insert(0, str(_svc_root))

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi

from app.api import compile as compile_api, gate, health, plans, privacy, root
from app.core.auth import verify_api_key
from app.core.errors import DUDEXError, ErrorCode, ErrorResponse
from app.db.init_db import init_db
from app.logging.logger import configure_logging

DUDEX_ROOT_PATH = os.getenv("DUDEX_ROOT_PATH")
if not DUDEX_ROOT_PATH and os.getenv("VERCEL") == "1":
    DUDEX_ROOT_PATH = "/dude-x"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run on every cold start (Vercel serverless)."""
    configure_logging()
    await init_db()
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
    title="DUDE-X",
    description="Compile-only deterministic planner",
    version="1.0.0",
    redoc_url="/redoc",
    docs_url="/docs",
    root_path=DUDEX_ROOT_PATH or "",
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
    public_base = os.getenv("DUDEX_PUBLIC_BASE_URL")
    if public_base:
        production_url = f"{public_base}{DUDEX_ROOT_PATH or ''}"
    elif os.getenv("VERCEL") == "1" and DUDEX_ROOT_PATH:
        production_url = f"https://openclaw-mono.vercel.app{DUDEX_ROOT_PATH}"
    else:
        production_url = f"https://openclaw-mono.vercel.app{DUDEX_ROOT_PATH or ''}"
    schema["servers"] = [{"url": production_url, "description": "Production server"}]
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["apiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    for path in schema.get("paths", {}):
        if path in ("/", "/health", "/privacy", "/openapi.json", "/docs", "/redoc"):
            continue
        schema["paths"][path] = dict(schema["paths"][path])
        for method in schema["paths"][path]:
            if method in ("get", "post", "put", "delete", "patch"):
                schema["paths"][path][method]["security"] = [{"apiKeyAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
if DUDEX_ROOT_PATH:
    app.add_middleware(PrefixMiddleware, prefix=DUDEX_ROOT_PATH)


@app.exception_handler(DUDEXError)
async def dudex_error_handler(request: Request, exc: DUDEXError):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(code=exc.code, message=exc.message, details=exc.details).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            code=ErrorCode.INVALID_SPEC,
            message="Spec validation failed",
            details={"errors": exc.errors()},
        ).model_dump(),
    )


# Routers with API key (order as in overview)
app.include_router(compile_api.router, dependencies=[Depends(verify_api_key)])
app.include_router(plans.router, dependencies=[Depends(verify_api_key)])
app.include_router(gate.router, dependencies=[Depends(verify_api_key)])
# Public
app.include_router(health.router)
app.include_router(root.router)
app.include_router(privacy.router)
