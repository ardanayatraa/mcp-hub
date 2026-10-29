<?php

namespace McpHub\Laravel\Console;

use Illuminate\Console\Command;

final class InstallCommand extends Command
{
    protected $signature = 'mcp-hub:install {--dry-run}';
    protected $description = 'Publish missing MCP Hub configuration without replacing application settings';

    public function handle(): int
    {
        $target = config_path('mcp-hub.php');
        if (is_file($target)) {
            $this->info('Configuration already exists; no changes made.');
        } elseif ($this->option('dry-run')) {
            $this->info('Would create config/mcp-hub.php with no registered models.');
        } elseif (! copy(dirname(__DIR__, 2).'/config/mcp-hub.php', $target)) {
            $this->error('Configuration could not be written.');
            return 1;
        } else {
            $this->info('Configuration installed. No models or permissions were enabled.');
        }
        return 0;
    }
}
