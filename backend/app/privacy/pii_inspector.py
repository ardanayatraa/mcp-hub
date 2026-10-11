"""Defense-in-depth detectors. A match fails closed; it is not proof a text is safe."""

import math
import re

EMAIL_RE = re.compile(r"(?i)(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])")
PHONE_RE = re.compile(r"(?<!\d)(?:\+\d{8,15}|\d{10,15})(?!\d)")
FORMATTED_PHONE_RE = re.compile(r"(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]){2,4}\d{2,4}(?!\w)")
NID_RE = re.compile(r"(?<!\d)\d{16}(?!\d)")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
LOCAL_EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@(?:localhost|[a-z][a-z0-9_-]+)(?![\w.-])")
CREDENTIAL_RE = re.compile(r"(?i)\b(?:api[_ -]?key|password|passwd|authorization|bearer|secret|token)\s*[:=]\s*\S+|\b(?:sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|AKIA[A-Z0-9]{16}|hub_[a-z0-9_-]{32,}|eyJ[a-z0-9_-]{10,}\.[a-z0-9_-]{20,})")


def contains_pii(value: str) -> bool:
    return bool(EMAIL_RE.search(value) or LOCAL_EMAIL_RE.search(value) or CREDENTIAL_RE.search(value) or PHONE_RE.search(value) or NID_RE.search(value)
                or SSN_RE.search(value)
                or any(len(re.sub(r"\D", "", m.group())) >= 10 for m in FORMATTED_PHONE_RE.finditer(value)))


def tree_contains_pii(value) -> bool:
    pending = [(value, 0)]
    inspected = 0
    while pending:
        item, depth = pending.pop()
        inspected += 1
        if depth > 16 or inspected > 10000:
            return True  # Fail closed without recursive traversal of hostile trees.
        if isinstance(item, str) and contains_pii(item):
            return True
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.keys())
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, int) and not isinstance(item, bool) and contains_pii(str(item)):
            return True
        elif isinstance(item, float) and (not math.isfinite(item) or (item.is_integer() and contains_pii(str(int(item))))):
            return True
    return False
