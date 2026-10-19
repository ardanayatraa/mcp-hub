import Decimal from "decimal.js";
import { HubError } from "./errors.js";
import { isSensitivePath, treeContainsPii } from "./privacy.js";

export const FILTER_OPS = ["eq", "ne", "in", "gt", "gte", "lt", "lte", "between", "contains", "is_null", "not_null"];
export const METRIC_FUNCTIONS = ["count", "sum", "avg", "min", "max"];
export const INTERVALS = ["day", "week", "month", "year"];
export const MAX_LIMIT = 200;
const scalar = [{ type: "string", maxLength: 200 }, { type: "number" }, { type: "boolean" }];
const fieldSchema = { type: "string", maxLength: 64 };
export const REPORT_INPUT = { type: "object", additionalProperties: false, required: ["source"], properties: {
  source: { type: "string", maxLength: 130 },
  filters: { type: "array", maxItems: 10, items: { type: "object", additionalProperties: false,
    required: ["field", "op"], properties: { field: fieldSchema, op: { type: "string", enum: FILTER_OPS },
      value: { anyOf: [...scalar, { type: "array", maxItems: 50, items: { anyOf: scalar } }, { type: "null" }] } } } },
  group_by: { type: "array", maxItems: 2, items: fieldSchema },
  time_bucket: { type: "object", additionalProperties: false, required: ["field"], properties: {
    field: fieldSchema, interval: { type: "string", enum: INTERVALS } } },
  metrics: { type: "array", maxItems: 6, items: { type: "object", additionalProperties: false,
    required: ["fn"], properties: { fn: { type: "string", enum: METRIC_FUNCTIONS }, field: fieldSchema } } },
  sort: { type: "object", additionalProperties: false, required: ["by"], properties: {
    by: { type: "string", maxLength: 80 }, direction: { type: "string", enum: ["asc", "desc"] } } },
  limit: { type: "integer", minimum: 1, maximum: MAX_LIMIT },
  columns: { type: "array", maxItems: 50, items: fieldSchema },
} };
const MIN_GROUP_SIZE = 3;
const error = (code, message) => { throw new HubError(message, code, 422); };
const object = (value) => value && typeof value === "object" && !Array.isArray(value);
const only = (value, keys) => Object.keys(value).every((key) => keys.includes(key));
const label = (name) => /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(name) ? `'${name}'` : "a field";

export function parseSpec(raw, saved = false) {
  if (!object(raw) || !only(raw, ["filters", "group_by", "time_bucket", "metrics", "sort", "limit", "columns",
    ...(saved ? ["allow_filters"] : [])])) error("VALIDATION_FAILED", "Report request is invalid at: report");
  const spec = { filters: raw.filters ?? [], group_by: raw.group_by ?? [], time_bucket: raw.time_bucket ?? null,
    metrics: raw.metrics ?? [], sort: raw.sort ?? null, limit: raw.limit ?? 50, columns: raw.columns ?? [] };
  if (!Array.isArray(spec.filters) || spec.filters.length > 10 ||
      spec.filters.some((item) => !object(item) || !only(item, ["field", "op", "value"]) ||
        typeof item.field !== "string" || !item.field || item.field.length > 64 ||
        !FILTER_OPS.includes(item.op ?? "eq"))) error("VALIDATION_FAILED", "Report request is invalid at: filters");
  if (!Array.isArray(spec.group_by) || spec.group_by.length > 2 ||
      spec.group_by.some((name) => typeof name !== "string" || !name || name.length > 64)) {
    error("VALIDATION_FAILED", "Report request is invalid at: group_by");
  }
  if (spec.time_bucket && (!object(spec.time_bucket) || !only(spec.time_bucket, ["field", "interval"]) ||
      typeof spec.time_bucket.field !== "string" || !spec.time_bucket.field ||
      !INTERVALS.includes(spec.time_bucket.interval ?? "day"))) {
    error("VALIDATION_FAILED", "Report request is invalid at: time_bucket");
  }
  if (!Array.isArray(spec.metrics) || spec.metrics.length > 6 || spec.metrics.some((metric) =>
    !object(metric) || !only(metric, ["fn", "field"]) || !METRIC_FUNCTIONS.includes(metric.fn ?? "count") ||
    (metric.field !== undefined && (typeof metric.field !== "string" || metric.field.length > 64)))) {
    error("VALIDATION_FAILED", "Report request is invalid at: metrics");
  }
  if (spec.sort && (!object(spec.sort) || !only(spec.sort, ["by", "direction"]) ||
      typeof spec.sort.by !== "string" || !spec.sort.by || spec.sort.by.length > 80 ||
      !["asc", "desc"].includes(spec.sort.direction ?? "desc"))) {
    error("VALIDATION_FAILED", "Report request is invalid at: sort");
  }
  if (!Number.isInteger(spec.limit) || spec.limit < 1 || spec.limit > MAX_LIMIT ||
      !Array.isArray(spec.columns) || spec.columns.length > 50 ||
      spec.columns.some((name) => typeof name !== "string" || !name || name.length > 64)) {
    error("VALIDATION_FAILED", "Report request is invalid at: limit or columns");
  }
  spec.filters = spec.filters.map((item) => ({ op: "eq", value: null, ...item }));
  spec.metrics = spec.metrics.map((item) => ({ fn: "count", ...item }));
  if (spec.time_bucket) spec.time_bucket = { interval: "day", ...spec.time_bucket };
  if (spec.sort) spec.sort = { direction: "desc", ...spec.sort };
  if (saved) spec.allow_filters = raw.allow_filters ?? true;
  return spec;
}

