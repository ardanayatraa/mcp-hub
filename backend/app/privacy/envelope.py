"""Strict, minimized dataset metadata shared by push and REST tools."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.errors import HubError
from app.privacy.pii_inspector import tree_contains_pii

SCOPE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def safe_meta(meta: dict) -> dict:
    if not isinstance(meta, dict):
        raise HubError("SCHEMA_MISMATCH", "Dataset metadata is required", 422)
    selected = {key: meta.get(key) for key in ("as_of", "timezone", "scope", "coverage")}
    if tree_contains_pii(selected):
        raise HubError("PII_DETECTED", "Response blocked by privacy policy", 422)
    as_of, timezone_name, scope, coverage = (selected[k] for k in selected)
    if not all(isinstance(v, str) for v in (as_of, timezone_name, scope, coverage)):
        raise HubError("SCHEMA_MISMATCH", "Dataset metadata fields are invalid", 422)
    if not SCOPE_RE.fullmatch(scope) or coverage not in {"complete", "partial"}:
        raise HubError("SCHEMA_MISMATCH", "Dataset scope or coverage is invalid", 422)
    try:
        zone = ZoneInfo(timezone_name)
        parsed = datetime.fromisoformat(as_of)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("naive timestamp")
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise HubError("SCHEMA_MISMATCH", "Dataset time metadata is invalid", 422) from exc
    selected["as_of"] = parsed.astimezone(zone).isoformat()
    selected["contains_personal_data"] = False
    if "total_count" in meta:
        count = meta["total_count"]
        if type(count) is not int or not 0 <= count <= 1_000_000_000:
            raise HubError("SCHEMA_MISMATCH", "Dataset total count is invalid", 422)
        selected["total_count"] = count
    if "has_more" in meta:
        if type(meta["has_more"]) is not bool:
            raise HubError("SCHEMA_MISMATCH", "Dataset pagination is invalid", 422)
        if meta["has_more"] and coverage != "partial":
            raise HubError("SCHEMA_MISMATCH", "Incomplete datasets must declare partial coverage", 422)
        selected["has_more"] = meta["has_more"]
    if "next_cursor" in meta and meta["next_cursor"] is not None:
        cursor = meta["next_cursor"]
        if not isinstance(cursor, str) or len(cursor) > 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
            raise HubError("SCHEMA_MISMATCH", "Dataset cursor is invalid", 422)
        if tree_contains_pii(cursor):
            raise HubError("PII_DETECTED", "Response blocked by privacy policy", 422)
        selected["next_cursor"] = cursor
    return selected
