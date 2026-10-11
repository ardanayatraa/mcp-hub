"""Reference connected application. It owns its records and decides who may read them.

Implements the connector contract: authenticated health and manifest, a tenant- and
user-scoped project list, an activity feed, and an optional create request that only
returns a proposal (the user confirms it in this app, never through the AI).
"""

import hashlib
import hmac
import json
import os
import re
import secrets
from base64 import urlsafe_b64decode
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

API_KEY = os.environ.get("YOUR_APP_API_KEY", "dev-your-app-key")
DELEGATION_SECRET = os.environ.get("YOUR_APP_DELEGATION_SECRET", "dev-delegation-secret")
APP_KEY = "your_app"
SAFE_FIELDS = ["ref", "name", "status", "created_at", "budget"]


def _project(ref, name, status, created, budget, tenant, email, phone):
    return {"ref": ref, "name": name, "status": status, "created_at": created, "budget": budget,
            "tenant_id": tenant, "owner_email": email, "owner_phone": phone}


# Blocked owner contact fields stay in this application; the Hub never receives them.
PROJECTS = [
    _project("prj_125", "Website Villa", "active", "2026-10-01T09:00:00+08:00", 12500.0, "tenant_a", "canary.a@example.com", "+628111111111"),
    _project("prj_200", "Harbor Office", "completed", "2026-09-01T09:00:00+08:00", 48000.0, "tenant_a", "canary.hidden@example.com", "+628122222222"),
    _project("prj_210", "Beach Resort", "active", "2026-09-14T10:30:00+08:00", 91000.0, "tenant_a", "owner.c@example.com", "+628155555551"),
    _project("prj_215", "City Clinic", "pending", "2026-09-20T08:15:00+08:00", 30500.0, "tenant_a", "owner.d@example.com", "+628155555552"),
    _project("prj_220", "Coffee Bar", "active", "2026-10-03T13:00:00+08:00", 8600.0, "tenant_a", "owner.e@example.com", "+628155555553"),
    _project("prj_230", "Warehouse North", "completed", "2026-08-11T09:45:00+08:00", 152000.0, "tenant_a", "owner.f@example.com", "+628155555554"),
    _project("prj_240", "School Library", "pending", "2026-10-06T11:20:00+08:00", 22000.0, "tenant_a", "owner.g@example.com", "+628155555555"),
    _project("prj_250", "Sunset Villa", "active", "2026-10-08T15:40:00+08:00", 17750.0, "tenant_a", "owner.h@example.com", "+628155555556"),
    _project("prj_900", "Other Tenant", "active", "2026-10-02T09:00:00+08:00", 99999.0, "tenant_b", "canary.b@example.com", "+628133333333"),
]
USERS = {
    # project_refs None means every project in the user's tenant.
    "user_1": {"active": True, "tenant_id": "tenant_a", "permissions": {"projects.read", "projects.create", "activity.read"},
               "project_refs": None, "activity_refs": {"user_1", "user_2", "user_3", "user_4"}},
    "user_2": {"active": True, "tenant_id": "tenant_a", "permissions": {"projects.read"}, "project_refs": {"prj_200"}},
    "user_b": {"active": True, "tenant_id": "tenant_b", "permissions": {"projects.read"}, "project_refs": {"prj_900"}},
    "revoked_user": {"active": False, "tenant_id": "tenant_a", "permissions": set(), "project_refs": set()},
}
try:
    from reference.your_app.contract import MANIFEST
except ModuleNotFoundError:
    from contract import MANIFEST


def _b64decode(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _read_assertion(token: str, audience: str) -> dict | None:
    try:
        raw_part, digest_part = token.split(".", 1)
        raw = _b64decode(raw_part)
        expected = hmac.new(DELEGATION_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(digest_part)):
            return None
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("app_key") != APP_KEY or type(payload.get("exp")) is not int:
        return None
    now = int(datetime.now(timezone.utc).timestamp())
    if payload.get("aud") != audience or not now < payload["exp"] <= now + 150:
        return None
    if not isinstance(payload.get("tenant_id"), str) or not isinstance(payload.get("user_ref"), str) or not payload["tenant_id"] or not payload["user_ref"]:
        return None
    return payload


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"success": False, "error": {"code": code, "message": message}}, status_code=status)


def _guard(request: Request, x_api_key: str | None, x_hub_assertion: str | None, permission: str):
    """The source re-checks the service key, the signed user and the user's own permission."""

    if x_api_key != API_KEY:
        return None, _error(401, "UNAUTHENTICATED", "Authentication is required")
    audience = str(request.base_url).rstrip("/")
    configured = os.environ.get("ASSERTION_AUDIENCE")
    payload = _read_assertion(x_hub_assertion or "", configured or audience)
    if payload is None and configured:
        payload = _read_assertion(x_hub_assertion or "", audience)
    if payload is None:
        return None, _error(403, "PERMISSION_DENIED", "Operation is not permitted")
    user = USERS.get(payload["user_ref"])
    if not user or not user["active"] or user["tenant_id"] != payload["tenant_id"] or permission not in user["permissions"]:
        return None, _error(403, "PERMISSION_DENIED", "Operation is not permitted")
    return {**payload, "user": user}, None


