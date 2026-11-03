# Resources and permissions

A resource defines a model, allowed fields, filters, and application policy. The database is never exposed automatically.

## Discover candidates

```bash
php artisan mcp-hub:discover
php artisan mcp-hub:discover --schema
php artisan make:mcp-resource orders --model='App\Models\Order'
```

Discovery reads metadata, not business records. The generator creates **disabled** definitions in `config/mcp-hub-resources`, denial policies, and related application classes. Review them before enabling grants.

## Resolve actors

Implement `McpHub\Laravel\Contracts\ActorResolver`:

```php
public function forUser(Authenticatable $user): Actor;
public function resolve(string $userReference, string $tenant): Actor;
```

`forUser` derives identity from the server's authenticated user. `resolve` rechecks account status and tenant membership for a signed reference. Return a consistent actor or deny access; model arguments must never establish identity.

This configuration assumes that you have implemented the application classes:

```php
'actor_resolver' => \App\Mcp\ActorResolver::class,
'models' => [
    'orders' => [
        'model' => \App\Models\Order::class,
        'policy' => \App\Mcp\OrderPolicy::class,
        'enabled' => true,
        'read' => true,
        'lookup' => 'title',
        'fields' => [
            'title' => 'string',
            'status' => 'string',
            'total' => 'number',
        ],
        'filters' => ['status' => ['paid', 'pending']],
    ],
],
```

## Policies and record scope

`ResourcePolicy` separates action permission from query restrictions:

```php
public function allows(Actor $actor, string $resource, string $action): bool;
public function scope(Builder $query, Actor $actor): Builder;
```

`allows` checks current permissions; `scope` restricts the entire query by tenant, ownership, and host visibility rules. Column and role names depend on your application. UI filters or model-supplied tenant IDs are not a security boundary.

Test inactive accounts, other tenants, other users' records, and revoked permissions. Do not add sensitive fields to the allowlist. `limit` and `cursor` are reserved pagination parameters.

## References and grants

Default references are opaque and encrypted, bound to the source, environment, resource, actor, and tenant. A reference does not replace query scope. Administrator grants only narrow the developer's permissions. Generated tool keys must fit the Hub's 80-character limit.

After review, sync the manifest and verify the catalog using a restricted client. See the [source contract](../reference/connector-contract.md) for schemas and response envelopes.
