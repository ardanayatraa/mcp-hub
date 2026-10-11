<?php

namespace App\Services\Mcp;

use App\Models\User;
use App\Services\AI\AiResourceExecutor;
use RuntimeException;

class McpHubClient
{
    public static function enabled(): bool
    {
        return (bool) config('ai.mcp.hub.enabled');
    }

    public function openaiTools(User $actor): array
    {
        McpActorIdentity::active($actor);
        $available = $this->rpc('tools/list', [])['tools'] ?? [];
        $definitions = array_column($available, null, 'name');
        $out = [];
        $executor = app(AiResourceExecutor::class);
        foreach (McpResourceRegistry::tools() as $name => $tool) {
            $permitted = isset($tool['phase']) ? $executor->canWrite($tool['resource'], $tool['action']) : $executor->canRead($tool['resource']);
            if (! $permitted || ! isset($definitions[$tool['mcp_name']])) { continue; }
            $out[] = ['type' => 'function', 'function' => ['name' => $name, 'description' => $tool['description'],
                'parameters' => $definitions[$tool['mcp_name']]['inputSchema']]];
        }
        // Existing native exports stay inside Hireach's authenticated file route.
        if ($out !== []) {
            foreach ($executor->openaiTools($actor) as $tool) {
                if ($tool['function']['name'] === 'export_report') { $out[] = $tool; }
            }
        }
        return $out;
    }

    public function testConnection(?User $actor = null): void
    {
        $listed = $this->rpc('tools/list', [])['tools'] ?? null;
        if (! is_array($listed)) { throw new RuntimeException('Hireach Hub tool list is invalid.'); }
        $executor = app(AiResourceExecutor::class);
        $tools = array_filter(McpResourceRegistry::tools(), fn ($tool) => isset($tool['phase'])
            ? $executor->canWrite($tool['resource'], $tool['action']) : $executor->canRead($tool['resource']));
        // An empty registration list still allows testing the Hub connection.
        if ($tools === []) { return; }
        if (! array_intersect(array_column($listed, 'name'), array_column($tools, 'mcp_name'))) {
            throw new RuntimeException('Hireach Hub tools are unavailable.');
        }
        if ($actor) {
            $checked = 0;
            foreach ($tools as $name => $tool) {
                if ($tool['action'] !== 'count') { continue; }
                $resource = $tool['resource'];
                if (app(AiResourceExecutor::class)->canRead($resource)
                    && in_array($tool['mcp_name'], array_column($listed, 'name'), true)) {
                    $this->query($name, [], $actor);
                    $checked++;
                }
            }
            if ($checked === 0) { throw new RuntimeException('Hireach resource access is disabled.'); }
        }
    }

    public function query(string $name, array $arguments, User $actor): array
    {
        $tool = McpResourceRegistry::tools()[$name] ?? null;
        $executor = app(AiResourceExecutor::class);
        if (! $tool || (isset($tool['phase']) ? ! $executor->canWrite($tool['resource'], $tool['action']) : ! $executor->canRead($tool['resource']))) {
            throw new RuntimeException('Hub tool access denied.');
        }
        $actor = McpActorIdentity::active($actor);
        $result = $this->rpc('tools/call', ['name' => $tool['mcp_name'],
            'arguments' => $arguments ?: new \stdClass()], ['X-Hub-Delegation' => McpActorIdentity::sign($actor, 'mcp-hub')]);
        if (($result['isError'] ?? false) === true) { throw new RuntimeException('Hub tool request denied.'); }
        $body = $result['structuredContent'] ?? null;
        if (! is_array($body)) {
            $body = json_decode($result['content'][0]['text'] ?? '', true);
        }
        if (! is_array($body) || ($body['success'] ?? false) !== true || ! is_array($body['data'] ?? null)
            || ! is_array($body['meta'] ?? null) || ($body['meta']['contains_personal_data'] ?? null) !== false) {
            throw new RuntimeException('Hub tool response is invalid.');
        }
        $data = $tool['action'] === 'list' ? $body['data'] : ($body['data'][0] ?? []);
        if (isset($tool['phase'])) {
            $pending = $executor->proposal((string) ($data['proposal_ref'] ?? ''), $actor);
            if ($pending['resource'] !== $tool['resource'] || $pending['action'] !== $tool['action']) {
                throw new RuntimeException('Hub proposal response is invalid.');
            }
            $data = ['proposal_ref' => $data['proposal_ref'], 'summary' => $pending['summary'], 'requires_confirmation' => true];
        }
        return ['resource' => $tool['label'], 'action' => $tool['action'], 'data' => $data,
            'meta' => $body['meta'], 'trace_id' => $body['trace_id'] ?? null];
    }

    private function rpc(string $method, array $params, array $headers = []): array
    {
        return app(McpClient::class)->rpc($method, $params, $headers, 'hub');
    }
}