export function sourceFields(outputSchema, policies) {
  const fields = {};
  for (const [name, schema] of Object.entries(outputSchema?.items?.properties ?? {})) {
    const classification = isSensitivePath(name) ? "blocked" : policies[name] ?? "blocked";
    const usage = ["allowed", "allowed_for_ai"].includes(classification) ? "visible"
      : classification === "aggregate_only" ? "aggregate" : null;
    if (!usage) continue;
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    fields[name] = { name, kind: types.find((type) => type !== "null") ?? "string", usage,
      values: usage === "visible" ? (schema.enum ?? []) : [] };
  }
  return fields;
}

function field(fields, name, purpose, aggregateOk = false) {
  const found = fields[name ?? ""];
  if (!found) error("POLICY_LOCKED", `Field ${label(name ?? "")} is not available for ${purpose}; call list_data_sources to see usable fields`);
  if (found.usage === "aggregate" && !aggregateOk) {
    error("POLICY_LOCKED", `Field ${label(found.name)} is aggregate-only; use it in a sum or avg metric`);
  }
  return found;
}

const alias = (metric) => metric.fn === "count" ? "count" : `${metric.fn}_${metric.field}`;

export function validateSpec(spec, fields) {
  for (const item of spec.filters) {
    field(fields, item.field, "filters");
    const value = item.value;
    if (["is_null", "not_null"].includes(item.op) && value !== null) error("VALIDATION_FAILED", `Filter '${item.op}' does not take a value`);
    if (["in", "between"].includes(item.op)) {
      if (!Array.isArray(value) || (item.op === "between" ? value.length !== 2 : value.length < 1 || value.length > 50)) {
        error("VALIDATION_FAILED", `Filter '${item.op}' needs a list value`);
      }
    } else if (Array.isArray(value)) error("VALIDATION_FAILED", `Filter '${item.op}' needs a single value`);
    if (item.op === "contains" && (typeof value !== "string" || value.length < 1 || value.length > 100)) {
      error("VALIDATION_FAILED", "Filter 'contains' needs text of 1-100 characters");
    }
    if (["gt", "gte", "lt", "lte"].includes(item.op) && (value === null || typeof value === "boolean")) {
      error("VALIDATION_FAILED", `Filter '${item.op}' needs a number or date value`);
    }
  }
  if (new Set(spec.group_by).size !== spec.group_by.length) error("VALIDATION_FAILED", "group_by fields must be different");
  const aliases = (spec.metrics.length ? spec.metrics : [{ fn: "count" }]).map(alias);
  for (const name of spec.group_by) {
    field(fields, name, "grouping");
    if (["period", ...aliases].includes(name)) error("VALIDATION_FAILED", `Field ${label(name)} cannot be grouped because it matches a metric name`);
  }
  if (spec.time_bucket) field(fields, spec.time_bucket.field, "time buckets");
  for (const metric of spec.metrics) {
    if (metric.fn === "count") continue;
    const chosen = field(fields, metric.field, `the ${metric.fn} metric`, ["sum", "avg"].includes(metric.fn));
    if (["sum", "avg"].includes(metric.fn) && chosen.usage === "visible" &&
        !["integer", "number"].includes(chosen.kind)) error("VALIDATION_FAILED", `The ${metric.fn} metric needs a numeric field`);
  }
  if (new Set(aliases).size !== aliases.length) error("VALIDATION_FAILED", "Metrics must be different");
  spec.columns.forEach((name) => field(fields, name, "columns"));
  if (spec.sort) {
    const grouped = !!(spec.group_by.length || spec.time_bucket || spec.metrics.length);
    const allowed = [...spec.group_by, ...(spec.time_bucket ? ["period"] : []), ...aliases];
    if (grouped && !allowed.includes(spec.sort.by)) error("VALIDATION_FAILED", "Sort by a group field, 'period' or a metric name");
    if (!grouped) field(fields, spec.sort.by, "sorting");
  }
}

