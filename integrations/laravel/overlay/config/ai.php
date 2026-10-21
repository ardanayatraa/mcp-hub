<?php

return [
    'models_cache_ttl' => (int) env('AI_MODELS_CACHE_TTL', 15),
    'request_timeout' => (int) env('AI_REQUEST_TIMEOUT', 210),
    'default_model' => env('AI_DEFAULT_MODEL', 'gh/gpt-4o-mini'),

    // Config allows operations; saved admin permissions still decide access per model.
    'crud' => [
        'read' => true,
        'create' => true,
        'update' => true,
        'delete' => true,
        'allow_hard_delete' => false,
        'proposal_ttl' => 300,
        // Optional business-rule overrides. Fields/rules otherwise follow each model's fillable and schema.
        // Writes are denied unless a model has a Laravel policy or an authorize rule here (least privilege).
        'models' => [
            \App\Models\BillingUser::class => ['operations' => ['update'],
                'authorize' => [\App\Services\AI\AiToolAccessGuard::class, 'ownBillingProfile']],
        ],
    ],

    // AI model bridge and user-owned data Hub connections. The names the Hub's connect screen prints
    // (MCP_HUB_CLIENT_KEY, MCP_HUB_APP_TOKEN, MCP_HUB_BASE_URL) win; the older names keep working.
    'mcp' => [
        // Without MCP_BRIDGE_*, models come from the Hub's model gateway next to MCP_HUB_URL, with the client key.
        'bridge_url' => env('MCP_BRIDGE_URL', env('MCP_HUB_URL')
            ? preg_replace('#/mcp$#', '/gateway/mcp', rtrim((string) env('MCP_HUB_URL'), '/'))
            : 'http://127.0.0.1:8000/mcp'),
        'access_token' => env('MCP_BRIDGE_TOKEN', env('MCP_HUB_CLIENT_KEY', '')),
        'timeout' => (int) env('MCP_BRIDGE_TIMEOUT', 210),
        'ai_provider' => env('MCP_AI_PROVIDER', 'telixcell'),
        'ai_only' => true,

        // AI models use the bridge above; user-owned data tools use this Hub.
        'hub' => [
            // On once a Hub URL is set; the Hub shares the bridge token unless given its own.
            'enabled' => (bool) env('MCP_HUB_ENABLED', env('MCP_HUB_URL', '') !== ''),
            'url' => env('MCP_HUB_URL', ''),
            'token' => env('MCP_HUB_CLIENT_KEY', env('MCP_HUB_TOKEN', env('MCP_BRIDGE_TOKEN', ''))),
            'source_url' => rtrim(env('MCP_HUB_BASE_URL', env('MCP_HUB_SOURCE_URL', env('APP_URL', ''))), '/'),
            'source_key' => env('MCP_HUB_APP_TOKEN', env('MCP_HUB_SOURCE_KEY', '')),
            'delegation_secret' => env('MCP_HUB_DELEGATION_SECRET', ''),
            'timeout' => (int) env('MCP_HUB_TIMEOUT', 12),
            // Refuse connector calls over plain HTTP; on by default in production (behind a proxy, trust it in TrustProxies).
            'require_https' => (bool) env('MCP_HUB_REQUIRE_HTTPS', env('APP_ENV') === 'production'),
        ],
    ],
];
