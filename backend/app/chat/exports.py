"""Report receipts come from tool results; links and file contents are never model-authored."""

import re


def export_receipts(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return []
    receipts = []
    for row in payload["data"][:20]:
        if not isinstance(row, dict) or not isinstance(row.get("export_ref"), str):
            continue
        if (not re.fullmatch(r"exp_[a-p]{48}", row["export_ref"])
                or not isinstance(row.get("status"), str) or not isinstance(row.get("format"), str)
                or row.get("status") not in {"pending", "building", "ready", "failed", "expired"}
                or row.get("format") not in {"csv", "xlsx", "pdf"}):
            continue
        # Applications construct their own authenticated download routes from this
        # reference. Never turn a source/model-supplied URL into a browser anchor.
        receipts.append({key: row[key] for key in ("export_ref", "status", "format")})
    return receipts
