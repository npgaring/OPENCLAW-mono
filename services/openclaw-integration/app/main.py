"""FastAPI app: startup, routes, OpenAPI override."""
from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi

from app.api import audit, gate, health, public, status, task
from app.core.auth import require_integration_auth
from app.db.init_db import init_db
from app.logging.logger import configure_logging

app = FastAPI(
    title="OpenClaw Integration",
    description="Governance-gated layer between callers and runtime executor",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.on_event("startup")
async def startup():
    configure_logging()
    await init_db()


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["servers"] = [{"url": "https://openclaw-integration.example.com", "description": "Production"}]
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