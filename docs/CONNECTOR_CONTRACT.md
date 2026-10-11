# Connector contract

What a connected application implements so the Hub can serve its data to AI clients.
The application owns its records and its permissions. The Hub calls a small authenticated
JSON API; it never introspects an ORM or a database.

## Permissions managed by the application

An admin can choose `connector_type: source_managed` once when connecting a trusted
application. Its authenticated manifest must declare `managed_by: application` and
include only the models, operations and fields currently granted by that application's
admin. Each reviewed endpoint supplies a stable `tool_key` such as `your_app.orders.list`
and an optional safe description. Keys must belong to the manifest's application/module.
An explicitly empty `modules: []` revokes all generated tools and is valid in this mode.

Before every authenticated MCP tool list and allowed call, the Hub fetches and validates
this manifest, reconciles source policies and creates/updates/disables generated tools
atomically. There is no separate enable/test/publish workflow per model. A failed or invalid
policy fetch denies discovery/calls rather than using old grants. Sync calls only the
manifest endpoint; it never reads business records or sends write requests.

Admin Apps, data-source and Tools lists also refresh authorized active source-managed
connectors before reading their catalog. Removed/disabled grants are excluded from
these lists and counts. Retired metadata remains available as history; it does not
grant access. Failed refreshes return an error rather than displaying old grants as current.