app = FastAPI(title="Your App")


@app.get("/api/ai/v1/health")
def health(x_api_key: str | None = Header(default=None)):
    if x_api_key != API_KEY:
        return _error(401, "UNAUTHENTICATED", "Authentication is required")
    return {"status": "ok"}


@app.get("/api/ai/v1/capabilities")
def capabilities(x_api_key: str | None = Header(default=None)):
    if x_api_key != API_KEY:
        return _error(401, "UNAUTHENTICATED", "Authentication is required")
    return MANIFEST


@app.get("/api/v1/projects")
def projects(
    request: Request,
    status: Literal["active", "pending", "completed"] | None = None,
    limit: int = Query(default=50, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=64),
    x_api_key: str | None = Header(default=None),
    x_hub_assertion: str | None = Header(default=None),
):
    payload, error = _guard(request, x_api_key, x_hub_assertion, "projects.read")
    if error is not None:
        return error
    allowed = payload["user"]["project_refs"]
    rows = [row for row in PROJECTS if row["tenant_id"] == payload["tenant_id"] and (allowed is None or row["ref"] in allowed)]
    if status:
        rows = [row for row in rows if row["status"] == status]
    if cursor is not None and not re.fullmatch(r"page_\d{1,6}", cursor):
        return _error(422, "VALIDATION_FAILED", "Invalid cursor")
    offset = int(cursor[5:]) if cursor else 0
    page = rows[offset:offset + limit]
    has_more = offset + limit < len(rows)
    minimized = [{field: row[field] for field in SAFE_FIELDS} | {"tenant_id": row["tenant_id"]} for row in page]
    return {
        "success": True,
        "request_id": "req_your_app",
        "module": "projects",
        "schema_version": "1.0",
        "data": minimized,
        "meta": {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "timezone": "Asia/Makassar",
            "scope": "authorized_records",
            "coverage": "partial" if has_more else "complete",
            "total_count": len(rows),
            "has_more": has_more,
            "next_cursor": f"page_{offset + limit}" if has_more else None,
        },
    }


class ProjectProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=120)
    status: Literal["active", "pending"] = "pending"


@app.post("/api/v1/projects")
def propose_project(body: ProjectProposal, request: Request, x_api_key: str | None = Header(default=None),
                    x_hub_assertion: str | None = Header(default=None)):
    """A create request becomes a proposal; the user confirms it in this app's own UI."""

    payload, error = _guard(request, x_api_key, x_hub_assertion, "projects.create")
    if error is not None:
        return error
    return {
        "success": True,
        "data": [{"proposal_ref": "prop_" + secrets.token_hex(6), "summary": f"Create project '{body.name}' ({body.status})",
                  "status": "pending_confirmation", "tenant_id": payload["tenant_id"]}],
        "meta": {"requires_confirmation": True},
    }


@app.get("/api/v1/activity")
def activity(request: Request, x_api_key: str | None = Header(default=None), x_hub_assertion: str | None = Header(default=None)):
    """Last-activity stamps only. No names, emails, or phone numbers."""

    payload, error = _guard(request, x_api_key, x_hub_assertion, "activity.read")
    if error is not None:
        return error
    now = datetime.now(timezone.utc)
    activities = [
        {"user_ref": "user_1", "tenant_id": "tenant_a", "last_active_at": (now - timedelta(days=1)).isoformat(), "status": "active"},
        {"user_ref": "user_2", "tenant_id": "tenant_a", "last_active_at": None, "status": "active"},
        {"user_ref": "user_3", "tenant_id": "tenant_a", "last_active_at": (now - timedelta(days=6)).isoformat(), "status": "active"},
        {"user_ref": "user_4", "tenant_id": "tenant_a", "last_active_at": (now - timedelta(days=12)).isoformat(), "status": "suspended"},
        {"user_ref": "user_b", "tenant_id": "tenant_b", "last_active_at": (now - timedelta(days=5)).isoformat(), "status": "active"},
    ]
    visible = payload["user"].get("activity_refs", set())
    rows = [{"last_active_at": row["last_active_at"], "status": row["status"], "tenant_id": row["tenant_id"]}
            for row in activities if row["tenant_id"] == payload["tenant_id"] and row["user_ref"] in visible]
    return {
        "success": True,
        "data": rows,
        "meta": {"as_of": now.isoformat(), "timezone": "Asia/Makassar", "scope": "authorized_users", "coverage": "complete"},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8081")), access_log=False)
