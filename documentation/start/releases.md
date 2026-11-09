# Release status and versions

## Laravel package

**`ardanayatraa/laravel-mcp-hub` 1.0.1** is the current stable release, published November 9, 2026. Install it with `^1.0`, without an `@alpha` flag or `-W`.

[Release and verified ZIP](https://github.com/ardanayatraa/laravel-mcp-hub/releases/tag/v1.0.1) · [Packagist](https://packagist.org/packages/ardanayatraa/laravel-mcp-hub) · [Version 1.0.1 CI](https://github.com/ardanayatraa/laravel-mcp-hub/actions/runs/42583066466)

Version 1.0.1 installs on a fresh Laravel 13 application, which ships Guzzle 8, and its Hub calls work without listing the application in the Hub's `ALLOWED_ORIGINS`. It also removes a PHP 8.2+ deprecation, gives the package's rate limits their own counters, and renders tables and lists in chat answers. No migration or configuration change is required; see the [Laravel upgrade guide](../laravel/upgrade.md). All 16 release jobs passed: 13 PHP/Laravel combinations, PostgreSQL, chat assets and distribution checks. The package suite collects 119 tests with two opt-in tests; PostgreSQL checks run separately. CI results are not a production capacity benchmark.

**1.0.0**, the first stable release (November 3, 2026), added pairing, SQL nonces, CRUD proposals, settings and chat, the Gateway SDK and private exports. [Release](https://github.com/ardanayatraa/laravel-mcp-hub/releases/tag/v1.0.0) · [Version 1.0.0 CI](https://github.com/ardanayatraa/laravel-mcp-hub/actions/runs/41553234044)

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

Effective PHP requirements depend on the host framework and dependencies. The matrix tests the reference patches listed in the [package README](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.1/README.md), rather than every patch combination. Package compatibility does not restore expired upstream security maintenance.

## Hub server

Hub documentation follows the Python edition on `main`. The Laravel package's stable version does not automatically become the server's release number. Review the server commit, database schema, and API contracts before a coordinated upgrade. The JavaScript edition on `mcp-js` is outside this operations guide.

Keep the host application's lock file and follow the [Laravel upgrade guide](../laravel/upgrade.md). Release corrections use a new patch version; published tags are not moved.
