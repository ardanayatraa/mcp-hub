<?php

return [
    'app_key' => env('MCP_HUB_APP_KEY', 'your_app'),
    'environment' => env('MCP_HUB_ENVIRONMENT', env('APP_ENV', 'local')),
    'enabled' => env('MCP_HUB_ENABLED', env('MCP_HUB_URL', '') !== ''),
    'url' => env('MCP_HUB_URL'),
    'client_key' => env('MCP_HUB_CLIENT_KEY', env('MCP_HUB_TOKEN')),
    'source_url' => env('MCP_HUB_BASE_URL', env('MCP_HUB_SOURCE_URL', env('APP_URL'))),
    'app_token' => env('MCP_HUB_APP_TOKEN', env('MCP_HUB_SOURCE_KEY')),
    'delegation_secret' => env('MCP_HUB_DELEGATION_SECRET'),
    'require_https' => env('MCP_HUB_REQUIRE_HTTPS', env('APP_ENV') === 'production'),
    'timeout' => (int) env('MCP_HUB_TIMEOUT', 12),
    'protocol_version' => '2026-07-28',
    'routes' => ['enabled' => true, 'prefix' => 'api/ai/v1'],
    'actor_resolver' => \McpHub\Laravel\Security\DenyActorResolver::class,
    // Application-owned definitions only. No model, user class, or permission is assumed.
    'models' => [],
];
