# Release status and versions

## Laravel package

**`ardanayatraa/laravel-mcp-hub` 1.0.0** is the first stable release, published November 3, 2026. Install it with `^1.0`, without an `@alpha` flag.

[Release and verified ZIP](https://github.com/ardanayatraa/laravel-mcp-hub/releases/tag/v1.0.0) · [Packagist](https://packagist.org/packages/ardanayatraa/laravel-mcp-hub) · [Version 1.0.0 CI](https://github.com/ardanayatraa/laravel-mcp-hub/actions/runs/41553234044)

The release includes pairing, SQL nonces, CRUD proposals, settings and chat, the Gateway SDK, and private exports. All 16 release jobs passed: 13 PHP/Laravel combinations, PostgreSQL, chat assets, and distribution checks. The package suite collects 116 tests with two opt-in tests; PostgreSQL checks run separately. CI results are not a production capacity benchmark.

## Tested compatibility

| Laravel | PHP |
|---|---|
| 5.8 | 7.2, 7.4 |
| 6 | 7.2 |
| 7 | 7.2 |
| 8 | 7.3 |
| 9 | 8.0, 8.2 |
| 10 | 8.1 |
| 11 | 8.2 |
| 12 | 8.2, 8.4 |
| 13 | 8.3, 8.4 |

Effective PHP requirements depend on the host framework and dependencies. The matrix tests the reference patches listed in the [package README](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/README.md), rather than every patch combination. Package compatibility does not restore expired upstream security maintenance.

## Hub server

Hub documentation follows the Python edition on `main`. The Laravel package's stable version does not automatically become the server's release number. Review the server commit, database schema, and API contracts before a coordinated upgrade. The JavaScript edition on `mcp-js` is outside this operations guide.

Keep the host application's lock file and follow the [Laravel upgrade guide](../laravel/upgrade.md). Release corrections use a new patch version; the 1.0.0 tag is not moved.
