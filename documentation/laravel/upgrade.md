# Upgrades and maintenance

A Composer update is part of the application release process, not a substitute for reviewing production configuration and migrations.

## Upgrade from alpha to 1.0

1. Keep consistent backups of the database, lock file, configuration, resource definitions, and private storage.
2. Preserve APP_KEY and credentials through the host's secret management.
3. Update the dependency to `ardanayatraa/laravel-mcp-hub:^1.0` in a reviewed build.
4. Check conflicts and audits without platform or security bypasses.
5. Review and run package metadata migrations.
6. Restart queue and long-running workers, then check Doctor and status before switching traffic.

```bash
php artisan mcp-hub:install --dry-run --migrate
php artisan mcp-hub:install --migrate --force
php artisan mcp-hub:doctor --online
php artisan mcp-hub:status
```

Production requires `--force` after backup and review. The installer preserves existing configuration; add optional keys without replacing the whole host file.

## Existing integrations

If the host already owns connector routes, retain `routes.enabled=false` until an equivalent replacement is verified. Preserve the resolver, resource registry, policies, scope, handlers, and UI. A generic package does not reconstruct business permissions.

Pending proposals from older development snapshots may need to be prepared again. Do not move pending metadata between installations or environments. Version 1.0 uses opaque references by default.

## Scheduling

The provider registers hourly pruning with an overlap lock. The host must still run Laravel's scheduler.

```bash
php artisan mcp-hub:prune --days=30
```

If the host schedules pruning itself, set `maintenance.scheduled_prune=false` to avoid duplicate tasks. Terminal receipt retention accepts 1–365 days; expired payloads and artifacts have their own cleanup rules. The command touches package metadata and files only.

## Recovery

Roll back code and the lock file through the host's procedure. Do not automatically downgrade schemas or delete tables. New metadata can remain unused until the cause is reviewed.

File rollback does not restore revoked credentials. Use pairing resume or replacement. APP_KEY rotation requires a separate file and queue recovery plan; the package does not rotate it automatically.

[Complete upgrade and recovery guide](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/UPGRADE.md)
