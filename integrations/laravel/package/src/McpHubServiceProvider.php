<?php

namespace McpHub\Laravel;

use Illuminate\Support\ServiceProvider;
use Illuminate\Support\Facades\Route;
use McpHub\Laravel\Contracts\ActorResolver;
use McpHub\Laravel\Http\ConnectorController;

final class McpHubServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->mergeConfigFrom(dirname(__DIR__).'/config/mcp-hub.php', 'mcp-hub');
        $this->app->bind(ActorResolver::class, function ($app) {
            $resolver = $app->make($app['config']->get('mcp-hub.actor_resolver'));
            if (! $resolver instanceof ActorResolver) {
                throw new \RuntimeException('Invalid actor resolver.');
            }
            return $resolver;
        });
    }

    public function boot(): void
    {
        $this->publishes([dirname(__DIR__).'/config/mcp-hub.php' => config_path('mcp-hub.php')], 'mcp-hub-config');
        if ($this->app->runningInConsole()) {
            $this->commands([Console\InstallCommand::class, Console\ConnectCommand::class, Console\DoctorCommand::class]);
        }
        if (config('mcp-hub.routes.enabled') && ! $this->app->routesAreCached()) {
            Route::prefix(trim(config('mcp-hub.routes.prefix'), '/'))->middleware('throttle:60,1')
                ->name('mcp-hub.')->group(function () {
                    Route::get('health', [ConnectorController::class, 'health'])->name('health');
                    Route::get('capabilities', [ConnectorController::class, 'capabilities'])->name('capabilities');
                    Route::get('{resource}/{action}', [ConnectorController::class, 'read'])
                        ->where('resource', '[a-z][a-z0-9_]{0,47}')->where('action', 'list|get|count')->name('read');
                });
        }
    }
}
