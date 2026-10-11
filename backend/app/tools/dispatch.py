"""One tool call, from any front door: the MCP endpoint or the Hub's own chat.

Every call is authorized from scratch, checked for personal data on the way in, audited
once, and committed on its own, so a later failure in the same conversation cannot undo
the record of an earlier call.
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.discovery import sync_source_permissions
from app.connectors.http_adapter import last_retry_count
from app.errors import HubError
from app.ids import new_trace_id
from app.persistence.models import ToolDefinition
from app.privacy.pii_inspector import tree_contains_pii
from app.security.audit import record_audit
from app.security.authorization import reject_forbidden_keys
from app.security.clients import Caller
from app.security.rate_limit import hit
from app.tools import catalog, memory, switches
from app.tools.definitions import WRITE_TEMPLATES
from app.tools.runtime import execute_tool, resolve_source_key, run_report_for_caller
from app.tools.schema_tools import validate_arguments

logger = logging.getLogger("hub.tools")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


@dataclass
class Outcome:
    trace_id: str
    tool_key: str
    payload: dict | None = None
    error: HubError | None = None


def safe_name(name) -> str:
    """The name as given when it is a well-formed tool name, otherwise a placeholder safe to log."""

    return name if isinstance(name, str) and NAME_RE.fullmatch(name) and not tree_contains_pii(name) else "unrecognized"


def _published_tool(db: Session, name: str, caller: Caller) -> ToolDefinition:
    tool = db.scalar(select(ToolDefinition).where(ToolDefinition.mcp_name == name, ToolDefinition.status == "published"))
    if tool is None or caller.connector is None or tool.connector_id != caller.connector.id:
        raise HubError("PERMISSION_DENIED", "Tool is not available to this client", 403)
    return tool


async def run_tool(db: Session, caller: Caller, name, arguments, *, delegation: str | None, trace: str,
                   state: dict) -> dict:
    if state["tool_key"] == "unrecognized":
        raise HubError("VALIDATION_FAILED", "Tool name is invalid", 422)
    if not isinstance(arguments, dict):
        raise HubError("VALIDATION_FAILED", "Tool arguments must be an object", 422)
    # Personal data must be entered in the application's own forms, never through AI chat.
    if tree_contains_pii(arguments):
        raise HubError("PII_DETECTED", "Input blocked by privacy policy", 422)
    reject_forbidden_keys(arguments)
    if not caller.allows(name):
        raise HubError("PERMISSION_DENIED", "This client key is not allowed to use that tool", 403)
    switches.require_on(db, caller.application.id, name)
    await sync_source_permissions(db, caller.connector, caller.application, get_settings())
    if name == catalog.LIST_SOURCES:
        validate_arguments(catalog.BUILTINS[name].input_schema, arguments)
        if caller.connector is None or caller.connector.status != "active":
            raise HubError("CONNECTOR_INACTIVE", "Connector is not active", 409)
        settings = get_settings()
        hit(f"tool:{caller.actor_ref}:{name}", settings.tool_rate_limit, settings.tool_rate_window_seconds)
        return {"success": True, "data": catalog.data_sources(db, caller.application.id),
                "meta": {"scope": "enabled_sources", "coverage": "complete", "contains_personal_data": False},
                "trace_id": trace}
    if name == catalog.RUN_REPORT:
        validate_arguments(catalog.REPORT_INPUT, arguments)
        state["module_key"] = resolve_source_key(caller.application, arguments.get("source"))
        if caller.connector is None:
            raise HubError("CONNECTOR_INACTIVE", "Connector is not active", 409)
        return await run_report_for_caller(db, application=caller.application, connector=caller.connector,
                                           arguments=arguments, actor_ref=caller.actor_ref,
                                           delegation_header=delegation, trace_id=trace)
    if name in memory.NAMES:
        return memory.run(db, name=name, arguments=arguments, application=caller.application,
                          connector=caller.connector, actor_ref=caller.actor_ref, delegation_header=delegation,
                          settings=get_settings(), trace_id=trace)
    tool = _published_tool(db, name, caller)
    state["tool_key"], state["module_key"] = tool.tool_key, tool.module_key
    if tool.template in WRITE_TEMPLATES and not caller.can_write:
        raise HubError("PERMISSION_DENIED", "This client key does not have write permission", 403)
    return await execute_tool(db, tool=tool, arguments=arguments, actor_ref=caller.actor_ref,
                              delegation_header=delegation, trace_id=trace)


def _audit(db: Session, state: dict, trace: str, started: float, error: HubError | None) -> None:
    caller: Caller | None = state["caller"]
    application = caller.application if caller else None
    record_audit(
        db, action="tool.execute", actor_ref=caller.actor_ref if caller else "service:unknown",
        app_key=application.key if application else None,
        environment=application.environment if application else None,
        module_key=state["module_key"], tool_key=state["tool_key"], trace_id=trace,
        result="success" if error is None else ("denied" if error.status_code in {401, 403} else "error"),
        error_code=error.code if error else None,
        duration_ms=max(1, int((time.perf_counter() - started) * 1000)), retry_count=last_retry_count())


async def execute(db: Session, name, arguments, *, caller_for: Callable[[Session], Caller], delegation: str | None,
                  trace: str | None = None) -> Outcome:
    """Run one call and audit it. Errors come back in the outcome, never as exceptions.

    Chat passes its turn's trace so the activity log shows a turn's calls together.
    """

    trace = trace or new_trace_id()
    started = time.perf_counter()
    state = {"caller": None, "tool_key": safe_name(name), "module_key": None}
    try:
        try:
            caller = caller_for(db)
            state["caller"] = caller
            payload = await run_tool(db, caller, name, arguments, delegation=delegation, trace=trace, state=state)
        except HubError as exc:
            _audit(db, state, trace, started, exc)
            db.commit()
            return Outcome(trace, state["tool_key"], error=exc)
        _audit(db, state, trace, started, None)
        db.commit()
        return Outcome(trace, state["tool_key"], payload=payload)
    except Exception as exc:
        # A defect must not leak details to the client; the trace links the log line.
        db.rollback()
        logger.error("tool_failure", extra={"error_type": type(exc).__name__, "trace_id": trace})
        failure = HubError("INTERNAL", "The tool failed unexpectedly", 500)
        try:
            _audit(db, state, trace, started, failure)
            db.commit()
        except Exception:
            db.rollback()
        return Outcome(trace, state["tool_key"], error=failure)