function decimal(value) {
  if (value === null || value === undefined || typeof value === "boolean" ||
      !["number", "string"].includes(typeof value)) return null;
  try { const result = new Decimal(String(value).trim()); return result.isFinite() ? result : null; }
  catch { return null; }
}

function moment(value, zone) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/.test(value)) return null;
  if (value.length === 10) return { timestamp: Date.parse(`${value}T12:00:00Z`), localDate: value };
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return null;
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: zone, year: "numeric",
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    hourCycle: "h23" }).formatToParts(parsed).map((part) => [part.type, part.value]));
  const localDate = `${parts.year}-${parts.month}-${parts.day}`;
  return { timestamp: parsed, localDate };
}

function comparable(value, zone) {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  if (typeof value === "number") { const number = decimal(value); return number ? ["number", number] : null; }
  if (typeof value === "string") { const date = moment(value, zone); return date ? ["date", date.timestamp] : ["text", value.toLocaleLowerCase()]; }
  return null;
}

function compare(left, right, zone) {
  let a = comparable(left, zone); let b = comparable(right, zone);
  if (!a || !b) return null;
  if (a[0] !== b[0]) {
    if (a[0] === "number" && b[0] === "text" && decimal(right)) b = ["number", decimal(right)];
    else if (b[0] === "number" && a[0] === "text" && decimal(left)) a = ["number", decimal(left)];
    if (a[0] !== b[0]) return null;
  }
  const first = a[1]; const second = b[1];
  return first instanceof Decimal ? first.comparedTo(second) : Math.sign(first > second ? 1 : first < second ? -1 : 0);
}

function equal(left, right, zone) {
  if (left === null || right === null) return left === null && right === null;
  if (typeof left === "boolean" || typeof right === "boolean") return typeof left === "boolean" && left === right;
  return compare(left, right, zone) === 0;
}

function matches(row, filter, zone) {
  const value = row[filter.field] ?? null;
  if (filter.op === "is_null") return value === null;
  if (filter.op === "not_null") return value !== null;
  if (filter.op === "contains") return typeof value === "string" && value.toLocaleLowerCase().includes(filter.value.toLocaleLowerCase());
  if (filter.op === "eq") return equal(value, filter.value, zone);
  if (filter.op === "ne") return !equal(value, filter.value, zone);
  if (filter.op === "in") return filter.value.some((item) => equal(value, item, zone));
  if (filter.op === "between") {
    const low = compare(value, filter.value[0], zone);
    const high = compare(value, filter.value[1], zone);
    return low !== null && high !== null && low >= 0 && high <= 0;
  }
  const result = compare(value, filter.value, zone);
  if (result === null) return false;
  return { gt: result > 0, gte: result >= 0, lt: result < 0, lte: result <= 0 }[filter.op];
}