The connected application remains responsible for record ownership, user status, current
permissions and any write confirmation. Hub privacy rules, fixed routes, signed delegation,
client write scope, allowlists and revocation still apply. Client keys cannot change mode,
register a different source or widen their scopes. Mode changes return the connector to
draft; test, discover and activate it once. Hub model/tool editing is locked in source mode.
Manual `http_contract` connectors retain their existing review and publication workflow.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/ai/v1/health` (configurable) | Authenticated health. Body `{"status": "ok"}`. |
| GET | `/api/ai/v1/capabilities` (configurable) | The capability manifest below. |
| as declared | each route in `read_endpoints` | One reviewed read: GET, or POST marked `safe_query: true`. |
| as declared | each route in `write_endpoints` (optional) | One reviewed create, update or delete request. |

Paths are relative to the base URL the admin enters. The Hub refuses redirects, private or
metadata addresses (unless explicitly allowed for development), and any route that is not
in the manifest.

## Authentication

Every request carries the app's service credential: `X-API-Key: <key>` or
`Authorization: Bearer <token>`, as chosen when connecting. The Hub stores it encrypted.

A service credential proves the Hub may call the app. It does not prove which user is
asking. For user-scoped routes:

1. The **app's AI gateway** (or any trusted caller) sends `X-Hub-Delegation` to the Hub with
   each MCP call. This is an HMAC-SHA256 token signed with the app's delegation secret:
   `base64url(json) + "." + base64url(hmac)`, where the JSON is
   `{"app_key", "tenant_id", "user_ref", "aud": "mcp-hub", "exp"}` and `exp` is at most
   150 seconds ahead (mint for 120 s or less).
2. The Hub verifies it, then sends the app `X-Hub-Assertion`. This is a 60-second token
   signed with the same secret, with `aud` set to the connector's base URL.
3. The app verifies the assertion and re-checks the user, tenant, permissions and records
   on **every** request.

Model-supplied arguments named `user_id`, `tenant_id`, `role`, `approved`, `url`, `path`,
`method`, `token` and similar are rejected and can never establish authorization.

## Manifest

```json
{
  "contract_version": "1.0",
  "application": "telixmart",
  "manifest_version": "2026-10-10.1",
  "modules": [{
    "key": "orders",
    "name": "Orders",
    "description": "Orders the signed-in user may see",
    "schema_version": "1.0",
    "supported_operations": ["read", "create"],
    "readable_fields": ["ref", "status", "total", "created_at"],
    "writable_fields": ["note"],
    "field_policies": {"total": "aggregate_only"},
    "max_page_size": 50,
    "read_endpoints": [{
      "method": "GET", "path_template": "/api/ai/v1/orders/list",
      "requires_user_context": true, "tenant_field": "tenant_id",
      "input_schema": {"type": "object", "additionalProperties": false, "properties": {
        "status": {"type": "string", "enum": ["open", "paid", "void"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        "cursor": {"type": "string", "maxLength": 64}}},
      "output_schema": {"type": "array", "maxItems": 50, "items": {"type": "object", "additionalProperties": false,
        "required": ["ref", "status", "total", "created_at"],
        "properties": {"ref": {"type": "string", "maxLength": 64},
                       "status": {"type": "string", "enum": ["open", "paid", "void"]},
                       "total": {"type": "number"},
                       "created_at": {"type": "string", "maxLength": 64}}}}
    }],
    "write_endpoints": [{
      "operation": "create", "method": "POST", "path_template": "/api/ai/v1/orders/propose",
      "requires_user_context": true, "tenant_field": "tenant_id",
      "input_schema": {"type": "object", "additionalProperties": false, "required": ["note"],
                       "properties": {"note": {"type": "string", "maxLength": 200}}},
      "output_schema": {"type": "array", "maxItems": 1, "items": {"type": "object", "additionalProperties": false,
        "required": ["proposal_ref", "summary"],
        "properties": {"proposal_ref": {"type": "string", "maxLength": 64}, "summary": {"type": "string", "maxLength": 300}}}}
    }]
  }]
}
```

Rules the Hub enforces when it syncs the manifest:

- `application` equals the app key entered in the Hub. Module keys are lowercase identifiers.
- **Readable fields** are an allowlist. Each field starts *Visible to AI* unless `field_policies` says otherwise (`blocked`, `secure_form_only`, `aggregate_only`). Names that indicate personal or secret data (email, phone, password, token, national id, `user_id`, `tenant_id`, …, including variants such as `owner_email` or `contactPhone`) are always blocked and locked. Admins can tighten a field, or relax it back to your declared level, never beyond.
- **Schemas** are closed (`additionalProperties: false`). Inputs are scalars with bounds or small string enums. Outputs are arrays of flat records with scalar (optionally nullable) fields that come from `readable_fields`. No `$ref`.
- **User-scoped routes** set `requires_user_context: true` and `tenant_field`. Every returned row must contain the tenant field. The Hub drops rows for other tenants (and marks the answer `partial`), then removes the field before anything reaches the AI.
- **Public routes** (no user context) must say `"public_aggregate": true` and return only data that anyone with the client key may see.
- **Write routes** are optional. `operation` must be in `supported_operations`; inputs must be declared readable or writable fields and never personal data; user context is mandatory; the output is a small receipt. A write is enableable only when its route is declared.
- Pagination: a list route that accepts `limit` (integer) and `cursor` (string) and returns `meta.has_more` + `meta.next_cursor` can be read page by page by `run_report`.

A changed module is switched off in the Hub until an admin reviews it, and its tools need
a new test. Unchanged modules keep working.

## Responses

Reads:

```json
{"success": true,
 "data": [{"ref": "ord_1", "status": "paid", "total": 120.5, "created_at": "2026-10-01T09:00:00+08:00", "tenant_id": "t_1"}],
 "meta": {"as_of": "2026-10-10T09:00:00+08:00", "timezone": "Asia/Makassar", "scope": "authorized_records",
          "coverage": "complete", "total_count": 1, "has_more": false, "next_cursor": null}}
```

`as_of` is timezone-aware; `timezone` is an IANA name; `coverage` is `complete` or
`partial`. A page that is not the last one is `partial` with `has_more: true`. Never put
personal data in `meta`, cursors or error messages.

Write receipts use the same envelope. `data` holds one record with the declared receipt
fields plus the tenant field. `meta.requires_confirmation: true` tells the AI that nothing
changed yet and the user must confirm in your app. The Hub sends an `Idempotency-Key`
header with every write and never retries one.

Errors: `{"success": false, "error": {"code": "PERMISSION_DENIED", "message": "Operation is not permitted"}}`
with 401, 403, 404, 409, 422 or 429. The Hub forwards only the codes `PERMISSION_DENIED`,
`VALIDATION_FAILED`, `NOT_FOUND`, `RATE_LIMITED` and `SCHEMA_MISMATCH`; anything else
becomes `UPSTREAM_ERROR`.

## Laravel sketch

The admin UI's **Laravel guide** (Docs → Laravel guide) builds the complete contract with a
downloadable starter kit: list, get, prepare create/update/delete, proposals the user confirms,
and a feature test for every path. The minimum read route looks like this:

```php
// routes/api.php
Route::prefix('ai/v1')->middleware('hub.key')->group(function () {
    Route::get('health', fn () => ['status' => 'ok']);
    Route::get('capabilities', [HubController::class, 'manifest']);
    Route::get('orders/list', [HubController::class, 'orders']);
});

// HubController::orders: the user comes from the verified assertion, never from input.
public function orders(Request $request)
{
    $user = HubAssertion::verify($request->header('X-Hub-Assertion'));   // HMAC, aud, exp, active user
    abort_unless($user->can('orders.read'), 403);
    $validated = $request->validate(['status' => 'in:open,paid,void', 'limit' => 'integer|min:1|max:50',
                                     'cursor' => 'regex:/^page_\d{1,6}$/']);
    $query = Order::whereBelongsTo($user)->when($validated['status'] ?? null, fn ($q, $s) => $q->where('status', $s));
    $offset = (int) substr($validated['cursor'] ?? 'page_0', 5);
    $limit = $validated['limit'] ?? 50;
    $total = (clone $query)->count();
    $rows = $query->orderByDesc('id')->skip($offset)->take($limit)->get(['id', 'status', 'total', 'created_at'])
        ->map(fn ($o) => ['ref' => 'ord_'.$o->id, 'status' => $o->status, 'total' => (float) $o->total,
                          'created_at' => $o->created_at->toAtomString(), 'tenant_id' => 'user_'.$user->id]);
    $more = $offset + $rows->count() < $total;
    return ['success' => true, 'data' => $rows, 'meta' => [
        'as_of' => now()->toAtomString(), 'timezone' => config('app.timezone'), 'scope' => 'authorized_records',
        'coverage' => $more ? 'partial' : 'complete', 'total_count' => $total, 'has_more' => $more,
        'next_cursor' => $more ? 'page_'.($offset + $rows->count()) : null]];
}
```

Keep the field list explicit (never `Model::all()`), select only declared fields, and
compute aggregates at the source when individual values are sensitive.

The [reference app](../reference/your_app/app.py) implements the contract in Python,
including a create route that only returns a proposal.
