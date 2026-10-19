import assert from "node:assert/strict";
import test from "node:test";
import { chartHint, parseSpec, prepareRows, runReport, sourceFields, summarize } from "../server/core/report.js";

const schema = { type: "array", items: { type: "object", properties: {
  ref: { type: "string" }, status: { type: "string", enum: ["open", "closed"] },
  created_at: { type: "string" }, amount: { type: "number" }, salary: { type: "number" },
  owner_email: { type: "string" }, secret_note: { type: "string" },
} } };
const policies = { ref: "allowed_for_ai", status: "allowed_for_ai", created_at: "allowed",
  amount: "allowed_for_ai", salary: "aggregate_only", owner_email: "allowed_for_ai", secret_note: "blocked" };
const fields = sourceFields(schema, policies);
const rows = [
  { ref: "a", status: "open", created_at: "2026-10-01T20:00:00+00:00", amount: 10, salary: 100 },
  { ref: "b", status: "Open", created_at: "2026-10-02T08:00:00+08:00", amount: "2.50", salary: 300 },
  { ref: "c", status: "closed", created_at: "2026-09-30", amount: null, salary: 200 },
  { ref: "d", status: null, created_at: null, amount: 7, salary: 400 },
];
const run = (spec) => runReport(rows, parseSpec(spec), fields, "Asia/Singapore");

test("report filters, groups and hides small aggregate-only values", () => {
  assert.deepEqual(Object.keys(fields), ["ref", "status", "created_at", "amount", "salary"]);
  assert.deepEqual(run({ filters: [{ field: "status", op: "eq", value: "OPEN" }] }).rows.map((row) => row.ref), ["a", "b"]);
  assert.deepEqual(run({ filters: [{ field: "amount", op: "gte", value: 2.5 }] }).rows.map((row) => row.ref), ["a", "b", "d"]);
  assert.deepEqual(run({ filters: [{ field: "created_at", op: "between", value: ["2026-09-30", "2026-10-02"] }] }).rows.map((row) => row.ref), ["a", "b", "c"]);
  const grouped = run({ group_by: ["status"], metrics: [{ fn: "count" }, { fn: "sum", field: "amount" }, { fn: "avg", field: "salary" }] });
  assert.deepEqual(grouped.totals, { count: 4, sum_amount: 19.5, avg_salary: 250 });
  assert.ok(grouped.rows.every((row) => row.avg_salary === null));
  assert.ok(grouped.notes.some((note) => note.includes("fewer than 3")));
});

test("report buckets use source timezone and numeric sorting keeps null last", () => {
  assert.deepEqual(run({ time_bucket: { field: "created_at", interval: "day" } }).rows.map((row) => [row.period, row.count]),
    [["2026-09-30", 1], ["2026-10-02", 2], [null, 1]]);
  assert.deepEqual(run({ sort: { by: "amount", direction: "desc" }, columns: ["ref", "amount"], limit: 3 }).rows,
    [{ ref: "a", amount: 10 }, { ref: "d", amount: 7 }, { ref: "b", amount: "2.50" }]);
});

test("report policy and value masking match the Python contract", () => {
  assert.throws(() => run({ group_by: ["salary"] }), { code: "POLICY_LOCKED" });
  assert.throws(() => run({ metrics: [{ fn: "sum", field: "status" }] }), { code: "VALIDATION_FAILED" });
  const prepared = prepareRows([{ ref: "x", status: "mail canary@example.com", salary: 5,
    amount: { nested: 1 } }], fields);
  assert.equal(prepared.hidden, 2);
  assert.equal(prepared.rows[0].salary, 5);
  const grouped = run({ group_by: ["status"] });
  assert.equal(chartHint(grouped).type, "bar");
  assert.match(summarize(grouped, { label: "Demo · Orders", scanned: 4,
    coverage: "partial", truncated: true, filtered: false }), /^Demo · Orders: 4 record\(s\) \(partial data/);
});
