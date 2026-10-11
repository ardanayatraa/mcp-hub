"""Resolve a published mapping to one fixed URL. Callers cannot supply a host or method."""

import re
from urllib.parse import quote

from app.errors import HubError

_PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9_]{0,40})\}")
_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{1,80}$")


def render_path(template: str, arguments: dict) -> tuple[str, dict]:
    remaining = dict(arguments)

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name not in remaining:
            raise HubError("VALIDATION_FAILED", "A required path parameter is missing", 422)
        value = remaining.pop(name)
        text = str(value)
        if not _SEGMENT.match(text):
            raise HubError("VALIDATION_FAILED", "Path parameter contains characters that are not allowed", 422)
        return quote(text, safe="")

    rendered = _PLACEHOLDER.sub(replace, template)
    if rendered.startswith("//") or "\\" in rendered or ".." in rendered:
        raise HubError("VALIDATION_FAILED", "Resolved path is not allowed", 422)
    return rendered, remaining
