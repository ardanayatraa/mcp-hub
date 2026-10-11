<?php

namespace Tests\Unit;

use App\Services\Mcp\McpClient;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class McpClientTest extends TestCase
{
    public function test_list_tool_uses_structured_result(): void
    {
        $this->fakeToolResult([
            'structuredContent' => ['result' => [['name' => 'first'], ['name' => 'second']]],
            'content' => [['type' => 'text', 'text' => '{"name":"first"}']],
        ]);

        $this->assertSame(
            [['name' => 'first'], ['name' => 'second']],
            app(McpClient::class)->call('list_app_tools', ['app' => 'hireach'])
        );
        Http::assertSentCount(1);
        Http::assertSent(fn ($request) => $request['method'] === 'tools/call');
    }

    public function test_list_tool_reads_every_text_block_without_structured_result(): void
    {
        $this->fakeToolResult([
            'content' => [
                ['type' => 'text', 'text' => '{"name":"first"}'],
                ['type' => 'text', 'text' => '{"name":"second"}'],
            ],
        ]);

        $this->assertSame(
            [['name' => 'first'], ['name' => 'second']],
            app(McpClient::class)->call('list_app_tools', ['app' => 'hireach'])
        );
    }

    private function fakeToolResult(array $result): void
    {
        config(['ai.mcp.bridge_url' => 'http://127.0.0.1:8000/mcp']);
        Http::fake(function ($request) use ($result) {
            return Http::response([
                'jsonrpc' => '2.0',
                'id' => $request['id'],
                'result' => $request['method'] === 'initialize' ? [] : $result,
            ]);
        });
    }

    public function test_invalid_connections_send_no_requests(): void
    {
        Http::fake();
        config(['ai.mcp.hub.enabled' => true, 'ai.mcp.hub.token' => 'fixture-hub-token']);
        foreach (['bridge', 'hub'] as $connection) {
            foreach (['http://remote.example.test/mcp', 'https://user:secret@example.test/mcp',
                'https://example.test/mcp?token=secret', 'https://example.test/mcp#private',
                'file:///private', ''] as $url) {
                config([$connection === 'hub' ? 'ai.mcp.hub.url' : 'ai.mcp.bridge_url' => $url]);
                try {
                    app(McpClient::class)->rpc('tools/list', [], [], $connection);
                    $this->fail('Invalid connection was accepted');
                } catch (\RuntimeException $error) {
                    $this->assertSame('MCP connection is not configured.', $error->getMessage());
                }
            }
        }
        Http::assertNothingSent();
    }

    /** @dataProvider invalidResponses */
    public function test_transport_rejects_redirects_rpc_errors_and_oversized_responses(
        string $connection, int $status, array|string $body, array $headers
    ): void
    {
        config(['ai.mcp.bridge_url' => 'https://provider.example.test/mcp',
            'ai.mcp.hub.enabled' => true, 'ai.mcp.hub.url' => 'https://hub.example.test/mcp',
            'ai.mcp.hub.token' => 'fixture-hub-token']);
        Http::fake(fn () => Http::response($body, $status, $headers));
        try {
            app(McpClient::class)->rpc('tools/list', [], [], $connection);
            $this->fail('Invalid response was accepted');
        } catch (\RuntimeException $error) {
            $this->assertSame('MCP request failed.', $error->getMessage());
        }
        Http::assertSentCount(1);
    }

    public static function invalidResponses(): array
    {
        $cases = [];
        foreach (['bridge', 'hub'] as $connection) {
            foreach (['redirect' => [302, '', ['Location' => 'https://other.example.test/mcp']],
                'rpc-error' => [200, ['error' => ['message' => 'private-credential-canary']], []],
                'invalid-json' => [200, 'invalid-json', []], 'oversized' => [200, str_repeat('a', 1048577), []]] as $name => $case) {
                $cases[$connection.'-'.$name] = [$connection, ...$case];
            }
        }
        return $cases;
    }
}
