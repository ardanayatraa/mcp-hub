"""The Hub assistant: answers admins' questions about how this MCP Hub works, from its own repository.

It reads the running Hub's repository (README, docs and code) through three read-only tools. Paths
stay inside the repository, and secrets and noise are invisible: .env files, keys, databases, the
git folder, build output, dependencies and the local verification folder. The admin picks the
model; answers stream like the app chat, and nothing is stored but an audit row without content.
"""

import hashlib
import hmac
import os
import time
from pathlib import Path
from types import SimpleNamespace

from mcp.types import Tool
from sqlalchemy.orm import Session

from app.chat import engine, providers, registry
from app.chat import settings as chat_settings
from app.config import Settings, get_settings
from app.errors import HubError
from app.ids import new_trace_id
from app.persistence.models import AdminUser
from app.security.audit import record_audit
from app.security.rate_limit import hit

SKIP_DIRS = {".git", ".verification", ".venv", "node_modules", "dist", "__pycache__", ".pytest_cache", ".ruff_cache",
             ".mypy_cache", ".uv-cache", "tmp", "output", "certs", ".claude", ".kiro"}
SKIP_SUFFIXES = {".db", ".sqlite", ".pem", ".key", ".p12", ".pfx", ".crt", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
                 ".pdf", ".zip", ".gz", ".tar", ".woff", ".woff2", ".ttf", ".exe", ".dll", ".pyd", ".so", ".pyc", ".lock"}
SKIP_NAMES = {"dev.env", "pnpm-lock.yaml", "package-lock.json"}
MAX_FILE_BYTES = 512_000
MAX_LINES = 400
MAX_MATCHES = 40
MAX_ENTRIES = 300
MAX_STEPS = 10
MAX_RESULT_CHARS = 30_000

TOOLS = [
    Tool(name="list_files", title="List files",
         description="The files and folders in one folder of the Hub's repository; an empty path is the root.",
         inputSchema={"type": "object", "additionalProperties": False,
                      "properties": {"path": {"type": "string", "maxLength": 300}}}),
    Tool(name="search_repo", title="Search the repository",
         description="Lines that contain a text (case-insensitive) as path:line: text, optionally only under one folder.",
         inputSchema={"type": "object", "additionalProperties": False, "required": ["query"],
                      "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 200},
                                     "path": {"type": "string", "maxLength": 300}}}),
    Tool(name="read_file", title="Read a file",
         description=f"Numbered lines of one file, at most {MAX_LINES} at a time; use start to read further.",
         inputSchema={"type": "object", "additionalProperties": False, "required": ["path"],
                      "properties": {"path": {"type": "string", "maxLength": 300},
                                     "start": {"type": "integer", "minimum": 1}}}),
]
TITLES = {tool.name: tool.title for tool in TOOLS}

SYSTEM = """You are the assistant in this MCP Hub's admin console. Admins ask how the Hub works: its workflow, \
setup, features, settings, API, security and code. Answer from the Hub's own repository, which you read with \
list_files, search_repo and read_file (read-only). Start with README.md and docs/; read the code under \
backend/app and frontend/src when the docs do not settle it. Name the files you relied on as path:line. \
If the repository does not answer something, say so instead of guessing. Keep answers short and practical, \
with steps where they help, and answer in the language of the question. The repository holds no secrets: \
never ask for keys or passwords.

The repository's top level:
{tree}"""


def repo_root(settings: Settings) -> Path | None:
    """ASSISTANT_REPO_PATH, or the repository this code runs from; None when neither has a README."""

    candidate = Path(settings.assistant_repo_path) if settings.assistant_repo_path else Path(__file__).resolve().parents[3]
    candidate = candidate.resolve()
    return candidate if (candidate / "README.md").is_file() else None


def _visible(root: Path, path: Path) -> bool:
    # A link may point anywhere; only what really lies inside the repository counts.
    if not path.resolve().is_relative_to(root) or any(part in SKIP_DIRS for part in path.relative_to(root).parts):
        return False
    if path.is_dir():
        return True
    name = path.name.lower()
    if name in SKIP_NAMES or (name.startswith(".env") and name != ".env.example") or path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return path.stat().st_size <= MAX_FILE_BYTES


def _resolve(root: Path, raw, *, folder: bool) -> Path:
    """A repository path the tools may open; anything outside it or hidden reads as not found."""

    text = (raw or "").strip().replace("\\", "/").lstrip("/") if isinstance(raw, str) else ""
    path = (root / text).resolve() if text else root
    if not path.is_relative_to(root) or not path.exists() or (path != root and not _visible(root, path)) \
            or path.is_dir() != folder:
        raise HubError("NOT_FOUND", f"No such {'folder' if folder else 'file'} in the repository: {text or '/'}", 404)
    return path


def _files(root: Path, start: Path):
    for folder, dirs, names in os.walk(start):
        dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS)
        for name in sorted(names):
            path = Path(folder, name)
            if _visible(root, path):
                yield path


def list_files(root: Path, arguments: dict) -> str:
    folder = _resolve(root, arguments.get("path"), folder=True)
    entries = [f"{child.name}/" if child.is_dir() else child.name
               for child in sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
               if _visible(root, child)]
    shown = entries[:MAX_ENTRIES]
    return "\n".join(shown) + (f"\n… and {len(entries) - len(shown)} more" if len(entries) > len(shown) else "")


