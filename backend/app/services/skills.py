"""Skills: named, reusable instructions served to AI clients as MCP prompts.

A skill is text an admin writes for one app, with optional arguments ({{name}}
placeholders) and the tools it relies on. Nothing is executed: the client shows the
skill like a slash command and the model follows it using tools the key may call
anyway. A key that cannot call every listed tool does not see the skill.
"""

import re

from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.registry import get_connector_bundle
from app.errors import HubError
from app.ids import as_utc, new_id, new_trace_id, utcnow
from app.persistence.models import (
    AdminUser,
    Application,
    Connector,
    ServiceIdentity,
    Skill,
    ToolDefinition,
)
from app.privacy.pii_inspector import tree_contains_pii
from app.security.audit import record_audit
from app.security.authorization import allowed_app_ids, require_app_access
from app.security.clients import READ_SCOPE, WRITE_SCOPE, Caller
from app.tools import catalog, memory

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
ARGUMENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]{0,31})\s*\}\}")
MAX_ARGUMENTS = 5
MAX_TOOLS = 10
MAX_VALUE = 300
# Skills legitimately instruct the model, so only markers of an attempt to override it are refused.
BANNED = ("ignore previous", "ignore all previous", "disregard previous", "disregard all previous", "system prompt", "<|")

TEMPLATES = [
    {"key": "data_overview", "title": "Data overview",
     "description": "Explain which data the assistant can answer questions about.",
     "instructions": "Give me an overview of the data you can use. Call list_data_sources, then describe each data "
                     "source in one line and suggest two questions I could ask about it.",
     "arguments": [], "tools": ["list_data_sources"]},
    {"key": "periodic_report", "title": "Periodic report",
     "description": "A short report on one data source for a period, with totals and notable changes.",
     "instructions": "Prepare a report on {{source}} for {{period}}. Use run_report with a time_bucket on the main date "
                     "field, the record count and the most relevant totals. Present a two-sentence summary, a small table "
                     "of the main numbers and any notable changes. Say so if the data coverage is partial.",
     "arguments": [{"name": "source", "description": "Data source key, for example orders", "required": True},
                   {"name": "period", "description": "For example this month or the last 7 days", "required": False}],
     "tools": ["list_data_sources", "run_report"]},
    {"key": "needs_attention", "title": "Records needing attention",
     "description": "Find records that need follow-up and suggest next steps.",
     "instructions": "Using run_report on {{source}}, find records that need attention ({{rule}}). Group them by status, "
                     "show the largest groups first and suggest one next step for each group.",
     "arguments": [{"name": "source", "description": "Data source key", "required": True},
                   {"name": "rule", "description": "What counts as needing attention, for example overdue", "required": False}],
     "tools": ["run_report"]},
    {"key": "explain_number", "title": "Explain a number",
     "description": "Answer a numeric question and show how the number was calculated.",
     "instructions": "Answer this question: {{question}}. Use list_data_sources to choose the right data source and "
                     "fields, then run_report. Show the filters and grouping you used so I can check the number.",
     "arguments": [{"name": "question", "description": "The question to answer", "required": True}],
     "tools": ["list_data_sources", "run_report"]},
    {"key": "personal_briefing", "title": "Personal briefing",
     "description": "A briefing that follows the user's saved preferences (needs memory turned on).",
     "instructions": "Call recall_memory first and follow my saved preferences, such as language, currency and report "
                     "period. Then give me a short briefing on {{topic}} using run_report. If I state a new lasting "
                     "preference, save it with save_memory.",
     "arguments": [{"name": "topic", "description": "What the briefing is about", "required": True}],
     "tools": ["recall_memory", "run_report", "save_memory"]},
]


def _text(value, field: str, *, maximum: int, minimum: int = 1, multiline: bool = False) -> str:
    if not isinstance(value, str):
        raise HubError("VALIDATION_FAILED", f"{field} is required", 422)
    if multiline:
        lines = ["".join(ch for ch in line if ch.isprintable()).rstrip() for line in value.replace("\r\n", "\n").split("\n")]
        cleaned = "\n".join(lines).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    else:
        cleaned = " ".join("".join(ch for ch in value if ch.isprintable()).split())
    if not minimum <= len(cleaned) <= maximum:
        raise HubError("VALIDATION_FAILED", f"{field} must be {minimum} to {maximum} characters", 422)
    if tree_contains_pii(cleaned):
        raise HubError("PII_DETECTED", f"{field} contains personal data or a credential", 422)
    if any(token in cleaned.lower() for token in BANNED):
        raise HubError("VALIDATION_FAILED", f"{field} contains text that tries to override the assistant's rules", 422)
    return cleaned


def available_tools(db: Session, application: Application) -> dict[str, str]:
    """Tools a skill may name for this app: Hub tools and the app's current custom tools."""

    names = {tool.name: tool.title or tool.name for tool in catalog.BUILTINS.values()}
    names.update({tool.name: tool.title or tool.name for tool in memory.TOOLS.values()})
    rows = db.scalars(select(ToolDefinition).join(Connector, Connector.id == ToolDefinition.connector_id)
                      .where(Connector.app_id == application.id, ToolDefinition.status != "archived"))
    for tool in rows:
        names.setdefault(tool.mcp_name, catalog.tool_title(tool))
    return names


