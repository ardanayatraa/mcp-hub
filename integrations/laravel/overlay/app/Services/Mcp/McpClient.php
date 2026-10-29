<?php

namespace App\Services\Mcp;

use App\Models\User;
use Illuminate\Support\Facades\Http;
use RuntimeException;

class McpClient
{
    private int $requestId = 0;

    public function call(string $name, array $arguments = [], array $headers = []): array
    {
        $result = $this->rpc('tools/call', [
            'name' => $name,
            'arguments' => $arguments === [] ? new \stdClass() : $arguments,
        ], $headers);
        if ($result['isError'] ?? false) {
            throw new RuntimeException('MCP tool failed.');
        }
        $structured = $result['structuredContent']['result'] ?? null;
        if (is_array($structured)) {
            return $structured;
        }

        $content = $result['content'] ?? null;
        if (! is_array($content) || $content === []) {
            throw new RuntimeException('Invalid MCP tool response.');
        }

        $decoded = [];
        foreach ($content as $block) {
            $text = $block['text'] ?? null;
            if (! is_string($text)) {
                throw new RuntimeException('Invalid MCP tool response.');
            }
            $value = json_decode($text, true);
            if (json_last_error() !== JSON_ERROR_NONE) {
                throw new RuntimeException('Invalid MCP tool response.');
            }
            $decoded[] = $value;
        }

        return count($decoded) === 1 && is_array($decoded[0]) ? $decoded[0] : $decoded;
    }

    public function query(string $app, string $tool, array $arguments = [], ?User $actor = null): array
    {
        if (McpHubClient::enabled()) {
            if ($app !== 'hireach' || ! $actor) {
                throw new RuntimeException('Hub user context is required.');
            }
            return app(McpHubClient::class)->query($tool, $arguments, $actor);
        }
        $delegated = $actor && $app === 'hireach'
            ? $actor->createToken('mcp-ai-query', ['mcp'])
            : null;

        try {
            $decoded = $this->call('query_app', [
                'app' => $app,
                'tool' => $tool,
                'arguments' => $arguments === [] ? new \stdClass() : $arguments,
            ], $delegated ? ['X-MCP-Delegated-Token' => $delegated->plainTextToken] : []);
        } finally {
            $delegated?->accessToken->delete();
        }
        if (! is_array($decoded) || ($decoded['app'] ?? null) !== $app
            || ($decoded['tool'] ?? null) !== $tool || ! is_array($decoded['result'] ?? null)) {
            throw new RuntimeException('Invalid MCP tool response.');
        }

        return $decoded['result'];
    }

    public function connectionStatus(User $actor): array
    {
        $status = ['models' => false, 'data' => false];
        try {
            $catalog = $this->call('list_ai_models');
            $status['models'] = is_array($catalog['data'] ?? null) && $catalog['data'] !== [];
        } catch (\Throwable $error) {
            // Report only connection status; provider errors may contain private details.
        }
        try {
            if (McpHubClient::enabled()) {
                app(McpHubClient::class)->testConnection($actor);
            } else {
                $this->call('list_app_tools', ['app' => 'hireach']);
            }
            $status['data'] = true;
        } catch (\Throwable $error) {
            // An enabled Hub never falls back to the legacy data bridge after failure.
        }
        return $status;
    }

    public function rpc(string $method, array $params, array $headers = [], string $connection = 'bridge'): array
    {
        if (! in_array($connection, ['bridge', 'hub'], true)) {
            throw new RuntimeException('Unknown MCP connection.');
        }
        if ($connection === 'hub') {
            return app(\McpHub\Laravel\HubClient::class)->rpc($method, $params, $headers);
        }
        $url = (string) config('ai.mcp.bridge_url');
        $token = (string) config('ai.mcp.access_token', '');
        $parts = parse_url($url);
        $scheme = strtolower((string) ($parts['scheme'] ?? ''));
        $host = strtolower((string) ($parts['host'] ?? ''));
        if (! is_array($parts) || $host === '' || ($scheme !== 'https'
            && ! ($scheme === 'http' && app()->environment(['local', 'testing'])
                && in_array($host, ['localhost', '127.0.0.1', '::1'], true)))
            || isset($parts['user']) || isset($parts['pass']) || isset($parts['query']) || isset($parts['fragment'])) {
            throw new RuntimeException('MCP connection is not configured.');
        }

        $request = Http::withHeaders(array_merge(['Accept' => 'application/json, text/event-stream'], $headers))
            ->withoutRedirecting()->connectTimeout(3)
            ->timeout((int) config('ai.mcp.timeout', 210));
        if ($token !== '') {
            $request = $request->withToken($token);
        }
        $response = $request->post($url, [
            'jsonrpc' => '2.0',
            'id' => ++$this->requestId,
            'method' => $method,
            'params' => $params,
        ]);
        $body = strlen($response->body()) <= 1048576 ? $response->json() : null;
        if (! $response->successful() || ! is_array($body) || isset($body['error'])
            || ! is_array($body['result'] ?? null)) {
            throw new RuntimeException('MCP request failed.');
        }

        return $body['result'];
    }
}
