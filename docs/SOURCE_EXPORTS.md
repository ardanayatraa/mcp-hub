# Source-owned exports

The development Laravel package prepares private CSV, XLSX and PDF reports in the
source application. The Hub passes only bounded report arguments and receives job
metadata. It never fetches the generated file or stores the report's business rows.
This is separate from the existing `run_report` JSON analytics tool.

Defaults enable no exports. The host developer must enable the feature and
specific resource formats, allow `export` plus `list` in its current resource
policy, and configure the authenticated web export Gate. Existing readable-field
grants, value privacy checks and tenant/record scopes still apply. No model class
or application permission is assumed.

## Discovered tools

The source manifest declares these as actor-scoped read endpoints:

| Tool suffix | Source method/path | Behavior |
| --- | --- | --- |
| `export` | POST `/{resource}/exports` | Prepare a private queue job; `safe_query=true` |
| `export_status` | GET `/{resource}/exports/{export_ref}` | Check that actor's job |

Paths use the application's configured API prefix. Both endpoints require the
source service token and a fresh signed user assertion. A read-only client key
can invoke them only if its app/module/tool restrictions permit them. A scoped
MCP profile must include the discovered tools explicitly. Laravel rechecks its
independent export permission regardless of the Hub key's scope.

Every POST receives a trace/method/path/argument-bound idempotency key. The Hub
does not retry POST calls. The source refuses reused keys with different input.

Arguments are closed scalars: required `format` (`csv`, `xlsx`, `pdf`), optional
comma-separated reviewed `columns`, `limit`, registered enum filters, and
`metric`/numeric `field`/`group_by` for bounded aggregates. No identity arguments,
SQL, formula, arbitrary filter or destination URL is accepted. Limits are at most
500 rows and ten columns; PDF is at most 100 rows. Partial coverage describes the
selected subset and must not be presented as a complete population total.

## Receipts and chat

The ordinary source `success/data/meta` envelope contains one receipt with:

- `export_ref`: opaque actor-bound reference;
- `status`: pending, building, ready, failed or expired;
- `format`, `expires_at`, `coverage`, `row_count`;
- `download_url`: null until ready, otherwise a trusted configured source URL.

The internal source `tenant_id` is removed by the Hub's output guard. There are
no file bytes or business records in the receipt. Status remains reconcilable
after the background worker finishes; a failed job does not mean an empty report.

Hub chat emits `export` events and includes an `exports` list in its final result.
Each entry has `tool`, `title`, `trace_id` and `data`, where `data` contains only
validated `export_ref`, `status` and `format` fields. The package widget builds its
own same-origin authenticated download route from a ready reference. It never
turns model prose or a source-supplied URL into a download anchor. Check status in
a later turn when the job is initially pending.

## Download and worker boundary

The Laravel download route uses its own session and export Gate. A URL/reference
alone grants no access. It re-resolves the current user and tenant, verifies
current resource/field/format permissions, then rechecks the bounded policy-scoped
record/value/version snapshot. Changed data or visibility requires a new export.
Another actor receives 404; expired artifacts receive 410. Responses are
attachments with no-store/nosniff headers.

Queue jobs contain an opaque reference only. Encrypted metadata and files remain
on the application's private filesystem. Production requires an asynchronous
queue; web and queue workers must share private storage, database, APP_KEY and
configuration. TTL is bounded to 30–900 seconds; capacity is two active jobs per
actor and forty per installation. The host Laravel scheduler runs package pruning.
The connector does not alter production queues, cron, credentials or public disks.

The package's `EXPORTS.md` contains installation, queue and format details. Stable
publication still requires the remaining compatibility and application migration
gates in [STABLE_RELEASE.md](STABLE_RELEASE.md).