def _validate(db: Session, application: Application, data: dict) -> dict:
    key = data.get("key")
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise HubError("VALIDATION_FAILED", "Skill key must be lowercase letters, digits and underscores", 422)
    arguments = data.get("arguments") or []
    if not isinstance(arguments, list) or len(arguments) > MAX_ARGUMENTS:
        raise HubError("VALIDATION_FAILED", f"A skill can have at most {MAX_ARGUMENTS} arguments", 422)
    cleaned_arguments, seen = [], set()
    for item in arguments:
        if not isinstance(item, dict) or set(item) - {"name", "description", "required"}:
            raise HubError("VALIDATION_FAILED", "Each argument needs a name, a description and required", 422)
        name = item.get("name")
        if not isinstance(name, str) or not ARGUMENT_RE.match(name) or name in seen:
            raise HubError("VALIDATION_FAILED", "Argument names must be unique lowercase words", 422)
        seen.add(name)
        cleaned_arguments.append({"name": name, "description": _text(item.get("description") or name, "Argument description",
                                                                     maximum=200),
                                  "required": item.get("required") is True})
    instructions = _text(data.get("instructions"), "Instructions", minimum=10, maximum=4000, multiline=True)
    unknown = set(PLACEHOLDER_RE.findall(instructions)) - seen
    if unknown:
        raise HubError("VALIDATION_FAILED", f"Placeholder {{{{{sorted(unknown)[0]}}}}} has no matching argument", 422)
    tools = data.get("tools") or []
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS or not all(isinstance(name, str) for name in tools):
        raise HubError("VALIDATION_FAILED", f"A skill can name at most {MAX_TOOLS} tools", 422)
    known = available_tools(db, application)
    missing = [name for name in tools if name not in known]
    if missing:
        raise HubError("VALIDATION_FAILED", f"Tool {missing[0]} is not a tool of this app", 422)
    enabled = data.get("enabled", True)
    if type(enabled) is not bool:
        raise HubError("VALIDATION_FAILED", "enabled must be true or false", 422)
    return {"key": key, "title": _text(data.get("title"), "Title", maximum=120),
            "description": _text(data.get("description"), "Description", minimum=3, maximum=300),
            "instructions": instructions, "arguments": cleaned_arguments, "tools": list(dict.fromkeys(tools)),
            "enabled": enabled}


def skill_view(db: Session, skill: Skill) -> dict:
    application = db.get(Application, skill.app_id)
    connector = db.scalar(select(Connector).where(Connector.app_id == skill.app_id))
    live = _live_tool_names(db, application, connector) if application else set()
    return {"id": skill.id, "key": skill.key, "title": skill.title, "description": skill.description,
            "instructions": skill.instructions, "arguments": skill.arguments, "tools": skill.tools,
            "enabled": skill.enabled, "connector_id": connector.id if connector else None,
            "app_id": skill.app_id, "app_key": application.key if application else None,
            "app_name": application.name if application else None,
            "environment": application.environment if application else None,
            # Tools a read/write key could call right now; a skill naming others stays hidden from clients.
            "unavailable_tools": [name for name in skill.tools if name not in live],
            "created_at": as_utc(skill.created_at).isoformat(), "updated_at": as_utc(skill.updated_at).isoformat()}


def _live_tool_names(db: Session, application: Application, connector: Connector | None) -> set[str]:
    preview = ServiceIdentity(id="preview", name="preview", token_hash="", app_id=application.id,
                              scopes=[READ_SCOPE, WRITE_SCOPE], allowed_tools=None)
    return {tool.name for tool in catalog.visible_tools(db, Caller(preview, application, connector))}


def list_skills(db: Session, admin: AdminUser, connector_id: str | None = None) -> list[dict]:
    query = select(Skill).order_by(Skill.app_id, Skill.title)
    allowed = allowed_app_ids(db, admin)
    if allowed is not None:
        query = query.where(Skill.app_id.in_(allowed))
    if connector_id:
        _connector, application = get_connector_bundle(db, connector_id)
        require_app_access(db, admin, application.id)
        query = query.where(Skill.app_id == application.id)
    return [skill_view(db, skill) for skill in db.scalars(query)]


def _audit(db: Session, admin: AdminUser, action: str, application: Application, skill_key: str) -> None:
    record_audit(db, action=action, actor_ref=f"admin:{admin.id}", result="success", app_key=application.key,
                 environment=application.environment, tool_key=skill_key, trace_id=new_trace_id())


