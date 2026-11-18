"""Defense-in-depth detectors. A match fails closed; it is not proof a text is safe.

Phone and ID detectors look at digit runs, so they are tuned to leave ordinary business values alone:
JSON numbers (amounts, counts, timestamps) are not phone numbers, ISO dates and times are not phone
numbers, and codes that start with letters (INV-2026-11-0001, SKU2026110900123) are identifiers.
A long digit run that does not start like a phone number (0, 62 or +) is a barcode or an ID, not a
phone. Emails, credentials, +country numbers, local 08… numbers and 16-digit national IDs still match.
"""

import math
import re

EMAIL_RE = re.compile(r"(?i)(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])")
LOCAL_EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@(?:localhost|[a-z][a-z0-9_-]+)(?![\w.-])")
CREDENTIAL_RE = re.compile(r"(?i)\b(?:api[_ -]?key|password|passwd|authorization|bearer|secret|token)\s*[:=]\s*\S+|\b(?:sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|AKIA[A-Z0-9]{16}|hub_[a-z0-9_-]{32,}|eyJ[a-z0-9_-]{10,}\.[a-z0-9_-]{20,})")
# Digit runs that do not continue a word: a run glued to letters (INV2026…) is an identifier.
PHONE_RE = re.compile(r"(?<![A-Za-z0-9])(\+?)(\d{10,15})(?!\d)")
FORMATTED_PHONE_RE = re.compile(r"(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]){2,4}\d{2,4}(?!\w)")
NID_RE = re.compile(r"(?<![A-Za-z0-9])\d{16}(?!\d)")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# ISO dates and times are removed before the phone checks, so "2026-11-09 10:30:00" is not a phone.
DATE_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})?)?")
# A formatted run right after letters and a separator (INV-2026-11-0001, PO/2026/11/0001) is a code.
CODE_PREFIX_RE = re.compile(r"[A-Za-z][-_/#.]?$")


def _phone_run(plus: str, digits: str) -> bool:
    """An unformatted run of 10-15 digits: a phone unless it is long and does not start like one."""

    if plus:
        return True
    if len(digits) >= 13:
        return digits.startswith(("0", "62"))
    return True


def _phone(text: str) -> bool:
    text = DATE_TIME_RE.sub(" ", text)
    if any(_phone_run(match.group(1), match.group(2)) for match in PHONE_RE.finditer(text)):
        return True
    for match in FORMATTED_PHONE_RE.finditer(text):
        if CODE_PREFIX_RE.search(text[max(0, match.start() - 2):match.start()]):
            continue
        if len(re.sub(r"\D", "", match.group())) >= 10:
            return True
    return False


def contains_pii(value: str) -> bool:
    return bool(EMAIL_RE.search(value) or LOCAL_EMAIL_RE.search(value) or CREDENTIAL_RE.search(value)
                or NID_RE.search(value) or SSN_RE.search(value) or _phone(value))


def number_contains_pii(value: int | float) -> bool:
    """A JSON number is an amount, count or timestamp, never a phone; a 16-digit one may be a national ID."""

    if isinstance(value, float):
        if not math.isfinite(value):
            return True
        if not value.is_integer():
            return False
        value = int(value)
    return len(str(abs(value))) == 16


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
        elif isinstance(item, (int, float)) and not isinstance(item, bool) and number_contains_pii(item):
            return True
    return False
