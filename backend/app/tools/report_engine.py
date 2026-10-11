"""Default reporting engine: filter, group, total and summarize authorized records in memory.

Records come from a source-reviewed endpoint (or a sample in the admin console) and are
never stored. Field policy decides how each field may be used:

* visible (``allowed_for_ai``/``allowed``): filter, group, sort, show and aggregate;
* ``aggregate_only``: only ``sum``/``avg``, hidden for groups smaller than MIN_GROUP_SIZE;
* anything else, or a field missing from the policy, cannot be used at all.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.errors import HubError
from app.privacy.output_guard import AI_SAFE
from app.privacy.pii_inspector import tree_contains_pii
from app.security.authorization import is_sensitive_path

FILTER_OPS = ("eq", "ne", "in", "gt", "gte", "lt", "lte", "between", "contains", "is_null", "not_null")
METRIC_FUNCTIONS = ("count", "sum", "avg", "min", "max")
INTERVALS = ("day", "week", "month", "year")
MIN_GROUP_SIZE = 3
MAX_LIMIT = 200
PERIOD = "period"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")
FIELD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

Scalar = str | int | float | bool


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Filter(_Strict):
    field: str = Field(min_length=1, max_length=64)
    op: Literal["eq", "ne", "in", "gt", "gte", "lt", "lte", "between", "contains", "is_null", "not_null"] = "eq"
    value: Scalar | list[Scalar] | None = None


class Metric(_Strict):
    fn: Literal["count", "sum", "avg", "min", "max"] = "count"
    field: str | None = Field(default=None, max_length=64)


class TimeBucket(_Strict):
    field: str = Field(min_length=1, max_length=64)
    interval: Literal["day", "week", "month", "year"] = "day"


class Sort(_Strict):
    by: str = Field(min_length=1, max_length=80)
    direction: Literal["asc", "desc"] = "desc"


class ReportSpec(_Strict):
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    time_bucket: TimeBucket | None = None
    metrics: list[Metric] = Field(default_factory=list, max_length=6)
    sort: Sort | None = None
    limit: int = Field(default=50, ge=1, le=MAX_LIMIT)
    columns: list[str] = Field(default_factory=list, max_length=50)


class SavedReport(ReportSpec):
    """A report template: a fixed spec, optionally extended by the AI with extra filters."""

    allow_filters: bool = True


def _invalid(exc: ValidationError) -> HubError:
    # Pydantic messages can contain submitted values; report only locations.
    problems = []
    for error in exc.errors()[:3]:
        location = [str(part) for part in error["loc"]]
        if error["type"] == "extra_forbidden":
            problems.append(".".join(location[:-1] + ["(unexpected field)"]) if location[:-1] else "unexpected field")
        else:
            problems.append(".".join(location) or "report")
    return HubError("VALIDATION_FAILED", "Report request is invalid at: " + ", ".join(problems), 422)


def parse_spec(raw: dict, model: type[ReportSpec] = ReportSpec) -> ReportSpec:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise _invalid(exc) from exc


@dataclass(frozen=True)
class SourceField:
    name: str
    kind: str
    usage: str  # "visible" or "aggregate"
    values: tuple[str, ...] = ()

    def describe(self) -> dict:
        info: dict = {"name": self.name, "type": self.kind}
        if self.usage == "aggregate":
            info["aggregate_only"] = True
        if self.values:
            info["values"] = list(self.values)
        return info


def source_fields(output_schema: dict, policies: dict[str, str]) -> dict[str, SourceField]:
    """Fields a report may use, derived from the reviewed endpoint and current policy."""

    properties = ((output_schema or {}).get("items") or {}).get("properties") or {}
    fields: dict[str, SourceField] = {}
    for name, spec in properties.items():
        classification = "blocked" if is_sensitive_path(name) else policies.get(name, "blocked")
        if classification in AI_SAFE:
            usage = "visible"
        elif classification == "aggregate_only":
            usage = "aggregate"
        else:
            continue
        types = spec.get("type")
        types = types if isinstance(types, list) else [types]
        kind = next((item for item in types if item and item != "null"), "string")
        values = tuple(item for item in spec.get("enum", []) if isinstance(item, str)) if usage == "visible" else ()
        fields[name] = SourceField(name, kind, usage, values)
    return fields


def _label(name: str) -> str:
    return f"'{name}'" if FIELD_NAME_RE.fullmatch(name) else "a field"


def _field(fields: dict[str, SourceField], name: str | None, purpose: str, *, aggregate_ok: bool = False) -> SourceField:
    field = fields.get(name or "")
    if field is None:
        raise HubError("POLICY_LOCKED", f"Field {_label(name or '')} is not available for {purpose}; "
                       "call list_data_sources to see usable fields", 422)
    if field.usage == "aggregate" and not aggregate_ok:
        raise HubError("POLICY_LOCKED", f"Field {_label(field.name)} is aggregate-only; use it in a sum or avg metric", 422)
    return field


def metric_alias(metric: Metric) -> str:
    return "count" if metric.fn == "count" else f"{metric.fn}_{metric.field}"


def validate_spec(spec: ReportSpec, fields: dict[str, SourceField]) -> None:
    for item in spec.filters:
        _field(fields, item.field, "filters")
        value = item.value
        if item.op in {"is_null", "not_null"}:
            if value is not None:
                raise HubError("VALIDATION_FAILED", f"Filter '{item.op}' does not take a value", 422)
        elif item.op in {"in", "between"}:
            size_ok = isinstance(value, list) and (len(value) == 2 if item.op == "between" else 1 <= len(value) <= 50)
            if not size_ok:
                raise HubError("VALIDATION_FAILED", f"Filter '{item.op}' needs a list value", 422)
        elif isinstance(value, list):
            raise HubError("VALIDATION_FAILED", f"Filter '{item.op}' needs a single value", 422)
        elif item.op == "contains" and (not isinstance(value, str) or not 1 <= len(value) <= 100):
            raise HubError("VALIDATION_FAILED", "Filter 'contains' needs text of 1-100 characters", 422)
        elif item.op in {"gt", "gte", "lt", "lte"} and (value is None or isinstance(value, bool)):
            raise HubError("VALIDATION_FAILED", f"Filter '{item.op}' needs a number or date value", 422)
    if len(set(spec.group_by)) != len(spec.group_by):
        raise HubError("VALIDATION_FAILED", "group_by fields must be different", 422)
    reserved = {PERIOD} | {metric_alias(metric) for metric in spec.metrics or [Metric()]}
    for name in spec.group_by:
        _field(fields, name, "grouping")
        if name in reserved:
            raise HubError("VALIDATION_FAILED", f"Field {_label(name)} cannot be grouped because it matches a metric name", 422)
    if spec.time_bucket:
        _field(fields, spec.time_bucket.field, "time buckets")
    aliases = []
    for metric in spec.metrics:
        if metric.fn != "count":
            field = _field(fields, metric.field, f"the {metric.fn} metric", aggregate_ok=metric.fn in {"sum", "avg"})
            if metric.fn in {"sum", "avg"} and field.kind not in {"integer", "number"} and field.usage == "visible":
                raise HubError("VALIDATION_FAILED", f"The {metric.fn} metric needs a numeric field", 422)
        aliases.append(metric_alias(metric))
    if len(set(aliases)) != len(aliases):
        raise HubError("VALIDATION_FAILED", "Metrics must be different", 422)
    for name in spec.columns:
        _field(fields, name, "columns")
    if spec.sort:
        grouped = bool(spec.group_by or spec.time_bucket or spec.metrics)
        allowed = set(spec.group_by) | ({PERIOD} if spec.time_bucket else set()) | set(aliases or ["count"])
        if not grouped:
            _field(fields, spec.sort.by, "sorting")
        elif spec.sort.by not in allowed:
            raise HubError("VALIDATION_FAILED", "Sort by a group field, 'period' or a metric name", 422)


def _moment(value, zone: ZoneInfo) -> datetime | None:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def _decimal(value) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return None
        return number if number.is_finite() else None
    return None


def _comparable(value, zone: ZoneInfo):
    """Normalize to (kind, value) so mixed column types never raise while comparing."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = _decimal(value)
        return ("number", number) if number is not None else None
    if isinstance(value, str):
        moment = _moment(value, zone)
        return ("date", moment) if moment is not None else ("text", value.casefold())
    return None


