"""Audit events store metadata only. Payloads, tokens, and personal data stay out."""

import logging
import re

from sqlalchemy.orm import Session

from app.ids import new_id, new_trace_id, utcnow
from app.persistence.models import AuditEvent

logger = logging.getLogger("hub.audit")


def record_audit(
    db: Session,
    *,
    action: str,
    actor_ref: str,
    result: str,
    trace_id: str | None = None,
    app_key: str | None = None,
    module_key: str | None = None,
    tool_key: str | None = None,
    environment: str | None = None,
    error_code: str | None = None,
    duration_ms: int | None = None,
    retry_count: int = 0,
) -> str:
    trace = trace_id or new_trace_id()
    db.add(
        AuditEvent(
            id=new_id(),
            trace_id=trace,
            action=action,
            actor_ref=actor_ref,
            app_key=app_key,
            module_key=module_key,
            tool_key=tool_key,
            environment=environment,
            result=result,
            error_code=error_code,
            duration_ms=duration_ms,
            retry_count=retry_count,
            created_at=utcnow(),
        )
    )
    logger.info(
        "audit",
        extra={
            "trace_id": trace,
            "action": action,
            "actor_ref": actor_ref,
            "app_key": app_key,
            "tool_key": tool_key,
            "result": result,
            "error_code": error_code,
            "duration_ms": duration_ms,
            "retry_count": retry_count,
        },
    )
    return trace


EVENT_NAME = re.compile(r"[a-z][a-z0-9_]{2,63}")


class SafeJSONFormatter(logging.Formatter):
    def format(self, record):
        import json
        result = {"level": record.levelname, "logger": record.name}
        # The Hub's own event names (purge_expired, gateway_model_error) are kept; free-text messages,
        # which libraries may fill with request data, are not.
        if isinstance(record.msg, str) and EVENT_NAME.fullmatch(record.msg):
            result["event"] = record.msg
        # uvicorn's access line: (client, method, path, http version, status). The client address and
        # the query string (which may hold personal data or tokens) are left out.
        if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
            _client, method, path, _version, status = record.args
            result.update({"event": "http_request", "method": str(method)[:16],
                           "path": str(path).split("?", 1)[0][:200], "status": status})
        # detail: a model provider's own error text, cut short and checked for personal data by the caller.
        for key in ("trace_id", "action", "actor_ref", "app_key", "tool_key", "result", "error_code", "duration_ms", "retry_count", "error_type",
                    "detail", "count"):
            if hasattr(record, key):
                result[key] = getattr(record, key)
        return json.dumps(result, default=str)
