# Private report exports

CSV, XLSX, and PDF files are generated in Laravel. The Hub receives job receipts and status, not the report file. This is separate from the JSON analytics provided by `run_report`.

## Enable exports

```php
'exports' => [
    'enabled' => true,
    'ttl' => 600,
    'connection' => 'database',
    'queue' => 'default',
],
```

Add the required `exports` formats to a reviewed resource, for example `['csv', 'xlsx', 'pdf']`. Its policy must allow both `list` and `export` for the current actor. Define the export Gate and migrate package metadata.

The host's queue backend must already exist; the package does not create that infrastructure. For a database queue:

```bash
php artisan queue:work database --queue=default --tries=1 --timeout=60
```

Production rejects the `sync` driver. Set `retry_after` above the worker timeout, such as 90 seconds for a 60-second timeout.

## Limits and defaults

| Limit | Value |
|---|---|
| TTL | 30–900 seconds; default 600 |
| Active exports | 2 per actor, 40 per installation |
| Records | 1–500; default 200 |
| PDF | At most 100 records |
| Columns | At most 10 reviewed fields |
| File size | At most 5 MiB |

```json
{"format":"xlsx","columns":"title,status,total","limit":200,"status":"paid"}
```

POST requires a fresh assertion and an `Idempotency-Key` of 16–128 letters, digits, underscores, or hyphens. Query strings and inputs outside the schema are rejected. Aggregates cover only selected records; `coverage: partial` is not a complete population total.

## Storage and downloads

Web and queue workers must share the database, APP_KEY, configuration, and private `storage/app/mcp-hub` filesystem. Files are encrypted and must not be published or symlinked to a public disk. This workflow does not support workers with independent local storage.

Downloads recheck the session, Gate, actor and tenant, grants, format, expiry, and current query/record snapshot. A link alone grants no access. Changed data or grants cause a conflict requiring a new export; expired downloads return 410.

A crashed worker can leave a job unavailable until expiry. Create a new request and key rather than manually replaying the job. Run the host scheduler for periodic pruning.

[Complete export contract](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/EXPORTS.md)