def _pair(left, right, zone: ZoneInfo):
    a, b = _comparable(left, zone), _comparable(right, zone)
    if a is None or b is None:
        return None
    if a[0] != b[0]:
        # Numeric text (common for decimal columns) compares as a number.
        if a[0] == "number" and b[0] == "text" and (number := _decimal(right)) is not None:
            b = ("number", number)
        elif b[0] == "number" and a[0] == "text" and (number := _decimal(left)) is not None:
            a = ("number", number)
        if a[0] != b[0]:
            return None
    return a, b


def _equal(left, right, zone: ZoneInfo) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    pair = _pair(left, right, zone)
    return pair is not None and pair[0] == pair[1]


def _compare(left, right, zone: ZoneInfo) -> int | None:
    pair = _pair(left, right, zone)
    if pair is None:
        return None
    a, b = pair
    return (a[1] > b[1]) - (a[1] < b[1])


def _end_of_day(value):
    """'2026-10-31' as an upper bound means the whole day."""

    if isinstance(value, str) and len(value) == 10 and DATE_RE.match(value):
        return value + "T23:59:59.999999"
    return value


def _matches(row: dict, item: Filter, zone: ZoneInfo) -> bool:
    value = row.get(item.field)
    op = item.op
    if op == "is_null":
        return value is None
    if op == "not_null":
        return value is not None
    if op == "contains":
        return isinstance(value, str) and str(item.value).casefold() in value.casefold()
    if op == "eq":
        return _equal(value, item.value, zone)
    if op == "ne":
        return not _equal(value, item.value, zone)
    if op == "in":
        return any(_equal(value, candidate, zone) for candidate in item.value)
    if op == "between":
        low = _compare(value, item.value[0], zone)
        high = _compare(value, _end_of_day(item.value[1]), zone)
        return low is not None and high is not None and low >= 0 and high <= 0
    result = _compare(value, _end_of_day(item.value) if op == "lte" else item.value, zone)
    if result is None:
        return False
    return {"gt": result > 0, "gte": result >= 0, "lt": result < 0, "lte": result <= 0}[op]


