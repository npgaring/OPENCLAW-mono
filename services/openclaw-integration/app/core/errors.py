"""HTTP error helpers and error codes."""
from typing import Any

from fastapi import HTTPException


class ErrorCodes:
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    OPENCLAW_UNREACHABLE = "OPENCLAW_UNREACHABLE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"


def _detail(code: str, message: str) -> dict[str, Any]:
    return {"detail": {"code": code, "message": message}}


def unauthorized() -> dict[str, Any]:
    return {"status_code": 401, "detail": _detail(ErrorCodes.UNAUTHORIZED, "Unauthorized")}


def invalid_payload(message: str = "Invalid payload") -> dict[str, Any]:
    return {"status_code": 422, "detail": _detail(ErrorCodes.INVALID_PAYLOAD, message)}


def task_not_found() -> dict[str, Any]:
    return {"status_code": 404, "detail": _detail(ErrorCodes.TASK_NOT_FOUND, "Task not found")}


def openclaw_unreachable(message: str = "OpenClaw unreachable") -> dict[str, Any]:
    return {"status_code": 502, "detail": _detail(ErrorCodes.OPENCLAW_UNREACHABLE, message)}


def execution_failed(message: str = "Execution failed") -> dict[str, Any]:
    return {"status_code": 502, "detail": _detail(ErrorCodes.EXECUTION_FAILED, message)}