def search_repo(root: Path, arguments: dict) -> str:
    query = str(arguments.get("query") or "").strip().lower()
    if len(query) < 2:
        raise HubError("VALIDATION_FAILED", "query needs at least 2 characters", 422)
    matches: list[str] = []
    for path in _files(root, _resolve(root, arguments.get("path"), folder=True)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if query in line.lower():
                matches.append(f"{path.relative_to(root).as_posix()}:{number}: {line.strip()[:200]}")
                if len(matches) >= MAX_MATCHES:
                    return "\n".join(matches) + "\n… more matches; search a narrower text or folder"
    return "\n".join(matches) or "No matches."


def read_file(root: Path, arguments: dict) -> str:
    path = _resolve(root, arguments.get("path"), folder=False)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise HubError("VALIDATION_FAILED", "That file is not text", 422) from exc
    start = arguments.get("start") if type(arguments.get("start")) is int and arguments["start"] > 0 else 1
    chunk = lines[start - 1:start - 1 + MAX_LINES]
    body = "\n".join(f"{number}: {line}" for number, line in enumerate(chunk, start))
    rest = len(lines) - (start - 1 + len(chunk))
    return f"{path.relative_to(root).as_posix()} ({len(lines)} lines)\n{body}" + (
        f"\n… {rest} more lines; read_file again with start={start + len(chunk)}" if rest > 0 else "")


RUN = {"list_files": list_files, "search_repo": search_repo, "read_file": read_file}


def _detail(name: str, arguments) -> str:
    if not isinstance(arguments, dict):
        return ""
    if name == "search_repo":
        return str(arguments.get("query") or "")[:80]
    return str(arguments.get("path") or "/")[:120]


class AssistantTurn:
    """One question: the model reads the repository with the tools until it can answer."""

    def __init__(self, db: Session, admin: AdminUser, body, settings: Settings | None = None) -> None:
        self.db, self.admin = db, admin
        self.settings = settings or get_settings()
        self.trace = new_trace_id()
        self.started = time.perf_counter()
        self.request = engine.parse_request(body)
        model = chat_settings.chosen_model(db, body)
        if model is None:
            raise HubError("VALIDATION_FAILED", "Choose a provider and a model", 422)
        self.config = SimpleNamespace(provider=model[0], model=model[1], effort="medium")
        root = repo_root(self.settings)
        if root is None:
            raise HubError("ASSISTANT_UNAVAILABLE", "The Hub cannot find its repository. Set ASSISTANT_REPO_PATH.", 503)
        self.root = root
        self.endpoint: registry.Endpoint | None = None

    async def prepare(self) -> "AssistantTurn":
        self.settings = registry.claude_settings(self.db, self.settings)
        self.endpoint = registry.endpoint_for(self.db, self.config.provider, self.settings)
        hit(f"assistant:{self.admin.id}", self.settings.chat_rate_limit, 60)
        return self

    async def run(self, emit: engine.Emit) -> dict:
        error: HubError | None = None
        try:
            return await self._run(emit)
        except HubError as exc:
            error = exc
            raise
        except BaseException:
            error = HubError("INTERNAL", "The assistant failed unexpectedly", 500)
            raise
        finally:
            self.db.rollback()
            record_audit(self.db, action="assistant.turn", actor_ref=f"admin:{self.admin.id}", trace_id=self.trace,
                         result="success" if error is None else "error", error_code=error.code if error else None,
                         duration_ms=max(1, int((time.perf_counter() - self.started) * 1000)))
            self.db.commit()

    async def _run(self, emit: engine.Emit) -> dict:
        system = SYSTEM.format(tree=list_files(self.root, {}))
        # An opaque id lets the model provider spot abuse without learning who is asking.
        user_id = hmac.new(f"assistant:{self.settings.secret_encryption_key}".encode(), self.admin.id.encode(),
                           hashlib.sha256).hexdigest()[:32]
        conversation = providers.start(self.settings, self.config, endpoint=self.endpoint, system=system,
                                       messages=engine._messages(self.request.history, self.request.message),
                                       tools=TOOLS, user_id=user_id)
        used: list[dict] = []
        steps = 0

        async def on_text(delta: str) -> None:
            await emit("text", {"delta": delta})

        try:
            while True:
                step = await conversation.step(on_text, allow_tools=steps < MAX_STEPS)
                if not step.calls or step.stop in ("refusal", "max_tokens"):
                    break
                if steps >= MAX_STEPS:
                    await emit("notice", {"code": "STEP_LIMIT", "message": "The assistant read as much as it may for one "
                                                                         "question. Ask a narrower one."})
                    break
                steps += 1
                results = []
                for call in step.calls:
                    name = conversation.hub_name(call.name)
                    detail = _detail(name, call.arguments)
                    event = {"id": call.id, "name": name, "title": TITLES.get(name, name), "detail": detail}
                    await emit("tool", {**event, "status": "running"})
                    try:
                        if name not in RUN:
                            raise HubError("UNKNOWN_TOOL", "That tool is not available", 404)
                        if not isinstance(call.arguments, dict):
                            raise HubError("INVALID_JSON", "Tool arguments were not valid JSON", 422)
                        content, failed = RUN[name](self.root, call.arguments), False
                    except HubError as exc:
                        content, failed = f"{exc.code}: {exc.message}", True
                    if len(content) > MAX_RESULT_CHARS:
                        content = content[:MAX_RESULT_CHARS] + "\n… (cut; read a smaller part)"
                    used.append({**event, "status": "error" if failed else "done"})
                    await emit("tool", used[-1])
                    results.append(providers.Result(call.id, content, is_error=failed))
                conversation.add_results(results)
        finally:
            await conversation.close()
        return {"trace_id": self.trace, "steps": steps, "tools": used, "proposals": [], "notices": []}


def options(db: Session, settings: Settings) -> dict:
    """What the console needs before the first question: whether the repository is there, and the models."""

    providers_list = chat_settings.provider_options(db, settings, "")
    ready = next((item for item in providers_list if item["ready"]), None)
    return {"available": repo_root(settings) is not None, "providers": providers_list,
            "default": {"provider": ready["id"], "model": ready["default_model"]} if ready else None}
