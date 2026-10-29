<?php

namespace McpHub\Laravel;

use Illuminate\Support\Facades\Http;
use RuntimeException;
use Throwable;

final class HubClient
{
    private int $requestId = 0;

    public function __construct(private Connection $connection)
    {
    }

    public function rpc(string $method, array $params = [], array $headers = []): array
    {
        if (! in_array($method, ['tools/list', 'tools/call'], true)) {
            throw new RuntimeException('Unsupported Hub operation.');
        }
        $url = (string) $this->connection->get('url', '');
        $token = (string) $this->connection->get('client_key', '');
        $parts = parse_url($url);
        $local = app()->environment(['local', 'testing']) && in_array(strtolower($parts['host'] ?? ''),
            ['localhost', '127.0.0.1', '::1'], true);
        if (! $this->connection->get('enabled') || $token === '' || ! is_array($parts)
            || empty($parts['host']) || (($parts['scheme'] ?? '') !== 'https'
                && !(($parts['scheme'] ?? '') === 'http' && $local))
            || isset($parts['user']) || isset($parts['pass']) || isset($parts['query']) || isset($parts['fragment'])) {
            throw new RuntimeException('MCP Hub connection is not configured.');
        }
        $version = (string) $this->connection->get('protocol_version');
        $params['_meta'] = ['io.modelcontextprotocol/protocolVersion' => $version,
            'io.modelcontextprotocol/clientCapabilities' => new \stdClass(),
            'io.modelcontextprotocol/clientInfo' => ['name' => 'laravel-mcp-hub', 'version' => '2.0.0-alpha']];
        $safeHeaders = ['Accept' => 'application/json, text/event-stream', 'MCP-Protocol-Version' => $version,
            'MCP-Method' => $method, 'Origin' => (string) $this->connection->get('source_url')];
        if (isset($params['name'])) {
            $safeHeaders['MCP-Name'] = $params['name'];
        }
        if (isset($headers['X-Hub-Delegation'])) {
            $safeHeaders['X-Hub-Delegation'] = $headers['X-Hub-Delegation'];
        }
        try {
            $response = Http::withHeaders($safeHeaders)->withToken($token)->withoutRedirecting()
                ->connectTimeout(3)->timeout(max(1, min(120, (int) $this->connection->get('timeout', 12))))
                ->post($url, ['jsonrpc' => '2.0', 'id' => ++$this->requestId, 'method' => $method,
                    'params' => $params === [] ? new \stdClass() : $params]);
            if (! $response->successful() || strlen($response->body()) > 1048576) {
                throw new RuntimeException('Hub request failed.');
            }
            $body = $response->json();
            if (! is_array($body)) {
                // Streamable HTTP can return a JSON-RPC response in an SSE event.
                foreach (preg_split('/\r?\n\r?\n/', $response->body()) as $event) {
                    $data = [];
                    foreach (preg_split('/\r?\n/', $event) as $line) {
                        if (str_starts_with($line, 'data:')) {
                            $data[] = ltrim(substr($line, 5), ' ');
                        }
                    }
                    $candidate = json_decode(implode("\n", $data), true);
                    if (is_array($candidate) && ($candidate['id'] ?? null) === $this->requestId) {
                        $body = $candidate;
                        break;
                    }
                }
            }
            if (! is_array($body) || ($body['id'] ?? null) !== $this->requestId
                || isset($body['error']) || ! is_array($body['result'] ?? null)) {
                throw new RuntimeException('Invalid Hub response.');
            }
            return $body['result'];
        } catch (Throwable $error) {
            // Upstream errors may contain credentials or business data.
            throw new RuntimeException('MCP Hub request failed.');
        }
    }
}
