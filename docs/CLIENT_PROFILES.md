# MCP access profiles

Contract for the stable-release implementation. One MCP runtime serves logical,
application-bound access profiles; a URL is never an authorization grant.

- `GET /api/admin/v1/mcp-profiles?app_id=...` lists profiles within the admin's app scope.
- `POST /api/admin/v1/mcp-profiles` creates a profile with `app_id`, `name`, optional
  `enabled` (default false), `modules` (default empty) and `tools` (default empty).
- `PATCH /api/admin/v1/mcp-profiles/{id}` requires the current integer `revision`;
  name, enablement, module and tool restrictions may be updated. Stale edits return 409.
- Client-key creation/update accepts nullable `profile_id`. Omission preserves
  existing behavior; an explicit null removes this restriction and requires the
  same write-role/app authority as changing the key's other permissions.

All writes require the admin session and CSRF. Modules/tools must belong to the
same app. Profiles cannot enable modules, expose fields, grant write scope, change
model budgets or override the connected application's authorization. An empty
list grants no access in that dimension. A key's own tool allowlist intersects
with the profile. Reports and source discovery obey the profile's module list.

Profiles are disabled rather than deleted. Disabling blocks bound client keys on
their next request. Foreign, missing and disabled bindings fail closed. Existing
keys without a profile remain compatible. Skills only appear when all their tools
remain callable. Profile restrictions cover MCP tools and Hub chat tools; model
gateway model/budget policy remains configured per application.

Replacing connector enrollment credentials preserves the old key's profile and
tool allowlist, including a disabled profile. Replacement never grants write
scope. Renewal preserves the same identity and its restrictions.
