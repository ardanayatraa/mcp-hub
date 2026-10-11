<?php

return [
    'models_cache_ttl' => (int) env('AI_MODELS_CACHE_TTL', 15),
    'request_timeout' => (int) env('AI_REQUEST_TIMEOUT', 210),
    'default_model' => env('AI_DEFAULT_MODEL', 'gh/gpt-4o-mini'),

    // Config allows operations; saved admin permissions still decide access per model.
    'crud' => [
        'read' => true,
        'create' => false,
        'update' => false,
        'delete' => false,
        'allow_hard_delete' => false,
        'proposal_ttl' => 300,
        // Optional business-rule overrides. Fields/rules otherwise follow each model's fillable and schema.
        'models' => [],
    ],

    // AI model bridge and user-owned data Hub connections.
    'mcp' => [
        'bridge_url' => env('MCP_BRIDGE_URL', 'http://127.0.0.1:8000/mcp'),
        'access_token' => env('MCP_BRIDGE_TOKEN', ''),
        'timeout' => (int) env('MCP_BRIDGE_TIMEOUT', 210),
        'ai_provider' => env('MCP_AI_PROVIDER', 'telixcell'),
        'ai_only' => true,

        // AI models use the bridge above; user-owned data tools use this Hub.
        'hub' => [
            'enabled' => (bool) env('MCP_HUB_ENABLED', false),
            'url' => env('MCP_HUB_URL', ''),
            'token' => env('MCP_HUB_TOKEN', ''),
            'source_url' => rtrim(env('MCP_HUB_SOURCE_URL', env('APP_URL', '')), '/'),
            'source_key' => env('MCP_HUB_SOURCE_KEY', ''),
            'delegation_secret' => env('MCP_HUB_DELEGATION_SECRET', ''),
            'timeout' => (int) env('MCP_HUB_TIMEOUT', 12),
        ],
    ],
];
