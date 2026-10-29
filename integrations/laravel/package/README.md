# Laravel MCP Hub Connector

The public MIT release is now available as
[ardanayatraa/laravel-mcp-hub](https://packagist.org/packages/ardanayatraa/laravel-mcp-hub),
with its standalone source at
[GitHub](https://github.com/ardanayatraa/laravel-mcp-hub).
This directory retains the existing local pilot dependency; the public release
has its own repository, standalone tests and version tags.

Local alpha for Laravel 9 and 12. The package has **no registered business models by default**. Model definitions, actor identity, record scope, and permission rules belong to the installing application.

The [PRD](PRD.md) describes the full planned product. This alpha provides authenticated source health/manifest/read routes, an explicit resource registry, signed actor assertions with replay protection, a Hub MCP transport, encrypted connection import, and install/doctor commands.

One-time Hub pairing, the settings UI, the legacy release line, and the complete Laravel 5.8–13 compatibility matrix remain planned. They are not implemented or claimed as supported by this alpha.

## Install in a development application

Add this directory as a Composer path repository, then require mcp-hub/laravel-connector at dev-main. The source checkout must remain available while using the path repository.

~~~bash
composer require mcp-hub/laravel-connector:dev-main
php artisan mcp-hub:install
php artisan mcp-hub:connect --import-env
php artisan mcp-hub:doctor
~~~

Configure the existing MCP_HUB_* connection values supplied by the Hub. The import command saves an encrypted copy under storage/app/mcp-hub and never prints credentials. Installation does not provision a Hub connector, enable models, or rotate keys.

The config defaults include:

~~~php
'actor_resolver' => \McpHub\Laravel\Security\DenyActorResolver::class,
'models' => [],
~~~

An application implements ActorResolver to identify active users and their tenant context, and ResourcePolicy for authorization and query scope. It then supplies reviewed model definitions, or replaces Registry through the container to use its own dynamic permissions. No App namespace, user table, ownership column, or product model is assumed by the package.

The modern sandbox contains an example. Its Order model, OrderPolicy, and demo actor resolver are application files, not package defaults. Writes are not exposed by the generic alpha source.

## Existing adapter integration

The local application's existing MCP gateway can delegate Hub HTTP calls to HubClient while retaining its original source endpoints, model settings, actor checks, write confirmations, chat and report code. Its application-specific container bindings adapt its existing configuration. This avoids replacing working domain authorization during the alpha.

## Verification

From the modern sandbox:

~~~bash
php artisan test --filter=ConnectorTest
php artisan config:cache
php artisan route:cache
php artisan config:clear
php artisan route:clear
~~~

The Postman mock is derived from the local Hub RPC contract and current adapter. It only models tools/list; unmodeled routes return 501. No external owner mock was needed for this repository-owned API.

From the repository root, start the simulation:

~~~bash
postman simulation run integrations/laravel/package/postman/simulations/connector.sim.yaml --port 18130 --output ndjson
~~~

Set MCP_HUB_SIM_URL to http://127.0.0.1:18130/hub/mcp for HubSimulationTest. This exercises the actual PHP HTTP transport against the stand-in, not the real Hub. Runtime config and credentials are dummy values.

With the sandbox running on port 18120, verify-sandbox.py checks actual source HTTP responses against the real Python Hub manifest validator and verifies both accounts' scopes and replay rejection.
