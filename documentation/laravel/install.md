# Install Laravel MCP Hub 1.0

The `ardanayatraa/laravel-mcp-hub` package provides source connectors and a server SDK for Laravel applications. It assumes no particular user model, business table, permission package, or billing system.

## Prerequisites

Use PHP and Laravel versions from the [compatibility matrix](../start/releases.md), Composer, and the extensions required by dependency resolution. You need a stable `APP_KEY`, a metadata database, a Hub reachable from the application, and a source URL reachable from the Hub.

```bash
composer require ardanayatraa/laravel-mcp-hub:^1.0
php artisan mcp-hub:install --dry-run --migrate
```

Review the plan, then run:

```bash
php artisan mcp-hub:install --migrate
```

Production requires `--migrate --force` after the application's normal backup and review process. This command runs only package migration files, not application business migrations or application schema dumps.

## Installation artifacts

| Artifact | Contents |
|---|---|
| `config/mcp-hub.php` | Initial configuration, only if the file does not exist |
| `mcp_hub_nonces` | Replay prevention through SQL uniqueness |
| `mcp_hub_commands` | Proposals and transaction receipts |
| `mcp_hub_exports` | Private report metadata |

Laravel discovers the provider automatically. If the host disables package discovery, register `McpHub\Laravel\McpHubServiceProvider` using the provider mechanism for your Laravel version.

## Default state

The default resolver denies identity, the model registry is empty, and writes and exports are disabled. Installation does not grant data access. Implement a resolver and policies before enabling resources.

```bash
php artisan mcp-hub:doctor
php artisan mcp-hub:status
```

Doctor may report incomplete configuration before pairing. Continue with [pairing and configuration](connection.md).

!!! note "The local prototype is a different dependency"
    `mcp-hub/laravel-connector` is the old pilot dependency. It shares the public package's PHP namespace, so both must not be installed together. Review dependencies, routes, and host integrations before replacing it.