def create_skill(db: Session, admin: AdminUser, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HubError("VALIDATION_FAILED", "Skill is invalid", 422)
    connector, application = get_connector_bundle(db, str(payload.get("connector_id") or ""))
    require_app_access(db, admin, application.id)
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived apps cannot get new skills", 409)
    data = _validate(db, application, payload)
    if db.scalar(select(Skill.id).where(Skill.app_id == application.id, Skill.key == data["key"])):
        raise HubError("CONFLICT", "This app already has a skill with that key", 409)
    now = utcnow()
    skill = Skill(id=new_id(), app_id=application.id, created_by=admin.id, created_at=now, updated_at=now, **data)
    db.add(skill)
    db.flush()
    _audit(db, admin, "skill.create", application, skill.key)
    return skill_view(db, skill)


def require_skill(db: Session, admin: AdminUser, skill_id: str) -> tuple[Skill, Application]:
    skill = db.get(Skill, skill_id)
    if skill is None:
        raise HubError("NOT_FOUND", "Skill was not found", 404)
    require_app_access(db, admin, skill.app_id)
    return skill, db.get(Application, skill.app_id)


def update_skill(db: Session, admin: AdminUser, skill: Skill, application: Application, payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) - {"key", "title", "description", "instructions", "arguments",
                                                         "tools", "enabled"}:
        raise HubError("VALIDATION_FAILED", "Skill changes are invalid", 422)
    current = {"key": skill.key, "title": skill.title, "description": skill.description,
               "instructions": skill.instructions, "arguments": skill.arguments, "tools": skill.tools,
               "enabled": skill.enabled}
    data = _validate(db, application, {**current, **payload})
    if data["key"] != skill.key and db.scalar(select(Skill.id).where(Skill.app_id == application.id,
                                                                    Skill.key == data["key"])):
        raise HubError("CONFLICT", "This app already has a skill with that key", 409)
    for name, value in data.items():
        setattr(skill, name, value)
    skill.updated_at = utcnow()
    db.flush()
    _audit(db, admin, "skill.update", application, skill.key)
    return skill_view(db, skill)


def delete_skill(db: Session, admin: AdminUser, skill: Skill, application: Application) -> None:
    _audit(db, admin, "skill.delete", application, skill.key)
    db.delete(skill)


def render(skill_data: dict, arguments: dict | None) -> str:
    """The instructions with argument values filled in, followed by the tools to use."""

    values = arguments or {}
    if not isinstance(values, dict):
        raise HubError("VALIDATION_FAILED", "Skill arguments must be an object", 422)
    declared = {item["name"]: item for item in skill_data["arguments"]}
    unknown = set(values) - set(declared)
    if unknown:
        raise HubError("VALIDATION_FAILED", f"Unknown argument: {sorted(unknown)[0]}", 422)
    filled = {}
    for name, item in declared.items():
        value = values.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if item["required"]:
                raise HubError("VALIDATION_FAILED", f"Argument {name} is required", 422)
            filled[name] = "not specified"
            continue
        filled[name] = _text(str(value), f"Argument {name}", maximum=MAX_VALUE)
    text = PLACEHOLDER_RE.sub(lambda match: filled.get(match.group(1), match.group(0)), skill_data["instructions"])
    if skill_data["tools"]:
        text += "\n\nTools for this task: " + ", ".join(skill_data["tools"]) + "."
    return text


def preview(db: Session, admin: AdminUser, payload: dict) -> dict:
    """Render a saved or unsaved skill exactly as an AI client would receive it."""

    if not isinstance(payload, dict):
        raise HubError("VALIDATION_FAILED", "Preview request is invalid", 422)
    _connector, application = get_connector_bundle(db, str(payload.get("connector_id") or ""))
    require_app_access(db, admin, application.id)
    draft = payload.get("skill")
    if not isinstance(draft, dict):
        raise HubError("VALIDATION_FAILED", "Preview needs the skill to render", 422)
    data = _validate(db, application, {**draft, "key": draft.get("key") or "preview"})
    return {"text": render(data, payload.get("arguments") or {})}


def _visible(db: Session, caller: Caller) -> list[Skill]:
    if caller.connector is None or caller.connector.status != "active":
        return []
    callable_names = {tool.name for tool in catalog.visible_tools(db, caller)}
    skills = db.scalars(select(Skill).where(Skill.app_id == caller.application.id, Skill.enabled.is_(True))
                        .order_by(Skill.key))
    return [skill for skill in skills if set(skill.tools) <= callable_names]


def visible_prompts(db: Session, caller: Caller) -> list[Prompt]:
    return [Prompt(name=skill.key, title=skill.title, description=skill.description,
                   arguments=[PromptArgument(name=item["name"], description=item["description"],
                                             required=item["required"]) for item in skill.arguments])
            for skill in _visible(db, caller)]


def get_prompt(db: Session, caller: Caller, name: str, arguments: dict | None) -> GetPromptResult:
    skill = next((item for item in _visible(db, caller) if item.key == name), None)
    if skill is None:
        raise HubError("NOT_FOUND", "Skill is not available to this client", 404)
    text = render({"instructions": skill.instructions, "arguments": skill.arguments, "tools": skill.tools}, arguments)
    return GetPromptResult(description=skill.description,
                           messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))])