def _bucket(value, interval: str, zone: ZoneInfo) -> str | None:
    moment = _moment(value, zone)
    if moment is None:
        return None
    if interval == "week":
        year, week, _ = moment.isocalendar()
        return f"{year}-W{week:02d}"
    return moment.strftime({"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}[interval])


def _number(value: Decimal) -> int | float:
    if value == value.to_integral_value() and abs(value) < 2**53:
        return int(value)
    return float(value.quantize(Decimal("0.0001")))


def _metrics(rows: list[dict], metrics: list[Metric], fields: dict[str, SourceField], zone: ZoneInfo,
             notes: set[str]) -> dict:
    result = {}
    for metric in metrics:
        alias = metric_alias(metric)
        if metric.fn == "count":
            result[alias] = len(rows)
            continue
        field = fields[metric.field]
        if field.usage == "aggregate" and len(rows) < MIN_GROUP_SIZE:
            result[alias] = None
            notes.add(f"Aggregate-only values are hidden for groups with fewer than {MIN_GROUP_SIZE} records.")
            continue
        if metric.fn in {"sum", "avg"}:
            numbers = [number for number in (_decimal(row.get(field.name)) for row in rows) if number is not None]
            ignored = sum(1 for row in rows if row.get(field.name) is not None) - len(numbers)
            if ignored:
                notes.add(f"{ignored} non-numeric value(s) were ignored in {alias}.")
            if metric.fn == "sum":
                result[alias] = _number(sum(numbers, Decimal(0)))
            else:
                result[alias] = _number(sum(numbers, Decimal(0)) / len(numbers)) if numbers else None
            continue
        present = [(row.get(field.name), _comparable(row.get(field.name), zone)) for row in rows]
        present = [(raw, key) for raw, key in present if key is not None]
        kinds = {key[0] for _, key in present}
        if len(kinds) > 1:
            notes.add(f"{alias} compared only {sorted(kinds)[0]} values.")
            present = [(raw, key) for raw, key in present if key[0] == sorted(kinds)[0]]
        chosen = (min if metric.fn == "min" else max)(present, key=lambda pair: pair[1][1]) if present else None
        result[alias] = chosen[0] if chosen else None
    return result


def _sort_key(value, zone: ZoneInfo):
    key = _comparable(value, zone)
    if key is not None and key[0] == "text" and (number := _decimal(value)) is not None:
        key = ("number", number)  # "2.50" sorts with 10 and 7, not after them
    return key


def _sort_rows(rows: list[dict], key: str, direction: str, zone: ZoneInfo) -> list[dict]:
    keyed = [(row, _sort_key(row.get(key), zone)) for row in rows]
    order = {"number": 0, "date": 1, "text": 2}
    present = sorted(((row, value) for row, value in keyed if value is not None),
                     key=lambda pair: (order[pair[1][0]], pair[1][1]), reverse=direction == "desc")
    return [row for row, _ in present] + [row for row, value in keyed if value is None]


def run_report(rows: list[dict], spec: ReportSpec, fields: dict[str, SourceField], *, zone: ZoneInfo) -> dict:
    """Return {mode, columns, rows, totals, matched, groups, notes}. Inputs are already authorized."""

    validate_spec(spec, fields)
    matched = [row for row in rows if all(_matches(row, item, zone) for item in spec.filters)]
    notes: set[str] = set()
    grouped = bool(spec.group_by or spec.time_bucket)
    if not grouped and not spec.metrics:
        columns = spec.columns or [field.name for field in fields.values() if field.usage == "visible"]
        ordered = _sort_rows(matched, spec.sort.by, spec.sort.direction, zone) if spec.sort else matched
        shown = [{column: row.get(column) for column in columns} for row in ordered[:spec.limit]]
        return {"mode": "records", "columns": columns, "rows": shown, "totals": {"count": len(matched)},
                "matched": len(matched), "groups": None, "notes": sorted(notes)}
    metrics = spec.metrics or [Metric(fn="count")]
    aliases = [metric_alias(metric) for metric in metrics]
    totals = _metrics(matched, metrics, fields, zone, notes)
    if not grouped:
        return {"mode": "summary", "columns": aliases, "rows": [totals], "totals": totals,
                "matched": len(matched), "groups": None, "notes": sorted(notes)}
    dimensions = list(spec.group_by) + ([PERIOD] if spec.time_bucket else [])
    buckets: dict[tuple, list[dict]] = {}
    for row in matched:
        key = tuple(row.get(name) for name in spec.group_by)
        if spec.time_bucket:
            key += (_bucket(row.get(spec.time_bucket.field), spec.time_bucket.interval, zone),)
        buckets.setdefault(key, []).append(row)
    grouped_rows = [{**dict(zip(dimensions, key)), **_metrics(members, metrics, fields, zone, notes)}
                    for key, members in buckets.items()]
    if spec.sort:
        sort_key, direction = spec.sort.by, spec.sort.direction
    elif spec.time_bucket and not spec.group_by:
        sort_key, direction = PERIOD, "asc"
    else:
        sort_key, direction = aliases[0], "desc"
    grouped_rows = _sort_rows(grouped_rows, sort_key, direction, zone)
    if len(grouped_rows) > spec.limit:
        notes.add(f"Showing the first {spec.limit} of {len(grouped_rows)} groups.")
    return {"mode": "groups", "columns": dimensions + aliases, "rows": grouped_rows[:spec.limit], "totals": totals,
            "matched": len(matched), "groups": len(grouped_rows), "notes": sorted(notes)}


def _format(value) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)[:60]


def summarize(result: dict, *, label: str, scanned: int, coverage: str, truncated: bool, filtered: bool) -> str:
    """A short, deterministic sentence the AI can quote. It never adds facts."""

    matched = result["matched"]
    head = f"{label}: {matched:,} record(s)"
    if filtered:
        head += f" matched the filters out of {scanned:,} read"
    if coverage == "partial":
        head += " (partial data: the scan stopped early)" if truncated else " (partial data)"
    parts = [head + "."]
    mode, rows, columns = result["mode"], result["rows"], result["columns"]
    if mode == "records":
        parts.append(f"Showing {len(rows):,}.")
    elif mode == "summary":
        parts.append("Totals: " + ", ".join(f"{key} {_format(value)}" for key, value in result["totals"].items()) + ".")
    else:
        dimensions = [column for column in columns if column not in result["totals"]]
        metric = next(column for column in columns if column in result["totals"])
        listed = []
        for row in rows[:5]:
            name = " / ".join(_format(row.get(dimension)) for dimension in dimensions)
            value = row.get(metric)
            share = ""
            if metric == "count" and matched and isinstance(value, int):
                share = f" ({value / matched:.0%})"
            listed.append(f"{name}: {_format(value)}{share}")
        if listed:
            parts.append(f"{result['groups']:,} group(s) by {', '.join(dimensions)}; {metric}: " + "; ".join(listed) + ".")
    parts.extend(result["notes"])
    return " ".join(parts)


def chart_hint(result: dict) -> dict | None:
    if result["mode"] != "groups":
        return None
    dimensions = [column for column in result["columns"] if column not in result["totals"]]
    if len(dimensions) != 1:
        return None
    metrics = [column for column in result["columns"] if column in result["totals"]]
    return {"type": "line" if dimensions[0] == PERIOD else "bar", "x": dimensions[0], "y": metrics}


def prepare_rows(rows: list[dict], fields: dict[str, SourceField]) -> tuple[list[dict], int]:
    """Project source rows to usable fields; mask values that are unsafe to show.

    Records that a read tool would return verbatim fail closed on detected personal data.
    A report only shows aggregates and group labels, so an unsafe value is replaced by
    null (it never leaves the Hub) and counted, instead of failing the whole report.
    Aggregate-only values are never shown individually; they are kept when scalar.
    """

    projected, hidden = [], 0
    for row in rows:
        if not isinstance(row, dict):
            raise HubError("SCHEMA_MISMATCH", "Source records must be objects", 422)
        item = {}
        for name, field in fields.items():
            value = row.get(name)
            unsafe = isinstance(value, (dict, list)) or (field.usage == "visible" and tree_contains_pii(value))
            if unsafe:
                hidden += 1
                value = None
            item[name] = value
        projected.append(item)
    return projected, hidden
