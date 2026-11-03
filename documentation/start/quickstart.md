# Implementation paths

Choose a starting point based on the components you already have. Examples use `example.com` and the app key `your_app`; replace them with your environment's identity.

## Start from scratch

1. [Run the Hub locally](../hub/local.md) and sign in to the admin UI.
2. Register a source URL and stable app key.
3. [Install the Laravel package](../laravel/install.md) in a test application.
4. Complete [pairing](../laravel/connection.md).
5. Implement your resolver and policies, then review the [resources](../laravel/resources.md).
6. Create a read-only client key and verify the catalog and user scope.

## Connect to an existing Hub

```bash
composer require ardanayatraa/laravel-mcp-hub:^1.0
php artisan mcp-hub:install --dry-run --migrate
php artisan mcp-hub:install --migrate
php artisan mcp-hub:connect --hub=https://hub.example.com
php artisan mcp-hub:doctor --online
```

Enter the pairing code at the hidden prompt. The Hub must be able to reach the application's source URL. Production metadata migrations require `--force` after the host application's normal backup and review process.

!!! note "An empty resource catalog is the expected starting state"
    Installation does not automatically expose tables. Resources become available after the developer registers models, fields, identity resolution, and valid policies.

## First integration acceptance checks

- Health and Doctor report readiness.
- The client sees only reviewed resources.
- User or tenant A cannot read records belonging to B.
- Revoking permission blocks the next request.
- A model allowlist and budget are configured when using the gateway or chat.

Once reads work, add [CRUD proposals](../laravel/commands.md) or [private exports](../laravel/exports.md) as needed.
