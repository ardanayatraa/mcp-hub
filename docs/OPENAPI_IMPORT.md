# Reviewed OpenAPI draft import

Unreleased admin feature. OpenAPI documents describe candidates; the current
application capability manifest and field policies remain the authority.
Import never enables a module, publishes a tool, changes credentials or calls a
business operation. A tool still needs the normal test and publication steps.

The importer supports the bounded JSON/YAML subset of OpenAPI 3.0, 3.1 and 3.2
that maps to the Hub's scalar inputs and record outputs. It accepts pasted or
uploaded text, or a network-allowlisted HTTPS document URL. Remote downloads use
the existing pinned-DNS egress guard, TLS verification, no redirects, no
application credentials, a five-second timeout and a 512 KiB limit.

| POST route under `/api/admin/v1/tools/openapi` | Request | Response |
|---|---|---|
| `/preview` | `connector_id`, exactly one of `document` or `source_url`, `format` (`json` or `yaml`) | Fingerprint and operation candidates with eligibility, parameters, output fields and auth metadata |
| `/import` | Same source plus the preview `fingerprint` and 1–20 selected candidate IDs | New draft tool IDs; all selections succeed together or none are created |

Both routes require the admin session, CSRF, a write role and application scope.
Source-managed connectors keep deriving their tools from application code;
manual import applies to manually reviewed HTTP connectors only. Preview does
not persist the raw document or its examples. Import rechecks the document hash,
current source contract and policies. A changed remote document returns 409 and
requires another preview. Existing tool names are never overwritten.

Only GET/POST/PUT/PATCH/DELETE operations matching an approved source route are
eligible. Document server hints must resolve under the configured connector
base; they cannot introduce another destination. Parameter names must be a
subset of that route's reviewed inputs and retain its required inputs. Drafts
reuse the reviewed source input constraints. Outputs are restricted to the
intersection of documented, approved and currently AI-visible fields. Write
receipts must retain the source's required receipt fields. Source authentication,
tenant context and approval requirements remain unchanged. Spec descriptions,
examples, security keys and scripts are never executed or copied as credentials.

Local component references are resolved with depth and expansion limits. Remote
references, recursive references, YAML aliases/merge keys/custom tags, duplicate
keys, executable/custom extensions and oversized documents are rejected. Nested
or binary operation inputs and unsupported response shapes are ineligible; they
are not silently turned into free-form schemas.

Reference: [OpenAPI Specification](https://spec.openapis.org/oas/v3.1.1.html).
