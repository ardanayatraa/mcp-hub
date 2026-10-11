"""Audit events store metadata only. Payloads, tokens, and personal data stay out."""

import logging

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


class SafeJSONFormatter(logging.Formatter):
    def format(self, record):
        import json
        result = {"level": record.levelname, "logger": record.name}
        for key in ("trace_id", "action", "actor_ref", "app_key", "tool_key", "result", "error_code", "duration_ms", "retry_count", "error_type"):
            if hasattr(record, key):
                result[key] = getattr(record, key)
        return json.dumps(result, default=str)
