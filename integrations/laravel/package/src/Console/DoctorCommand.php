<?php

namespace McpHub\Laravel\Console;

use Illuminate\Console\Command;
use McpHub\Laravel\Connection;
use McpHub\Laravel\HubClient;
use McpHub\Laravel\Registry;
use Throwable;

final class DoctorCommand extends Command
{
    protected $signature = 'mcp-hub:doctor {--online} {--json}';
    protected $description = 'Check configuration and optionally list Hub tools without reading records';

    public function handle(Connection $connection, Registry $registry, HubClient $client): int
    {
        $checks = [];
        try {
            $checks['application_key'] = preg_match('/^[a-z][a-z0-9_]{0,62}$/D', (string) $connection->get('app_key')) === 1;
            $checks['app_token'] = strlen((string) $connection->get('app_token')) >= 32;
            $checks['delegation_secret'] = strlen((string) $connection->get('delegation_secret')) >= 32;
            $checks['client_key'] = (string) $connection->get('client_key') !== '';
            $checks['manifest'] = is_array($registry->manifest($connection));
            $checks['shared_cache'] = app()->environment(['local', 'testing']) || ! in_array(config('cache.default'), ['array', 'null'], true);
            if ($this->option('online')) {
                $checks['hub_tools'] = is_array($client->rpc('tools/list')['tools'] ?? null);
            }
        } catch (Throwable $error) {
            $checks['operation'] = false;
        }
        if ($this->option('json')) {
            $this->line(json_encode(['checks' => $checks, 'ok' => ! in_array(false, $checks, true)], JSON_THROW_ON_ERROR));
        } else {
            foreach ($checks as $name => $ok) {
                $this->line($name.': '.($ok ? 'OK' : 'FAIL'));
            }
        }
        return in_array(false, $checks, true) ? 1 : 0;
    }
}
