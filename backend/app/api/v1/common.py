"""Shared admin response helpers."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.persistence.models import AdminUser


def ok(data, status_code: int = 200) -> JSONResponse:
    return JSONResponse({"success": True, "data": data}, status_code=status_code)


def fail(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"success": False, "error": {"code": code, "message": message}}, status_code=status_code)


def user_view(user: AdminUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "mfa_enabled": user.mfa_enabled,
    }


def client_host(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host
