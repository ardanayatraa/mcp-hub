<?php

namespace McpHub\Laravel\Console;

use Illuminate\Console\Command;
use McpHub\Laravel\Connection;
use Throwable;

final class ConnectCommand extends Command
{
    protected $signature = 'mcp-hub:connect {--import-env : Save an already provisioned connection} {--dry-run}';
    protected $description = 'Import existing Hub credentials without changing grants or rotating keys';

    public function handle(Connection $connection): int
    {
        if (! $this->option('import-env')) {
            $this->error('This alpha uses existing Hub provisioning. Set MCP_HUB_* and pass --import-env.');
            return 2;
        }
        try {
            $keys = ['app_key', 'environment', 'url', 'client_key', 'source_url', 'app_token', 'delegation_secret'];
            $values = [];
            foreach ($keys as $key) {
                $value = $connection->get($key);
                if (! is_string($value) || trim($value) === '') {
                    $this->error('Missing connection setting: '.$key);
                    return 2;
                }
                $values[$key] = $value;
            }
            foreach (['app_token', 'delegation_secret'] as $key) {
                if (strlen($values[$key]) < 32) {
                    $this->error('Invalid connection setting: '.$key);
                    return 2;
                }
            }
            if (! $this->option('dry-run')) {
                $connection->save($values);
            }
            $this->info($this->option('dry-run') ? 'Connection settings are present; no changes made.'
                : 'Connection settings saved encrypted. Run mcp-hub:doctor --online to verify connectivity.');
            return 0;
        } catch (Throwable $error) {
            $this->error('Connection could not be imported. Credentials were not printed.');
            return 1;
        }
    }
}
