"""FastAPI app: routers, exception handlers, startup."""
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi

from app.api import compile as compile_api, gate, health, plans, privacy, root
from app.core.auth import verify_api_key
from app.core.errors import DUDEXError, ErrorCode, ErrorResponse
from app.db.init_db import init_db
from app.logging.logger import configure_logging

app = FastAPI(
    title="DUDE-X",
    description="Compile-only deterministic planner",
    version="1.0.0",
    redoc_url=None,
    docs_url="/docs",
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
    schema["servers"] = [{"url": "https://dude-x-dusky.vercel.app", "description": "Production server"}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


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
app.include_router(health.router, dependencies=[Depends(verify_api_key)])
app.include_router(root.router)
app.include_router(privacy.router)
