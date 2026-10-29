<?php

namespace App\Services\Mcp;

use McpHub\Laravel\Connection;
use McpHub\Laravel\Registry;

final class HubPackageRegistry extends Registry
{
    public function manifest(Connection $connection): array
    {
        // Existing application settings remain the source of model and field grants.
        return McpResourceRegistry::manifest();
    }
}