function bucket(value, interval, zone) {
  const date = moment(value, zone)?.localDate;
  if (!date) return null;
  if (interval === "day") return date;
  if (interval === "month") return date.slice(0, 7);
  if (interval === "year") return date.slice(0, 4);
  const day = new Date(`${date}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() + 4 - (day.getUTCDay() || 7));
  const year = day.getUTCFullYear();
  const week = Math.ceil((((day - new Date(Date.UTC(year, 0, 1))) / 86400000) + 1) / 7);
  return `${year}-W${String(week).padStart(2, "0")}`;
}

function numberOut(value) {
  return value.isInteger() && value.abs().lt(2 ** 53) ? value.toNumber() : value.toDecimalPlaces(4).toNumber();
}

function metricsFor(rows, metrics, fields, zone, notes) {
  const result = {};
  for (const metric of metrics) {
    const key = alias(metric);
    if (metric.fn === "count") { result[key] = rows.length; continue; }
    const selected = fields[metric.field];
    if (selected.usage === "aggregate" && rows.length < MIN_GROUP_SIZE) {
      result[key] = null;
      notes.add(`Aggregate-only values are hidden for groups with fewer than ${MIN_GROUP_SIZE} records.`);
      continue;
    }
    if (["sum", "avg"].includes(metric.fn)) {
      const values = rows.map((row) => decimal(row[selected.name])).filter(Boolean);
      const ignored = rows.filter((row) => row[selected.name] !== null && row[selected.name] !== undefined).length - values.length;
      if (ignored) notes.add(`${ignored} non-numeric value(s) were ignored in ${key}.`);
      const total = values.reduce((sum, item) => sum.plus(item), new Decimal(0));
      result[key] = metric.fn === "sum" ? numberOut(total) : values.length ? numberOut(total.div(values.length)) : null;
      continue;
    }
    const candidates = rows.map((row) => row[selected.name]).filter((value) => comparable(value, zone));
    if (!candidates.length) { result[key] = null; continue; }
    const kinds = [...new Set(candidates.map((value) => comparable(value, zone)[0]))].sort();
    if (kinds.length > 1) notes.add(`${key} compared only ${kinds[0]} values.`);
    const filtered = candidates.filter((value) => comparable(value, zone)[0] === kinds[0]);
    filtered.sort((a, b) => compare(a, b, zone));
    result[key] = metric.fn === "min" ? filtered[0] : filtered.at(-1);
  }
  return result;
}

function sortRows(rows, key, direction, zone) {
  const order = { number: 0, date: 1, text: 2 };
  const sortValue = (value) => {
    const current = comparable(value, zone);
    return current?.[0] === "text" && decimal(value) ? ["number", decimal(value)] : current;
  };
  return [...rows].sort((a, b) => {
    const left = sortValue(a[key]); const right = sortValue(b[key]);
    if (!left) return right ? 1 : 0;
    if (!right) return -1;
    const category = order[left[0]] - order[right[0]];
    const comparison = category || (left[1] instanceof Decimal ? left[1].comparedTo(right[1])
      : left[1] > right[1] ? 1 : left[1] < right[1] ? -1 : 0);
    return direction === "desc" ? -comparison : comparison;
  });
}

export function prepareRows(rows, fields) {
  let hidden = 0;
  const prepared = rows.map((row) => {
    if (!object(row)) error("SCHEMA_MISMATCH", "Source records must be objects");
    const output = {};
    for (const [name, field] of Object.entries(fields)) {
      let value = row[name] ?? null;
      if ((value !== null && typeof value === "object") || (field.usage === "visible" && treeContainsPii(value))) {
        hidden++;
        value = null;
      }
      output[name] = value;
    }
    return output;
  });
  return { rows: prepared, hidden };
}

export function runReport(rows, spec, fields, zone) {
  validateSpec(spec, fields);
  const matched = rows.filter((row) => spec.filters.every((filter) => matches(row, filter, zone)));
  const notes = new Set();
  const grouped = !!(spec.group_by.length || spec.time_bucket);
  if (!grouped && !spec.metrics.length) {
    const columns = spec.columns.length ? spec.columns : Object.values(fields).filter((field) => field.usage === "visible").map((field) => field.name);
    const sorted = spec.sort ? sortRows(matched, spec.sort.by, spec.sort.direction, zone) : matched;
    return { mode: "records", columns, rows: sorted.slice(0, spec.limit).map((row) =>
      Object.fromEntries(columns.map((name) => [name, row[name] ?? null]))), totals: { count: matched.length },
    matched: matched.length, groups: null, notes: [] };
  }
  const metrics = spec.metrics.length ? spec.metrics : [{ fn: "count" }];
  const aliases = metrics.map(alias);
  const totals = metricsFor(matched, metrics, fields, zone, notes);
  if (!grouped) return { mode: "summary", columns: aliases, rows: [totals], totals,
    matched: matched.length, groups: null, notes: [...notes].sort() };
  const dimensions = [...spec.group_by, ...(spec.time_bucket ? ["period"] : [])];
  const buckets = new Map();
  for (const row of matched) {
    const values = spec.group_by.map((name) => row[name] ?? null);
    if (spec.time_bucket) values.push(bucket(row[spec.time_bucket.field], spec.time_bucket.interval, zone));
    const key = JSON.stringify(values);
    if (!buckets.has(key)) buckets.set(key, { values, rows: [] });
    buckets.get(key).rows.push(row);
  }
  let groupedRows = [...buckets.values()].map(({ values, rows: members }) => ({
    ...Object.fromEntries(dimensions.map((name, index) => [name, values[index]])),
    ...metricsFor(members, metrics, fields, zone, notes) }));
  const sortBy = spec.sort?.by ?? (spec.time_bucket && !spec.group_by.length ? "period" : aliases[0]);
  const direction = spec.sort?.direction ?? (sortBy === "period" ? "asc" : "desc");
  groupedRows = sortRows(groupedRows, sortBy, direction, zone);
  if (groupedRows.length > spec.limit) notes.add(`Showing the first ${spec.limit} of ${groupedRows.length} groups.`);
  return { mode: "groups", columns: [...dimensions, ...aliases], rows: groupedRows.slice(0, spec.limit), totals,
    matched: matched.length, groups: groupedRows.length, notes: [...notes].sort() };
}

function format(value) {
  if (value === null || value === undefined) return "(none)";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString("en-US")
    : value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return String(value).slice(0, 60);
}

export function summarize(result, { label: sourceLabel, scanned, coverage, truncated, filtered }) {
  let text = `${sourceLabel}: ${format(result.matched)} record(s)`;
  if (filtered) text += ` matched the filters out of ${format(scanned)} read`;
  if (coverage === "partial") text += truncated ? " (partial data: the scan stopped early)" : " (partial data)";
  const parts = [`${text}.`];
  if (result.mode === "records") parts.push(`Showing ${format(result.rows.length)}.`);
  else if (result.mode === "summary") parts.push(`Totals: ${Object.entries(result.totals).map(([key, value]) => `${key} ${format(value)}`).join(", ")}.`);
  else {
    const dimensions = result.columns.filter((name) => !(name in result.totals));
    const metric = result.columns.find((name) => name in result.totals);
    const listed = result.rows.slice(0, 5).map((row) => {
      const name = dimensions.map((dimension) => format(row[dimension])).join(" / ");
      const share = metric === "count" && result.matched && Number.isInteger(row[metric])
        ? ` (${Math.round(row[metric] / result.matched * 100)}%)` : "";
      return `${name}: ${format(row[metric])}${share}`;
    });
    if (listed.length) parts.push(`${format(result.groups)} group(s) by ${dimensions.join(", ")}; ${metric}: ${listed.join("; ")}.`);
  }
  return [...parts, ...result.notes].join(" ");
}

export function chartHint(result) {
  if (result.mode !== "groups") return null;
  const dimensions = result.columns.filter((name) => !(name in result.totals));
  if (dimensions.length !== 1) return null;
  return { type: dimensions[0] === "period" ? "line" : "bar", x: dimensions[0],
    y: result.columns.filter((name) => name in result.totals) };
}
