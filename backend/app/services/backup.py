"""Metadata export and restore. Ciphertext is copied; plaintext secrets are not."""

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.errors import HubError
from app.ids import utcnow
from app.persistence.base import Base
from app.persistence.models import (
    AdminApplicationScope,
    AdminSession,
    AdminUser,
    Application,
    AuditEvent,
    ChatSetting,
    Connector,
    ConnectorEnrollment,
    ConnectorHealthCheck,
    ConnectorSecret,
    ContractSnapshot,
    FieldPolicy,
    GatewayUsage,
    McpAccessProfile,
    MemorySetting,
    MfaChallenge,
    ModelProvider,
    ModuleDefinition,
    ModuleSetting,
    RestToolMapping,
    ServiceIdentity,
    Skill,
    ToolDefinition,
    ToolSwitch,
    ToolTestRun,
)
from app.tools import memory

# User memories are end-user data, not configuration: they are never exported.
EXPORT_ORDER = [
    Application,
    MemorySetting,
    ModelProvider,
    ChatSetting,
    ToolSwitch,
    Skill,
    AdminApplicationScope,
    Connector,
    ConnectorSecret,
    ContractSnapshot,
    ModuleDefinition,
    ModuleSetting,
    FieldPolicy,
    RestToolMapping,
    ToolDefinition,
    ToolTestRun,
    McpAccessProfile,
    ServiceIdentity,
    ConnectorEnrollment,
]
# Placeholder tables from earlier releases; their rows are ignored on restore.
LEGACY_TABLES = {"mcp_server_profiles", "mcp_profile_tools", "skill_definitions"}


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def export_metadata(db: Session) -> dict:
    document = {"format": "mcp-hub-metadata-v1", "tables": {}}
    for model in EXPORT_ORDER:
        rows = []
        for obj in db.scalars(select(model)):
            rows.append({column.name: _jsonable(getattr(obj, column.name)) for column in model.__table__.columns})
        document["tables"][model.__tablename__] = rows
    return document


def import_metadata(db: Session, document: dict) -> dict:
    from sqlalchemy.exc import IntegrityError

    if document.get("format") != "mcp-hub-metadata-v1":
        raise HubError("VALIDATION_FAILED", "Backup format is not recognized", 422)
    tables = document.get("tables") or {}
    if not isinstance(tables, dict) or set(tables) - {m.__tablename__ for m in EXPORT_ORDER} - LEGACY_TABLES:
        raise HubError("VALIDATION_FAILED", "Backup tables are invalid", 422)
    prepared = {}
    # Parse and validate all records before replacing any current configuration.
    for model in EXPORT_ORDER:
        payload = tables.get(model.__tablename__, [])
        if not isinstance(payload, list) or len(payload) > 10000:
            raise HubError("VALIDATION_FAILED", "Backup table exceeds its record limit", 422)
        rows = []
        for raw in payload:
            if not isinstance(raw, dict) or set(raw) - {c.name for c in model.__table__.columns}:
                raise HubError("VALIDATION_FAILED", "Backup record fields are invalid", 422)
            values = {}
            for column in model.__table__.columns:
                value = raw.get(column.name)
                if column.name not in raw and column.default is not None and column.default.is_scalar:
                    value = column.default.arg
                elif column.name not in raw and column.default is not None and column.type.__class__.__name__ == "JSON":
                    value = column.default.arg(None)
                if value is not None and column.type.__class__.__name__.startswith("DateTime"):
                    try:
                        value = datetime.fromisoformat(value)
                    except (ValueError, TypeError) as exc:
                        raise HubError("VALIDATION_FAILED", "Backup timestamp is invalid", 422) from exc
                elif value is not None:
                    type_name = column.type.__class__.__name__
                    valid = ((type_name in {"String", "Text"} and isinstance(value, str)) or
                             (type_name == "Boolean" and type(value) is bool) or
                             (type_name == "Integer" and type(value) is int) or
                             (type_name == "JSON" and isinstance(value, (dict, list))))
                    if not valid:
                        raise HubError("VALIDATION_FAILED", "Backup field type is invalid", 422)
                if value is None and not column.nullable and column.default is None:
                    raise HubError("VALIDATION_FAILED", "Backup required field is missing", 422)
                values[column.name] = value
            if model is ConnectorEnrollment and db.get(AdminUser, values["created_by"]) is None:
                continue
            if model is AdminApplicationScope and db.get(AdminUser, values["user_id"]) is None:
                continue  # A restore never creates administrators or grants an unknown identity.
            if model is ToolDefinition and not _restorable_tool(values):
                values["status"] = "disabled"
            if model is ToolDefinition and values.get("status") in {"validated", "approved"}:
                values["status"] = "draft"
            rows.append(model(**values))
        prepared[model] = rows
    counts = {}
    try:
        for model in reversed(EXPORT_ORDER):
            db.execute(delete(model))
        db.flush()
        db.expunge_all()
        for model in EXPORT_ORDER:
            db.add_all(prepared[model])
            db.flush()  # Flush parents before their children; no implicit ORM dependency assumption.
            counts[model.__tablename__] = len(prepared[model])
    except IntegrityError as exc:
        db.rollback()
        raise HubError("VALIDATION_FAILED", "Backup relationships are invalid", 422) from exc
    return counts


def _restorable_tool(values: dict) -> bool:
    """Legacy or tampered tool configurations restore disabled instead of failing the import."""

    from app.tools import report_engine
    from app.tools.definitions import TEMPLATES
    from app.tools.schema_tools import validate_input_schema, validate_output_schema

    try:
        template = values.get("template") or "read"
        if template not in TEMPLATES:
            return False
        if template == "report":
            report_engine.parse_spec(values.get("report_spec") or {}, report_engine.SavedReport)
            return True
        validate_input_schema(values["input_schema"])
        validate_output_schema(values["output_schema"], values["output_policy"]["allow_fields"])
        return True
    except (HubError, KeyError, TypeError):
        return False


def purge_expired(db: Session, retention_days: int) -> dict:
    cutoff = utcnow() - timedelta(days=retention_days)
    removed = {}
    for model in (AuditEvent, ConnectorHealthCheck, ToolTestRun, AdminSession):
        result = db.execute(delete(model).where(model.created_at < cutoff))
        removed[model.__tablename__] = result.rowcount or 0
    result = db.execute(delete(MfaChallenge).where(MfaChallenge.expires_at < utcnow()))
    removed[MfaChallenge.__tablename__] = result.rowcount or 0
    result = db.execute(delete(AdminSession).where(AdminSession.expires_at < utcnow()))
    removed["expired_sessions"] = result.rowcount or 0
    removed["expired_memories"] = memory.purge_expired(db)
    # Gateway usage is kept a little over a year, for month-on-month comparisons.
    oldest = (utcnow().replace(day=1) - timedelta(days=366)).strftime("%Y-%m")
    result = db.execute(delete(GatewayUsage).where(GatewayUsage.period < oldest))
    removed[GatewayUsage.__tablename__] = result.rowcount or 0
    return removed


def metadata_tables_present() -> list[str]:
    return [table.name for table in Base.metadata.sorted_tables]
