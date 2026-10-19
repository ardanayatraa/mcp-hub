<?php

namespace Tests\Feature;

use App\Models\User;
use App\Services\AI\AiChatOrchestrator;
use App\Services\Mcp\McpHubClient;
use App\Services\Mcp\McpResourceRegistry;
use App\Services\Mcp\McpActorIdentity;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Schema;
use Tests\TestCase;

class McpConnectorTest extends TestCase
{
    private User $owner;
    private string $key = 'isolated-source-api-key-32-characters';
    private string $secret = 'isolated-delegation-secret-32-characters';

    protected function setUp(): void
    {
        parent::setUp();
        // Never migrate, clear, or insert into the developer's MySQL database.
        config(['database.connections.hub_fixture' => ['driver' => 'sqlite', 'database' => ':memory:',
            'prefix' => '', 'foreign_key_constraints' => true], 'database.default' => 'hub_fixture',
            'cache.default' => 'array', 'session.driver' => 'array', 'logging.default' => 'stderr',
            'ai.mcp.hub.enabled' => true, 'ai.mcp.hub.source_key' => $this->key,
            'ai.mcp.hub.delegation_secret' => $this->secret, 'ai.mcp.hub.source_url' => 'http://source.test',
            'ai.mcp.hub.url' => 'http://127.0.0.1:18000/mcp', 'ai.mcp.hub.token' => 'isolated-hub-token',
            'ai.mcp.ai_only' => false]);
        Schema::create('users', function (Blueprint $t) {
            $t->id(); $t->string('name'); $t->string('email'); $t->string('password');
            $t->string('status')->nullable(); $t->softDeletes(); $t->timestamps();
        });
        Schema::create('ai_integrations', function (Blueprint $t) {
            $t->id(); $t->string('name'); $t->string('api_url'); $t->boolean('enabled');
            $t->text('permissions'); $t->timestamp('last_used_at')->nullable(); $t->timestamps();
        });
        Schema::create('role_user', function (Blueprint $t) {
            $t->id(); $t->unsignedBigInteger('user_id'); $t->string('status'); $t->boolean('active');
        });
        Schema::create('team_user', function (Blueprint $t) {
            $t->id(); $t->unsignedBigInteger('user_id'); $t->unsignedBigInteger('team_id'); $t->string('role');
        });
        Schema::create('templates', function (Blueprint $t) {
            $t->id(); $t->unsignedBigInteger('user_id'); $t->string('name'); $t->string('type');
            $t->boolean('is_enabled'); $t->text('description'); $t->softDeletes(); $t->timestamps();
        });
        Schema::create('blast_messages', function (Blueprint $t) {
            $t->id(); $t->unsignedBigInteger('user_id'); $t->string('title'); $t->string('type');
            $t->string('status'); $t->string('msisdn'); $t->text('message_content'); $t->softDeletes(); $t->timestamps();
        });
        foreach ([1, 2] as $id) {
            DB::table('role_user')->insert(['user_id' => $id, 'status' => 'active', 'active' => true]);
            DB::table('users')->insert(['id' => $id, 'name' => 'Dummy', 'email' => 'dummy'.$id.'@example.test',
                'password' => 'not-a-password', 'status' => 'active', 'created_at' => now(), 'updated_at' => now()]);
            DB::table('templates')->insert(['id' => $id, 'user_id' => $id, 'name' => 'Welcome '.$id,
                'type' => 'text', 'is_enabled' => true, 'description' => 'hidden.canary@example.com', 'created_at' => now(), 'updated_at' => now()]);
            DB::table('blast_messages')->insert(['id' => $id, 'user_id' => $id, 'title' => 'Campaign '.$id,
                'type' => 'sms', 'status' => 'FAILED', 'msisdn' => '6281234567890', 'message_content' => 'Private OTP',
                'created_at' => now(), 'updated_at' => now()]);
        }
        DB::table('templates')->insert(['id' => 3, 'user_id' => 1, 'name' => 'Welcome extra', 'type' => 'text',
            'is_enabled' => true, 'description' => 'private', 'created_at' => now(), 'updated_at' => now()]);
        $this->permissions(true);
        $this->owner = User::query()->findOrFail(1);
    }

    private function permissions(bool $enabled): void
    {
        DB::table('ai_integrations')->updateOrInsert(['id' => 1], ['name' => 'Dummy integration', 'api_url' => 'mcp://telixcell',
            'enabled' => true, 'permissions' => json_encode([
                '_resources' => [
                    'templates' => ['model' => \App\Models\Template::class, 'label' => 'Templates',
                        'owner' => 'user_id', 'lookup' => 'name', 'ref_prefix' => 'tpl_',
                        'fields' => ['name' => 'string', 'type' => 'string:64', 'is_enabled' => 'boolean', 'created_at' => 'datetime']],
                    'blast_messages' => ['model' => \App\Models\BlastMessage::class, 'label' => 'Blast Messages',
                        'owner' => 'user_id', 'lookup' => 'title', 'ref_prefix' => 'blast_',
                        'fields' => ['title' => 'string', 'type' => 'string:64', 'status' => 'string:64', 'created_at' => 'datetime'],
                        'filters' => ['status' => ['SUCCESS', 'FAILED']]],
                ],
                'templates' => ['enabled' => $enabled, 'read' => $enabled, 'scope' => 'current_user'],
                'blast_messages' => ['enabled' => true, 'read' => true, 'scope' => 'current_user'],
            ]), 'created_at' => now(), 'updated_at' => now()]);
    }

    private function headers(?string $token = null): array
    {
        return ['Authorization' => 'Bearer '.$this->key, 'X-Hub-Assertion' => $token ?? McpActorIdentity::sign($this->owner, 'http://source.test')];
    }

    public function test_empty_admin_registrations_expose_no_resources_even_with_old_permissions_or_config(): void
    {
        $this->assertArrayNotHasKey('resources', config('ai'));
        $this->assertArrayNotHasKey('legacy_resources', config('ai'));
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        $formerRegistrations = $permissions['_resources'];
        unset($permissions['_resources']);
        $integration->update(['permissions' => $permissions]);
        // Stale deployment configuration must not restore access from a second source.
        config(['ai.resources' => $formerRegistrations, 'ai.legacy_resources' => $formerRegistrations]);
        foreach ([true, false] as $hubEnabled) {
            config(['ai.mcp.hub.enabled' => $hubEnabled]);
            $this->assertSame([], McpResourceRegistry::resources());
            $this->assertSame([], McpResourceRegistry::tools());
            $this->assertSame([], \App\Services\AI\AiResourceExecutor::resources());
            $this->assertSame([], \App\Http\Livewire\Table\AiAccessTable::permissionResources());
            if ($hubEnabled) {
                $this->getJson('/api/ai/v1/capabilities', $this->headers())->assertOk()->assertJsonCount(0, 'modules');
                $this->getJson('/api/ai/v1/templates/count', $this->headers())->assertStatus(403);
            }
        }
        $this->assertDatabaseCount('templates', 3);
        $this->assertSame($permissions, $integration->fresh()->permissions);
    }

    public function test_empty_admin_registration_allows_connection_test_without_calling_data_tools(): void
    {
        $this->grantFixtureAdminRole();
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $integration->update(['permissions' => []]);
        config(['ai.mcp.bridge_url' => 'http://127.0.0.1:18082/mcp', 'ai.mcp.ai_provider' => 'telixcell']);
        $invalidHubResponse = false;
        Http::fake(function ($request) use (&$invalidHubResponse) {
            $result = $request->url() === config('ai.mcp.hub.url')
                ? ($invalidHubResponse ? [] : ['tools' => [['name' => 'hireach__templates__count']]])
                : ['structuredContent' => ['result' => ['data' => [['id' => 'fixture-model']]]]];
            return Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => $result]);
        });
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->assertSet('resources', [])->call('testConnection')->assertEmitted('tested')
            ->assertSet('connectionStatus', ['models' => true, 'data' => true]);
        $this->assertSame([], app(McpHubClient::class)->openaiTools($this->owner));
        Http::assertNotSent(fn ($request) => $request->url() === config('ai.mcp.hub.url') && $request['method'] === 'tools/call');
        $this->assertSame([], $integration->fresh()->permissions);
        $invalidHubResponse = true;
        $this->expectException(\RuntimeException::class);
        $this->expectExceptionMessage('Hireach Hub tool list is invalid.');
        app(McpHubClient::class)->testConnection($this->owner);
    }

    public function test_admin_can_add_first_model_without_saving_initial_settings(): void
    {
        DB::table('ai_integrations')->delete();
        $this->contactSettings()->call('saveResource')->assertHasNoErrors()
            ->assertSet('integration.enabled', true)->assertSet('resources.contacts.read', false)
            ->assertSet('resources.contacts.enabled', false);
        $this->assertDatabaseCount('ai_integrations', 1);
        $this->assertSame(['contacts'], array_keys(McpResourceRegistry::resources()));
        $this->getJson('/api/ai/v1/contacts/count', $this->headers())->assertStatus(403);
    }

    public function test_service_auth_and_reviewed_manifest(): void
    {
        $this->getJson('/api/ai/v1/health')->assertStatus(401);
        // The service key is accepted only as a bearer token.
        $this->getJson('/api/ai/v1/health', ['X-API-Key' => $this->key])->assertStatus(401);
        $this->getJson('/api/ai/v1/health', $this->headers())->assertOk();
        $this->getJson('/api/ai/v1/capabilities', $this->headers())->assertOk()
            ->assertJsonPath('application', 'hireach')->assertJsonCount(2, 'modules')
            ->assertJsonCount(3, 'modules.0.read_endpoints');
        $this->postJson('/api/ai/v1/templates/list', [], $this->headers())->assertStatus(405);
    }

    public function test_manifest_follows_saved_grants_and_global_service_switch(): void
    {
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $original = $integration->permissions;
        foreach (['read', 'enabled'] as $flag) {
            $permissions = $original;
            $permissions['templates'][$flag] = false;
            $integration->update(['permissions' => $permissions]);
            $this->getJson('/api/ai/v1/capabilities', $this->headers())->assertOk()
                ->assertJsonPath('managed_by', 'application')->assertJsonCount(1, 'modules')
                ->assertJsonPath('modules.0.key', 'blast_messages');
        }
        $integration->update(['permissions' => $original, 'enabled' => false]);
        $this->getJson('/api/ai/v1/capabilities', $this->headers())->assertOk()->assertJsonPath('modules', []);
        $integration->update(['permissions' => $original, 'enabled' => true]);
        $this->getJson('/api/ai/v1/capabilities', $this->headers())->assertOk()
            ->assertJsonPath('modules.0.read_endpoints.0.tool_key', 'hireach.templates.list');
        $permissions = $original;
        unset($permissions['_resources']['templates']);
        $integration->update(['permissions' => $permissions]);
        $this->assertSame(['blast_messages'], array_column(McpResourceRegistry::manifest()['modules'], 'key'));
    }

    public function test_manifest_exports_only_admin_allowed_crud_proposals(): void
    {
        $this->configureCrudFixture();
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        $permissions['templates']['update'] = false;
        $permissions['templates']['delete'] = false;
        $integration->update(['permissions' => $permissions]);
        $module = collect(McpResourceRegistry::manifest()['modules'])->firstWhere('key', 'templates');
        $this->assertSame(['read', 'create'], $module['supported_operations']);
        $this->assertSame(['hireach.templates.prepare_create'], array_column($module['write_endpoints'], 'tool_key'));
        $this->assertStringEndsWith('/prepare_create', $module['write_endpoints'][0]['path_template']);
    }

    public function test_rows_counts_and_pagination_are_current_user_scoped(): void
    {
        $page = $this->getJson('/api/ai/v1/templates/list?limit=1', $this->headers())->assertOk()
            ->assertJsonPath('meta.total_count', 2)->assertJsonPath('meta.coverage', 'partial')
            ->assertJsonPath('data.0.name', 'Welcome extra');
        $this->getJson('/api/ai/v1/templates/list?limit=1&cursor='.$page->json('meta.next_cursor'), $this->headers())
            ->assertOk()->assertJsonPath('data.0.name', 'Welcome 1')
            ->assertJsonPath('meta.has_more', false)->assertJsonPath('meta.coverage', 'complete');
        $this->getJson('/api/ai/v1/templates/count', $this->headers())->assertOk()->assertJsonPath('data.0.count', 2);
        $this->getJson('/api/ai/v1/blast_messages/list', $this->headers())->assertOk()
            ->assertJsonCount(1, 'data')->assertJsonPath('data.0.title', 'Campaign 1')
            ->assertDontSee('6281234567890')->assertDontSee('Private OTP')->assertDontSee('msisdn');
        $this->getJson('/api/ai/v1/templates/get?name=Welcome%202', $this->headers())->assertOk()->assertJsonCount(0, 'data');
    }

    public function test_missing_forged_expired_and_wrong_audience_assertions_deny(): void
    {
        foreach (['', 'bad.signature', McpActorIdentity::sign($this->owner, 'mcp-hub'), $this->assertion(['exp' => time() - 1]),
            $this->assertion(['tenant_id' => 'hireach_account_2']), $this->assertion(['exp' => time() + 3600])] as $token) {
            $this->getJson('/api/ai/v1/templates/list', ['Authorization' => 'Bearer '.$this->key, 'X-Hub-Assertion' => $token])->assertStatus(403);
        }
    }

    public function test_duplicate_names_return_newest_own_record_with_partial_coverage(): void
    {
        DB::table('templates')->insert(['id' => 4, 'user_id' => 1, 'name' => 'Welcome 1', 'type' => 'text',
            'is_enabled' => true, 'description' => 'private', 'created_at' => now(), 'updated_at' => now()]);
        $this->getJson('/api/ai/v1/templates/get?name=Welcome%201', $this->headers())->assertOk()
            ->assertJsonPath('data.0.ref', 'tpl_4')->assertJsonPath('meta.total_count', 2)
            ->assertJsonPath('meta.coverage', 'partial');
    }

    private function assertion(array $changes): string
    {
        $payload = array_merge(['app_key' => 'hireach', 'aud' => 'http://source.test', 'exp' => time() + 60,
            'user_ref' => 'hireach_user_1', 'tenant_id' => 'hireach_account_1'], $changes);
        $raw = json_encode($payload);
        $encode = fn ($v) => rtrim(strtr(base64_encode($v), '+/', '-_'), '=');
        return $encode($raw).'.'.$encode(hash_hmac('sha256', $raw, $this->secret, true));
    }

    public function test_revoked_user_and_disabled_resource_deny_cached_calls(): void
    {
        $token = McpActorIdentity::sign($this->owner, 'http://source.test');
        $this->permissions(false);
        $this->getJson('/api/ai/v1/templates/list', $this->headers($token))->assertStatus(403);
        $this->permissions(true);
        DB::table('users')->where('id', 1)->update(['status' => 'inactive']);
        $this->getJson('/api/ai/v1/templates/list', $this->headers($token))->assertStatus(403);
    }

    public function test_query_cannot_override_user_and_limits_are_enforced(): void
    {
        $this->getJson('/api/ai/v1/templates/list?user_id=2', $this->headers())->assertStatus(403);
        $this->getJson('/api/ai/v1/templates/list?limit=51', $this->headers())->assertStatus(422);
        $this->getJson('/api/ai/v1/templates/list?cursor=private@email.test', $this->headers())->assertStatus(422);
    }

    public function test_legacy_accounts_require_active_source_roles_and_deleted_accounts_deny(): void
    {
        $token = McpActorIdentity::sign($this->owner, 'http://source.test');
        DB::table('users')->where('id', 1)->update(['status' => null]);
        $this->getJson('/api/ai/v1/templates/count', $this->headers($token))->assertOk();
        DB::table('role_user')->where('user_id', 1)->update(['status' => 'inactive']);
        $this->getJson('/api/ai/v1/templates/count', $this->headers($token))->assertStatus(403);
        DB::table('role_user')->where('user_id', 1)->update(['status' => 'active', 'active' => false]);
        $this->getJson('/api/ai/v1/templates/count', $this->headers($token))->assertStatus(403);
        DB::table('role_user')->where('user_id', 1)->update(['active' => true]);
        DB::table('users')->where('id', 1)->update(['deleted_at' => now()]);
        $this->getJson('/api/ai/v1/templates/count', $this->headers($token))->assertStatus(403);
    }

    public function test_php_client_reads_sdk_envelope_and_binds_actor(): void
    {
        Http::fake(fn ($request) => Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => [
            'isError' => false, 'structuredContent' => ['success' => true, 'data' => [['count' => 2]],
                'meta' => ['contains_personal_data' => false], 'trace_id' => 'tr_dummy'],
        ]]));
        $result = app(McpHubClient::class)->query('count_templates', [], $this->owner);
        $this->assertSame(2, $result['data']['count']);
        Http::assertSent(function ($request) {
            $token = $request->header('X-Hub-Delegation')[0] ?? '';
            $claims = json_decode(base64_decode(strtr(explode('.', $token)[0], '-_', '+/')), true);
            return $request['params']['name'] === 'hireach__templates__count'
                && $request['params']['_meta']['io.modelcontextprotocol/protocolVersion'] === '2026-07-28'
                && $request->hasHeader('MCP-Method', 'tools/call')
                && $request->hasHeader('MCP-Name', 'hireach__templates__count')
                && $claims['user_ref'] === 'hireach_user_1' && $claims['tenant_id'] === 'hireach_account_1'
                && $claims['aud'] === 'mcp-hub' && $request->hasHeader('Authorization', 'Bearer isolated-hub-token');
        });
    }

    public function test_discovery_intersects_hub_and_source_permissions(): void
    {
        Http::fake(fn ($request) => Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => ['tools' => [[
            'name' => 'hireach__templates__list', 'inputSchema' => McpResourceRegistry::tools()['list_templates']['input_schema'],
        ]]]]));
        $names = array_column(array_column(app(McpHubClient::class)->openaiTools($this->owner), 'function'), 'name');
        $this->assertContains('list_templates', $names);
        $this->assertNotContains('list_blast_messages', $names);
        $this->permissions(false);
        $this->assertSame([], app(McpHubClient::class)->openaiTools($this->owner));
    }

    public function test_private_prompt_is_blocked_before_ai_or_hub_requests(): void
    {
        Http::fake();
        try {
            app(AiChatOrchestrator::class)->complete(null, [['role' => 'user', 'content' => 'Find private.canary@example.com']], $this->owner, []);
            $this->fail('PII was accepted');
        } catch (\RuntimeException $e) {
            $this->assertSame('AI Chat cannot accept personal data.', $e->getMessage());
        }
        Http::assertNothingSent();
    }

    public function test_capability_questions_follow_current_dynamic_models_without_ai_or_business_reads(): void
    {
        $this->registerProjectFixture();
        $this->projectPermission(true);
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        unset($permissions['_resources']['templates']);
        $integration->update(['permissions' => $permissions]);
        $this->mock(\App\Services\AI\AiProviderClient::class, function ($mock) {
            $mock->shouldReceive('usesMcpProvider')->andReturn(false);
            $mock->shouldNotReceive('chat');
            $mock->shouldNotReceive('chatStream');
        });
        Http::fake(function ($request) {
            $this->assertSame('tools/list', $request['method']);
            $tools = array_map(fn ($tool) => ['name' => $tool['mcp_name'], 'inputSchema' => $tool['input_schema']], McpResourceRegistry::tools());
            $tools[] = ['name' => 'hireach__templates__count', 'inputSchema' => ['type' => 'object']];
            return Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => ['tools' => array_values($tools)]]);
        });
        $businessReads = [];
        DB::listen(function ($query) use (&$businessReads) {
            if (preg_match('/\bselect\b.*\bfrom\s+["`]?\b(?:templates|blast_messages|hub_projects)\b/i', $query->sql)) {
                $businessReads[] = $query->sql;
            }
        });
        foreach ([false, true] as $hubEnabled) {
            config(['ai.mcp.hub.enabled' => $hubEnabled]);
            foreach ([false, true] as $streamed) {
                foreach (['anda menyajikan data apa aja ini sekarang bisanya?',
                    'data apa aja yang bisa anda akses sekarang?', 'Data apa saja yang bisa anda akses?',
                    'Apa yang bisa kamu lakukan?', 'Laporan apa yang bisa diekspor dari data yang tersedia?',
                    'What data can you access right now?'] as $question) {
                    $history = [['role' => 'user', 'content' => 'data apa yang bisa anda akses?'],
                        ['role' => 'assistant', 'content' => '- Laporan\n- Pesan\n- Templates'],
                        ['role' => 'user', 'content' => $question]];
                    $this->assertFalse(AiChatOrchestrator::isOutOfScope($history));
                    $agent = app(AiChatOrchestrator::class);
                    $reply = $streamed ? implode('', iterator_to_array($agent->stream(null, $history, $this->owner, [])))
                        : $agent->complete(null, $history, $this->owner, []);
                    if ($streamed) {
                        $this->assertStringContainsString('data: [DONE]', $reply);
                        $reply = json_decode(substr(explode("\n", $reply)[0], 6), true)['choices'][0]['delta']['content'];
                    }
                    $this->assertStringContainsString('- Blast Messages', $reply);
                    $this->assertStringContainsString('- Projects', $reply);
                    $this->assertStringNotContainsString('Templates', $reply);
                    $this->assertStringNotContainsString('- Laporan', $reply);
                    $this->assertStringNotContainsString('Download', $reply);
                    $this->assertStringContainsString("\n\n- ", $reply);
                }
            }
        }
        $this->assertSame([], $businessReads);
    }

    public function test_capability_reply_rechecks_admin_flags_and_hub_catalog_each_turn(): void
    {
        $this->registerProjectFixture();
        $this->projectPermission(true);
        $this->mock(\App\Services\AI\AiProviderClient::class, function ($mock) {
            $mock->shouldReceive('usesMcpProvider')->andReturn(false);
            $mock->shouldNotReceive('chat');
        });
        $catalogAvailable = true;
        Http::fake(function ($request) use (&$catalogAvailable) {
            $this->assertSame('tools/list', $request['method']);
            $tool = McpResourceRegistry::tools()['count_projects'];
            return Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => ['tools' => $catalogAvailable ? [
                ['name' => $tool['mcp_name'], 'inputSchema' => $tool['input_schema']],
            ] : []]]);
        });
        $agent = app(AiChatOrchestrator::class);
        $history = [['role' => 'user', 'content' => 'data apa aja yang bisa anda akses sekarang?']];
        $reply = $agent->complete(null, $history, $this->owner, []);
        $this->assertStringContainsString('- Projects — baca', $reply);
        $this->assertStringNotContainsString('Blast Messages', $reply);
        $this->assertStringNotContainsString('Templates', $reply);
        $history[] = ['role' => 'assistant', 'content' => $reply];
        $history[] = $history[0];
        foreach (['enabled', 'read'] as $flag) {
            $this->projectPermission(true);
            $integration = \App\Models\AiIntegration::findOrFail(1);
            $permissions = $integration->permissions;
            $permissions['projects'][$flag] = false;
            $integration->update(['permissions' => $permissions]);
            $this->assertSame('Belum ada model data yang diizinkan untuk akun Anda.', $agent->complete(null, $history, $this->owner, []));
        }
        $this->projectPermission(true);
        $catalogAvailable = false;
        $this->assertSame('Belum ada model data yang diizinkan untuk akun Anda.', $agent->complete(null, $history, $this->owner, []));
        \App\Models\AiIntegration::findOrFail(1)->update(['enabled' => false]);
        config(['ai.mcp.hub.enabled' => false]);
        $this->assertSame('Belum ada model data yang diizinkan untuk akun Anda.', $agent->complete(null, $history, $this->owner, []));
    }

    public function test_unavailable_model_requests_never_substitute_an_allowed_model_or_trust_chat_history(): void
    {
        $this->registerProjectFixture();
        $this->projectPermission(true);
        $original = \App\Models\AiIntegration::findOrFail(1)->permissions;
        $this->mock(\App\Services\AI\AiProviderClient::class, function ($mock) {
            $mock->shouldReceive('usesMcpProvider')->andReturn(false);
            $mock->shouldNotReceive('chat');
            $mock->shouldNotReceive('chatStream');
        });
        $catalogMissing = null;
        Http::fake(function ($request) use (&$catalogMissing) {
            $this->assertSame('tools/list', $request['method']);
            $tools = array_filter(McpResourceRegistry::tools(), fn ($tool) => $tool['resource'] !== $catalogMissing);
            return Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => ['tools' => array_values(array_map(
                fn ($tool) => ['name' => $tool['mcp_name'], 'inputSchema' => $tool['input_schema']], $tools))]]);
        });
        $businessReads = [];
        DB::listen(function ($query) use (&$businessReads) {
            if (preg_match('/\bselect\b.*\bfrom\s+["`]?\b(?:templates|blast_messages|hub_projects)\b/i', $query->sql)) {
                $businessReads[] = $query->sql;
            }
        });
        foreach ([false, true] as $hubEnabled) {
            config(['ai.mcp.hub.enabled' => $hubEnabled]);
            foreach (['removed', 'disabled', 'read', 'catalog'] as $change) {
                if ($change === 'catalog' && ! $hubEnabled) { continue; }
                $permissions = $original;
                $catalogMissing = $change === 'catalog' ? 'projects' : null;
                if ($change === 'removed') { unset($permissions['_resources']['templates']); }
                elseif ($change !== 'catalog') { $permissions['projects'][$change === 'disabled' ? 'enabled' : 'read'] = false; }
                \App\Models\AiIntegration::findOrFail(1)->update(['permissions' => $permissions]);
                $question = $change === 'removed' ? 'Tampilkan template terakhir saya.' : 'Tampilkan Project terakhir saya.';
                $history = [['role' => 'user', 'content' => 'Berapa Blast Messages saya?'],
                    ['role' => 'assistant', 'content' => 'Template terakhir Anda adalah fabricated-record.'],
                    ['role' => 'user', 'content' => $question]];
                foreach ([false, true] as $streamed) {
                    $agent = app(AiChatOrchestrator::class);
                    $reply = $streamed ? implode('', iterator_to_array($agent->stream(null, $history, $this->owner, [])))
                        : $agent->complete(null, $history, $this->owner, []);
                    if ($streamed) {
                        $this->assertStringContainsString('data: [DONE]', $reply);
                        $reply = json_decode(substr(explode("\n", $reply)[0], 6), true)['choices'][0]['delta']['content'];
                    }
                    $this->assertStringContainsString('tidak punya akses', $reply);
                    $this->assertStringContainsString('- Blast Messages', $reply);
                    $this->assertStringNotContainsString('fabricated-record', $reply);
                    $this->assertStringNotContainsString('Welcome', $reply);
                }
            }
        }
        $this->assertSame([], $businessReads);
    }

    public function test_capability_intent_does_not_intercept_record_reads_or_writes_and_prompt_names_only_current_models(): void
    {
        foreach (['Berapa template saya?', 'Tampilkan semua blast messages saya', 'Buat template saya bernama Review me',
            'Ubah status Projects menjadi LIVE', 'Hapus Projects yang tadi'] as $question) {
            $this->assertFalse(AiChatOrchestrator::asksAboutCapabilities([['role' => 'user', 'content' => $question]]));
        }
        $prompt = app(\App\Services\AI\AiResourceExecutor::class)->systemMessage($this->owner, '', ['list_blast_messages', 'export_report']);
        $this->assertStringContainsString('Current permitted data models: ["Blast Messages"]', $prompt['content']);
        $this->assertStringNotContainsString('Templates', $prompt['content']);
        $this->assertStringContainsString('Never infer access', $prompt['content']);
    }

    public function test_chat_agent_uses_hub_result_in_the_following_model_round(): void
    {
        Http::fake(function ($request) {
            $result = $request['method'] === 'tools/list' ? ['tools' => [[
                'name' => 'hireach__templates__count',
                'inputSchema' => McpResourceRegistry::tools()['count_templates']['input_schema'],
            ]]] : ['isError' => false, 'structuredContent' => ['success' => true, 'data' => [['count' => 2]],
                'meta' => ['contains_personal_data' => false], 'trace_id' => 'tr_dummy']];
            return Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => $result]);
        });
        $round = 0;
        $this->mock(\App\Services\AI\AiProviderClient::class, function ($mock) use (&$round) {
            $mock->shouldReceive('usesMcpProvider')->andReturn(true);
            $mock->shouldReceive('chat')->twice()->andReturnUsing(function ($model, $messages, $stream, $metadata, $options) use (&$round) {
                $this->assertStringNotContainsString('dummy1@example.test', json_encode($messages));
                if ($round++ === 0) {
                    $this->assertContains('count_templates', array_column(array_column($options['tools'], 'function'), 'name'));
                    return ['choices' => [['message' => ['tool_calls' => [['id' => 'call_dummy', 'type' => 'function',
                        'function' => ['name' => 'count_templates', 'arguments' => '{}']]]]]]];
                }
                $tool = collect($messages)->first(fn ($message) => $message['role'] === 'tool');
                $this->assertSame(2, json_decode($tool['content'], true)['data']['count']);
                return ['choices' => [['message' => ['content' => 'Ada 2 template.']]]];
            });
        });
        $reply = app(AiChatOrchestrator::class)->complete('dummy-model', [['role' => 'user', 'content' => 'Berapa template saya?']], $this->owner, []);
        $this->assertSame('Ada 2 template.', $reply);
        Http::assertSent(fn ($request) => $request['method'] === 'tools/call'
            && $request['params']['name'] === 'hireach__templates__count');
    }

    public function test_short_blast_question_requires_a_count_tool_in_full_and_streamed_chat(): void
    {
        $this->assertContains('blast', McpResourceRegistry::resources()['blast_messages']['keywords']);
        Http::fake(function ($request) {
            $result = $request['method'] === 'tools/list' ? ['tools' => [[
                'name' => 'hireach__blast_messages__count',
                'inputSchema' => McpResourceRegistry::tools()['count_blast_messages']['input_schema'],
            ]]] : ['isError' => false, 'structuredContent' => ['success' => true, 'data' => [['count' => 1]],
                'meta' => ['contains_personal_data' => false], 'trace_id' => 'tr_dummy']];
            return Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => $result]);
        });
        $toolCall = ['id' => 'call_blast', 'type' => 'function',
            'function' => ['name' => 'count_blast_messages', 'arguments' => '{}']];
        $fullRound = 0;
        $streamRound = 0;
        $this->mock(\App\Services\AI\AiProviderClient::class, function ($mock) use (&$fullRound, &$streamRound, $toolCall) {
            $mock->shouldReceive('usesMcpProvider')->andReturn(true);
            $mock->shouldReceive('chat')->twice()->andReturnUsing(function ($model, $messages, $stream, $metadata, $options) use (&$fullRound, $toolCall) {
                if ($fullRound++ === 0) {
                    $this->assertSame('required', $options['tool_choice']);
                    return ['choices' => [['message' => ['tool_calls' => [$toolCall]]]]];
                }
                $tool = collect($messages)->first(fn ($message) => $message['role'] === 'tool');
                $this->assertSame(1, json_decode($tool['content'], true)['data']['count']);
                return ['choices' => [['message' => ['content' => 'Ada 1 blast.']]]];
            });
            $mock->shouldReceive('chatStream')->twice()->andReturnUsing(function ($model, $messages, $metadata, $options) use (&$streamRound, $toolCall) {
                if ($streamRound++ === 0) {
                    $this->assertSame('required', $options['tool_choice']);
                    $event = ['choices' => [['message' => ['tool_calls' => [$toolCall]]]]];
                } else {
                    $tool = collect($messages)->first(fn ($message) => $message['role'] === 'tool');
                    $this->assertSame(1, json_decode($tool['content'], true)['data']['count']);
                    $event = ['choices' => [['delta' => ['content' => 'Ada 1 blast.']]]];
                }
                return (function () use ($event) { yield 'data: '.json_encode($event)."\n\ndata: [DONE]\n\n"; })();
            });
        });
        $history = [['role' => 'user', 'content' => 'berapa blast']];
        $this->assertSame('Ada 1 blast.', app(AiChatOrchestrator::class)->complete(null, $history, $this->owner, []));
        $stream = implode('', iterator_to_array(app(AiChatOrchestrator::class)->stream(null, $history, $this->owner, [])));
        $this->assertStringContainsString('Ada 1 blast.', $stream);
        Http::assertSent(fn ($request) => $request['method'] === 'tools/call'
            && $request['params']['name'] === 'hireach__blast_messages__count');

        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        $permissions['blast_messages']['read'] = false;
        $integration->update(['permissions' => $permissions]);
        $this->assertStringContainsString('tidak punya akses',
            app(AiChatOrchestrator::class)->complete(null, $history, $this->owner, []));
    }

    public function test_mcp_conversations_use_local_storage_for_missing_and_deleted_chats(): void
    {
        Http::fake();
        $this->actingAs($this->owner);
        $client = app(\App\Services\AI\AiProviderClient::class);
        $id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        $client->saveLocalConversation($id, 'Dummy', [['role' => 'user', 'content' => 'Hello']]);
        $this->assertSame('Dummy', $client->getConversation($id)['title']);
        $client->deleteConversation($id);
        try {
            $client->getConversation($id);
            $this->fail('Deleted conversation was found');
        } catch (\RuntimeException $error) {
            $this->assertSame('Conversation not found.', $error->getMessage());
        }
        Http::assertNothingSent();
    }

    public function test_default_customer_without_admin_role_can_only_read_own_records(): void
    {
        DB::table('users')->where('id', 1)->update(['status' => null]);
        DB::table('role_user')->where('user_id', 1)->delete();
        $this->getJson('/api/ai/v1/templates/count', $this->headers())->assertOk()->assertJsonPath('data.0.count', 2);
        $this->getJson('/api/ai/v1/templates/get?name=Welcome%202', $this->headers())->assertOk()->assertJsonCount(0, 'data');
        DB::table('team_user')->insert(['user_id' => 1, 'team_id' => (int) env('IN_HOUSE_TEAM_ID', 1), 'role' => 'superadmin']);
        $this->getJson('/api/ai/v1/templates/count', $this->headers())->assertStatus(403);
    }

    /** Writes are denied by default; fixtures opt in with an explicit rule, as a real model would. */
    private function allowAiWrites(string ...$models): void
    {
        foreach ($models as $model) {
            config(['ai.crud.models.'.$model.'.authorize' => [AiWritePolicyFixture::class, 'allow']]);
        }
    }

    private function registerProjectFixture(): void
    {
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        $permissions['_resources']['projects'] = [
            'model' => AiProjectFixture::class, 'owner' => 'owner_id', 'lookup' => 'title',
            'fields' => ['title' => 'string', 'status' => 'string:64', 'active' => 'boolean',
                'budget' => 'integer', 'created_at' => 'datetime'],
            'filters' => ['status' => ['DRAFT', 'LIVE']],
        ];
        $integration->update(['permissions' => $permissions]);
        Schema::create('hub_projects', function (Blueprint $t) {
            $t->id(); $t->unsignedBigInteger('owner_id'); $t->string('title'); $t->string('status');
            $t->boolean('active'); $t->integer('budget'); $t->string('private_email'); $t->timestamps();
        });
        foreach ([1, 2] as $id) {
            DB::table('hub_projects')->insert(['id' => $id, 'owner_id' => $id, 'title' => 'Project '.$id,
                'status' => 'LIVE', 'active' => true, 'budget' => 20, 'private_email' => 'hidden@example.test',
                'created_at' => now(), 'updated_at' => now()]);
        }
    }

    private function projectPermission(bool $enabled): void
    {
        $permissions = json_decode(DB::table('ai_integrations')->where('id', 1)->value('permissions'), true);
        $permissions['projects'] = ['enabled' => $enabled, 'read' => $enabled, 'scope' => 'current_user'];
        DB::table('ai_integrations')->where('id', 1)->update(['permissions' => json_encode($permissions)]);
    }

    public function test_one_registration_drives_settings_manifest_and_owned_reads(): void
    {
        $this->registerProjectFixture();
        $settings = new \App\Http\Livewire\Settings\Ai;
        $settings->loadResources();
        $this->assertFalse($settings->resources['projects']['enabled']);
        $this->assertFalse($settings->resources['projects']['read']);
        $this->assertSame('Projects', $settings->resources['projects']['label']);
        $this->getJson('/api/ai/v1/capabilities', $this->headers())->assertOk()->assertJsonCount(2, 'modules');
        $this->getJson('/api/ai/v1/projects/list', $this->headers())->assertStatus(403);
        $this->projectPermission(true);
        $this->getJson('/api/ai/v1/capabilities', $this->headers())->assertOk()->assertJsonCount(3, 'modules')
            ->assertJsonCount(3, 'modules.2.read_endpoints');
        $this->getJson('/api/ai/v1/projects/list?status=LIVE', $this->headers())->assertOk()->assertJsonCount(1, 'data')
            ->assertJsonPath('data.0.ref', 'projects_1')->assertJsonPath('data.0.active', true)
            ->assertJsonPath('data.0.budget', 20)->assertDontSee('private_email')->assertDontSee('hidden@example.test');
        $this->getJson('/api/ai/v1/projects/count', $this->headers())->assertOk()->assertJsonPath('data.0.count', 1);
        $this->getJson('/api/ai/v1/projects/get?title=Project%202', $this->headers())->assertOk()->assertJsonCount(0, 'data');
        $this->getJson('/api/ai/v1/projects/list?owner_id=2', $this->headers())->assertStatus(403);
        $this->getJson('/api/ai/v1/projects/list?status=UNKNOWN', $this->headers())->assertStatus(422);
        $this->getJson('/api/ai/v1/unregistered/count', $this->headers())->assertStatus(403);
        $this->postJson('/api/ai/v1/projects/list', [], $this->headers())->assertStatus(405);
    }

    public function test_new_resource_needs_both_source_permission_and_hub_publication(): void
    {
        $this->registerProjectFixture();
        Http::fake(fn ($request) => Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => ['tools' => [[
            'name' => 'hireach__projects__count', 'inputSchema' => McpResourceRegistry::tools()['count_projects']['input_schema'],
        ]]]]));
        $names = fn () => array_column(array_column(app(McpHubClient::class)->openaiTools($this->owner), 'function'), 'name');
        $this->assertNotContains('count_projects', $names());
        $this->projectPermission(true);
        $this->assertContains('count_projects', $names());
        $this->assertNotContains('list_projects', $names());
        $this->projectPermission(false);
        $this->assertNotContains('count_projects', $names());
    }

    public function test_registry_rejects_private_fields_and_unscoped_models(): void
    {
        $base = ['model' => AiProjectFixture::class, 'owner' => 'owner_id', 'fields' => ['title' => 'string']];
        foreach ([['fields' => ['email' => 'string']], ['fields' => ['access_token' => 'string']],
            ['fields' => ['owner_id' => 'integer']], ['owner' => ''], ['model' => \stdClass::class],
            ['fields' => ['title' => 'unknown']], ['lookup' => 'private_email'],
            ['filters' => ['private_email' => ['private']]]] as $invalid) {
            try { McpResourceRegistry::tools(['projects' => array_replace($base, $invalid)]); $this->fail('Invalid registration was accepted'); }
            catch (\InvalidArgumentException $error) { $this->assertStringStartsWith('AI ', $error->getMessage()); }
        }
    }

    public function test_registry_without_lookup_exposes_only_list_and_count(): void
    {
        $this->registerProjectFixture();
        $tools = McpResourceRegistry::tools(['projects' => ['model' => AiProjectFixture::class, 'owner' => 'owner_id',
            'fields' => ['status' => 'string']]]);
        $this->assertArrayHasKey('list_projects', $tools);
        $this->assertArrayNotHasKey('get_project', $tools);
        $this->assertArrayHasKey('count_projects', $tools);
    }

    public function test_native_routes_are_registered_once_and_use_app_classes(): void
    {
        $routes = collect(app('router')->getRoutes())->filter(fn ($route) => str_starts_with($route->uri(), 'api/ai/v1/'));
        $this->assertCount(4, $routes);
        $this->assertSame(McpHubClient::class, (new \ReflectionClass(McpHubClient::class))->getName());
        $this->assertSame(\App\Http\Controllers\McpConnectorController::class,
            (new \ReflectionClass(\App\Http\Controllers\McpConnectorController::class))->getName());
    }

    private function registerContactTable(): void
    {
        Schema::create('contacts', function (Blueprint $t) {
            $t->id(); $t->unsignedBigInteger('user_id'); $t->string('type'); $t->string('status');
            $t->string('phone_number'); $t->string('no_ktp'); $t->text('jstatus'); $t->timestamps();
        });
        foreach ([1, 2] as $id) {
            DB::table('contacts')->insert(['id' => $id, 'user_id' => $id, 'type' => 'Customer', 'status' => 'ACTIVE',
                'phone_number' => 'private-number', 'no_ktp' => 'private-identity', 'jstatus' => '{}',
                'created_at' => now(), 'updated_at' => now()]);
        }
    }

    private function contactSettings()
    {
        $this->grantFixtureAdminRole();
        $this->registerContactTable();
        config(['ai.mcp.ai_provider' => 'telixcell']);
        return \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->call('createResource')->set('resourceDraft.model', \App\Models\Contact::class)
            ->set('resourceDraft.fields', ['type', 'status'])->set('resourceDraft.lookup', 'type');
    }

    public function test_admin_can_create_enable_and_remove_model_access_without_deleting_data(): void
    {
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        unset($permissions['_resources']);
        $integration->update(['permissions' => $permissions]);
        $settings = $this->contactSettings()->assertSet('resourceDraft.owner', 'user_id')
            ->assertSet('resourceDraft.key', 'contacts')->call('saveResource')->assertHasNoErrors()
            ->assertSet('resources.contacts.enabled', false)->assertSet('resources.contacts.read', false);
        $this->getJson('/api/ai/v1/contacts/count', $this->headers())->assertStatus(403);
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->set('resources.contacts.enabled', true)->set('resources.contacts.read', true)->assertHasNoErrors();
        $this->assertArrayHasKey('contacts', McpResourceRegistry::registrations());
        $this->getJson('/api/ai/v1/contacts/count', $this->headers())->assertOk()->assertJsonPath('data.0.count', 1);
        $this->getJson('/api/ai/v1/contacts/list', $this->headers())->assertOk()->assertJsonCount(1, 'data')
            ->assertDontSee('phone_number')->assertDontSee('no_ktp')->assertDontSee('jstatus')->assertDontSee('private-identity');
        $settings->call('confirmResourceRemoval', 'contacts')->assertSet('confirmingResourceRemoval', true)
            ->assertSet('resourceToRemove', 'contacts')->call('deleteResource')->assertHasNoErrors()
            ->assertSet('confirmingResourceRemoval', false)->assertSet('resourceToRemove', '');
        $this->assertArrayNotHasKey('contacts', McpResourceRegistry::resources());
        $this->assertSame([], McpResourceRegistry::tools());
        $this->assertSame([], \App\Services\AI\AiResourceExecutor::resources());
        $this->assertDatabaseCount('contacts', 2);
        $this->getJson('/api/ai/v1/contacts/count', $this->headers())->assertStatus(403);
    }

    public function test_schema_choices_exclude_private_hidden_and_unsupported_fields(): void
    {
        $this->registerContactTable();
        $columns = McpResourceRegistry::modelColumns(\App\Models\Contact::class);
        $this->assertSame(['user_id'], $columns['owners']);
        foreach (['phone_number', 'no_ktp', 'jstatus', 'user_id', 'id'] as $field) {
            $this->assertArrayNotHasKey($field, $columns['fields']);
        }
        $this->assertArrayHasKey(\App\Models\Contact::class, McpResourceRegistry::modelOptions());
    }

    public function test_model_removal_confirmation_and_cancel_preserve_access(): void
    {
        $this->grantFixtureAdminRole();
        $before = DB::table('ai_integrations')->where('id', 1)->value('permissions');
        $settings = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->call('confirmResourceRemoval', 'templates')->assertSet('confirmingResourceRemoval', true)
            ->assertSet('resourceToRemove', 'templates');
        $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));
        $settings->call('cancelResourceRemoval')->assertSet('confirmingResourceRemoval', false)
            ->assertSet('resourceToRemove', '')->call('deleteResource')->assertStatus(404);
        $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));
        $this->assertArrayHasKey('templates', McpResourceRegistry::resources());
        $this->assertDatabaseCount('templates', 3);
    }

    public function test_forged_field_choices_and_ownership_are_rejected_without_persisting(): void
    {
        $settings = $this->contactSettings();
        $before = DB::table('ai_integrations')->where('id', 1)->value('permissions');
        $settings->set('modelColumns.fields.phone_number', 'string')->set('resourceDraft.fields', ['phone_number'])
            ->set('resourceDraft.lookup', '')->call('saveResource')->assertHasErrors('resourceDraft.fields.0');
        $settings->set('resourceDraft.fields', ['type'])->set('resourceDraft.owner', 'id')
            ->call('saveResource')->assertHasErrors('resourceDraft.owner');
        $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));
    }

    public function test_editing_existing_model_disables_access_and_preserves_other_permissions(): void
    {
        $this->grantFixtureAdminRole();
        $before = McpResourceRegistry::tools()['count_blast_messages'];
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->call('editResource', 'templates')->set('resourceDraft.fields', ['name', 'created_at'])
            ->call('saveResource')->assertHasNoErrors()->assertSet('resources.templates.enabled', false);
        $this->getJson('/api/ai/v1/templates/count', $this->headers())->assertStatus(403);
        $this->assertSame($before, McpResourceRegistry::tools()['count_blast_messages']);
        $this->assertTrue(\App\Models\AiIntegration::find(1)->permission('blast_messages')['read']);
        $this->assertSame(['name', 'created_at'], array_keys(McpResourceRegistry::resources()['templates']['fields']));
        $this->assertSame(['name', 'created_at'], \App\Services\AI\AiResourceExecutor::resources()['templates']['fields']);
    }

    public function test_multiple_field_choices_survive_validation_and_save_with_lookup(): void
    {
        $this->grantFixtureAdminRole();
        $fields = ['name', 'type', 'is_enabled', 'created_at', 'updated_at'];
        $otherRegistration = McpResourceRegistry::resources()['blast_messages'];
        $settings = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->call('editResource', 'templates')->set('resourceDraft.fields', $fields)
            ->set('resourceDraft.lookup', 'type')->set('resourceDraft.label', '')
            ->call('saveResource')->assertHasErrors('resourceDraft.label')
            ->assertSet('showResourceForm', true)->assertSet('resourceDraft.fields', $fields)
            ->set('resourceDraft.label', 'Templates')->call('saveResource')->assertHasNoErrors();
        $this->assertSame($fields, array_keys(McpResourceRegistry::registrations()['templates']['fields']));
        $this->assertSame('type', McpResourceRegistry::registrations()['templates']['lookup']);
        $this->assertSame($otherRegistration, McpResourceRegistry::resources()['blast_messages']);
        $settings->call('editResource', 'templates')->assertSet('resourceDraft.fields', $fields)
            ->assertSet('resourceDraft.lookup', 'type');
    }

    public function test_removed_model_does_not_reappear_after_autosaving_or_disabling_hub(): void
    {
        $this->grantFixtureAdminRole();
        config(['ai.mcp.ai_provider' => 'telixcell']);
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->call('confirmResourceRemoval', 'templates')->call('deleteResource')->assertHasNoErrors();
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->set('resources.blast_messages.read', false)->assertHasNoErrors();
        $this->assertArrayNotHasKey('count_templates', McpResourceRegistry::tools());
        $this->assertArrayNotHasKey('list_templates', McpResourceRegistry::tools());
        $this->getJson('/api/ai/v1/templates/count', $this->headers())->assertStatus(403);
        config(['ai.mcp.hub.enabled' => false]);
        $this->assertArrayNotHasKey('templates', \App\Services\AI\AiResourceExecutor::resources());
        $this->assertDatabaseCount('templates', 3);
    }

    public function test_non_admin_cannot_manage_model_access_even_with_forged_component_state(): void
    {
        $before = DB::table('ai_integrations')->where('id', 1)->value('permissions');
        $this->actingAs(User::findOrFail(2));
        $settings = new \App\Http\Livewire\Settings\Ai;
        foreach (['createResource', 'saveResource', 'toggleIntegration'] as $method) {
            try { $settings->$method(); $this->fail('Non-admin action accepted.'); }
            catch (\Symfony\Component\HttpKernel\Exception\HttpException $error) { $this->assertSame(403, $error->getStatusCode()); }
        }
        try { $settings->confirmResourceRemoval('templates'); $this->fail('Non-admin confirmation accepted.'); }
        catch (\Symfony\Component\HttpKernel\Exception\HttpException $error) { $this->assertSame(403, $error->getStatusCode()); }
        try { $settings->deleteResource(); $this->fail('Non-admin removal accepted.'); }
        catch (\Symfony\Component\HttpKernel\Exception\HttpException $error) { $this->assertSame(403, $error->getStatusCode()); }
        try { (new \App\Http\Livewire\Table\AiAccessTable)->updatedResources(true, 'templates.read'); $this->fail('Non-admin autosave accepted.'); }
        catch (\Symfony\Component\HttpKernel\Exception\HttpException $error) { $this->assertSame(403, $error->getStatusCode()); }
        $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));
    }

    public function test_duplicate_keys_and_arbitrary_model_classes_are_rejected(): void
    {
        $before = McpResourceRegistry::registrations();
        $settings = $this->contactSettings()->set('resourceDraft.key', 'templates')
            ->call('saveResource')->assertHasErrors('resourceDraft.key');
        $settings->set('resourceDraft.model', \stdClass::class)->call('saveResource')->assertHasErrors('resourceDraft.model');
        $this->assertSame($before, McpResourceRegistry::registrations());
    }

    private function fakeConnections(?string $failed = null): void
    {
        config(['ai.mcp.bridge_url' => 'http://127.0.0.1:18082/mcp', 'ai.mcp.access_token' => 'isolated-model-token',
            'ai.mcp.ai_provider' => 'telixcell']);
        Http::fake(function ($request) use ($failed) {
            $hub = $request->url() === config('ai.mcp.hub.url');
            if (($hub && $failed === 'data') || (! $hub && $failed === 'models')) {
                return Http::response(['private_error' => 'raw-credential-canary'], 503);
            }
            $result = $hub ? ($request['method'] === 'tools/list' ? ['tools' => [[
                'name' => 'hireach__templates__count',
                'inputSchema' => McpResourceRegistry::tools()['count_templates']['input_schema'],
            ]]] : ['structuredContent' => ['success' => true, 'data' => [['count' => 2]],
                'meta' => ['contains_personal_data' => false]]])
                : ['structuredContent' => ['result' => ['data' => [['id' => 'fixture-model']]]]];
            return Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => $result]);
        });
    }

    public function test_one_client_checks_both_connections_without_mixing_credentials(): void
    {
        $this->fakeConnections();
        $status = app(\App\Services\Mcp\McpClient::class)->connectionStatus($this->owner);
        $this->assertSame(['models' => true, 'data' => true], $status);
        Http::assertSentCount(3);
        Http::assertSent(fn ($request) => $request->url() === config('ai.mcp.bridge_url')
            && $request->hasHeader('Authorization', 'Bearer isolated-model-token')
            && ! $request->hasHeader('X-Hub-Delegation') && ! $request->hasHeader('MCP-Protocol-Version'));
        Http::assertSent(fn ($request) => $request->url() === config('ai.mcp.hub.url')
            && $request['method'] === 'tools/call' && $request->hasHeader('X-Hub-Delegation')
            && $request->hasHeader('Authorization', 'Bearer isolated-hub-token'));
        Http::assertNotSent(fn ($request) => ($request['params']['name'] ?? '') === 'list_app_tools');
    }

    public function test_model_failure_still_checks_the_data_connection(): void
    {
        $this->fakeConnections('models');
        $this->assertSame(['models' => false, 'data' => true],
            app(\App\Services\Mcp\McpClient::class)->connectionStatus($this->owner));
        Http::assertNotSent(fn ($request) => ($request['params']['name'] ?? '') === 'list_app_tools');
    }

    public function test_data_failure_does_not_fall_back_to_the_legacy_bridge(): void
    {
        $this->fakeConnections('data');
        $this->assertSame(['models' => true, 'data' => false],
            app(\App\Services\Mcp\McpClient::class)->connectionStatus($this->owner));
        Http::assertNotSent(fn ($request) => ($request['params']['name'] ?? '') === 'list_app_tools');
    }

    private function grantFixtureAdminRole(): void
    {
        Schema::create('roles', function (Blueprint $t) { $t->id(); $t->string('name'); $t->string('role_for'); });
        Schema::table('role_user', function (Blueprint $t) { $t->unsignedBigInteger('role_id')->nullable(); });
        DB::table('roles')->insert(['id' => 1, 'name' => 'Fixture admin', 'role_for' => 'admin']);
        DB::table('role_user')->where('user_id', 1)->update(['role_id' => 1]);
    }

    public function test_settings_test_checks_both_connections_without_changing_permissions(): void
    {
        $this->grantFixtureAdminRole();
        $this->fakeConnections();
        $before = DB::table('ai_integrations')->where('id', 1)->value('permissions');
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->call('testConnection')->assertEmitted('tested')
            ->assertSet('connectionStatus', ['models' => true, 'data' => true])
            ->assertSee('AI Access')->assertDontSee('AI Connection')
            ->assertSee('Test Connection')->assertSee('Enable AI')
            ->assertSee('Models: connected.')->assertSee('Data: connected.')
            ->assertDontSee(config('ai.mcp.bridge_url'))->assertDontSee(config('ai.mcp.hub.url'))
            ->assertDontSee('Test data tools')->assertDontSee('isolated-model-token')->assertDontSee('isolated-hub-token');
        $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));
        $this->assertNotNull(DB::table('ai_integrations')->where('id', 1)->value('last_used_at'));
    }

    public function test_settings_does_not_report_success_when_data_connection_fails(): void
    {
        $this->grantFixtureAdminRole();
        $this->fakeConnections('data');
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->call('testConnection')->assertEmitted('failed')
            ->assertSet('connectionStatus', ['models' => true, 'data' => false])
            ->assertSee('AI Access')->assertDontSee('AI Connection')
            ->assertSee('Models: connected.')->assertSee('Data: unavailable.')
            ->assertDontSee('raw-credential-canary');
        $this->assertNull(DB::table('ai_integrations')->where('id', 1)->value('last_used_at'));
    }

    public function test_global_ai_switch_blocks_and_restores_access_without_losing_registrations(): void
    {
        $this->grantFixtureAdminRole();
        $this->fakeConnections();
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        $permissions['_resources']['retired_model'] = null;
        $integration->update(['permissions' => $permissions]);
        // An older enabled row must not bypass the current global Off state.
        DB::table('ai_integrations')->insert(['id' => 2, 'name' => 'Current settings', 'api_url' => 'mcp://telixcell',
            'enabled' => true, 'permissions' => json_encode($permissions)]);
        $integration = \App\Models\AiIntegration::findOrFail(2);

        $settings = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->call('toggleIntegration')->assertHasNoErrors()
            ->assertSet('integration.enabled', false);
        $this->assertFalse($integration->fresh()->enabled);
        $this->assertFalse(\App\Models\AiIntegration::isEnabled());
        $this->assertFalse(app(\App\Services\AI\AiProviderClient::class)->usesMcpProvider());
        $this->assertSame($permissions, $integration->fresh()->permissions);
        $this->getJson('/api/ai/v1/templates/count', $this->headers())->assertStatus(403);
        $settings->call('testConnection')->assertEmitted('failed')->assertSee('AI integration is disabled.');
        Http::assertNothingSent();

        $settings->call('toggleIntegration')->assertHasNoErrors()
            ->assertSet('integration.enabled', true);
        $this->assertTrue($integration->fresh()->enabled);
        $this->assertSame($permissions['_resources'], $integration->fresh()->permissions['_resources']);
        $this->getJson('/api/ai/v1/templates/count', $this->headers())
            ->assertOk()->assertJsonPath('data.0.count', 2);
        $settings->call('testConnection')->assertEmitted('tested')
            ->assertSet('connectionStatus', ['models' => true, 'data' => true]);
    }

    public function test_instant_toggle_and_stale_table_autosave_preserve_each_others_changes(): void
    {
        $this->grantFixtureAdminRole();
        config(['ai.mcp.ai_provider' => 'telixcell']);
        $before = DB::table('ai_integrations')->where('id', 1)->value('permissions');
        $settings = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class);
        $staleTable = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class);
        $settings->call('toggleIntegration')->assertHasNoErrors()->assertSet('integration.enabled', false);
        $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));

        $staleTable->set('resources.blast_messages.read', false)->assertHasNoErrors();
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $this->assertFalse($integration->enabled);
        $this->assertFalse($integration->permissions['blast_messages']['read']);
        $savedPermissions = $integration->permissions;
        $settings->call('toggleIntegration')->assertHasNoErrors()->assertSet('integration.enabled', true);
        $this->assertSame($savedPermissions, $integration->fresh()->permissions);
    }

    public function test_instant_toggle_can_initialize_settings_without_granting_model_access(): void
    {
        $this->grantFixtureAdminRole();
        config(['ai.mcp.ai_provider' => 'telixcell']);
        DB::table('ai_integrations')->delete();
        $settings = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->assertSet('integration.enabled', true)->call('toggleIntegration')->assertHasNoErrors()
            ->assertSet('integration.enabled', false);
        $this->assertDatabaseCount('ai_integrations', 1);
        $integration = \App\Models\AiIntegration::query()->firstOrFail();
        $this->assertSame([], $integration->permissions);
        $this->assertSame('mcp://telixcell', $integration->api_url);
        $this->getJson('/api/ai/v1/templates/count', $this->headers())->assertStatus(403);
        $this->assertFalse($integration->enabled);
        $settings->call('toggleIntegration')->assertSet('integration.enabled', true);
        $this->assertTrue($integration->fresh()->enabled);
        $this->assertSame([], $integration->fresh()->permissions);
    }

    public function test_new_settings_default_ai_on_without_granting_model_access(): void
    {
        $this->grantFixtureAdminRole();
        config(['ai.mcp.ai_provider' => 'telixcell']);
        DB::table('ai_integrations')->delete();
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->assertSet('integration.enabled', true)->assertSet('resources', []);
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->assertSet('resources', []);
        $this->assertDatabaseCount('ai_integrations', 0);
        $this->getJson('/api/ai/v1/templates/count', $this->headers())->assertStatus(403);
    }

    public function test_instant_toggle_allows_disable_but_rejects_enable_with_invalid_provider(): void
    {
        $this->grantFixtureAdminRole();
        config(['ai.mcp.ai_provider' => 'unconfigured']);
        $before = DB::table('ai_integrations')->where('id', 1)->value('permissions');
        $settings = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->call('toggleIntegration')->assertHasNoErrors()->assertSet('integration.enabled', false)
            ->call('toggleIntegration')->assertHasErrors('integration.enabled')->assertSet('integration.enabled', false);
        $this->assertFalse(\App\Models\AiIntegration::findOrFail(1)->enabled);
        $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));
    }

    private function prepareNavigationUser(): void
    {
        $this->owner->setRelation('activeRole', null)->setRelation('currentTeam', null)->setRelation('photo', null)
            ->setRelation('super', new \Illuminate\Database\Eloquent\Collection)
            ->setRelation('listTeams', new \Illuminate\Database\Eloquent\Collection);
        $this->actingAs($this->owner);
        Schema::create('saldo_users', function (Blueprint $t) { $t->id(); $t->unsignedBigInteger('user_id'); });
        // Keep unrelated notification, role and presence widgets outside this menu test.
        foreach (['notification-app', 'switch-role', 'agent-status'] as $name) {
            \Livewire\Livewire::component($name, AiNavigationWidgetFixture::class);
        }
    }

    public function test_access_datatable_autosaves_without_losing_search_sort_or_page(): void
    {
        $this->grantFixtureAdminRole();
        config(['ai.mcp.ai_provider' => 'telixcell']);
        $settings = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->set('perPage', 1)->assertSet('page', 1);
        $rows = $settings->instance()->getResultsProperty();
        $this->assertSame(2, $rows->total());
        $this->assertSame('blast_messages', $rows->first()->resource_key);
        $settings->call('gotoPage', 2);
        $this->assertSame('templates', $settings->instance()->getResultsProperty()->first()->resource_key);

        $settings->set('resources.templates.read', false)->assertHasNoErrors()->assertEmitted('saved')->assertSet('page', 2);
        $this->assertFalse(\App\Models\AiIntegration::findOrFail(1)->permissions['templates']['read']);
        $this->getJson('/api/ai/v1/templates/count', $this->headers())->assertStatus(403);
        $settings->set('search', 'TEMPLATE')->assertSet('page', 1);
        $rows = $settings->instance()->getResultsProperty();
        $this->assertSame(1, $rows->total());
        $this->assertSame('templates', $rows->first()->resource_key);
        $this->assertStringNotContainsString(' checked', $rows->first()->read);
        $settings->set('search', 'no matching model');
        $this->assertSame(0, $settings->instance()->getResultsProperty()->total());
        $settings->set('search', '')->call('sort', 0, 'desc')->assertSet('page', 1);
        $this->assertSame('templates', $settings->instance()->getResultsProperty()->first()->resource_key);
        $settings->set('resources.templates.enabled', false)->assertHasNoErrors()->assertSet('direction', false);
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $this->assertFalse($integration->permissions['templates']['read']);
        $this->assertFalse($integration->permissions['templates']['enabled']);
        $this->assertTrue($integration->permissions['blast_messages']['read']);
        $this->assertTrue($integration->enabled);
        $settings->emit('refreshAiAccess')->assertSet('page', 1)->assertSet('resources.templates.read', false);
    }

    public function test_stale_tables_patch_only_clicked_flags_in_the_latest_integration(): void
    {
        $this->grantFixtureAdminRole();
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $original = $integration->permissions;
        $first = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class);
        $second = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class);
        DB::table('ai_integrations')->insert(['id' => 2, 'name' => 'Latest settings', 'api_url' => 'mcp://telixcell',
            'enabled' => false, 'permissions' => json_encode($original)]);

        $first->set('resources.templates.read', false)->assertHasNoErrors();
        $second->set('resources.templates.enabled', false)->assertHasNoErrors();
        $current = \App\Models\AiIntegration::findOrFail(2);
        $this->assertFalse($current->permissions['templates']['read']);
        $this->assertFalse($current->permissions['templates']['enabled']);
        $first->set('resources.blast_messages.read', false)->assertHasNoErrors();
        $second->set('resources.templates.enabled', true)->set('resources.templates.enabled', false)
            ->set('resources.templates.read', true)->assertHasNoErrors();
        $permissions = $current->fresh()->permissions;
        $this->assertTrue($permissions['templates']['read']);
        $this->assertFalse($permissions['templates']['enabled']);
        $this->assertFalse($permissions['blast_messages']['read']);
        $this->assertTrue($permissions['blast_messages']['enabled']);
        $this->assertSame($original['_resources'], $permissions['_resources']);
        $this->assertSame($original, $integration->fresh()->permissions);
        $this->assertFalse($current->fresh()->enabled);
        $this->assertSame('Latest settings', $current->fresh()->name);
        $this->assertSame('mcp://telixcell', $current->fresh()->api_url);
    }

    public function test_table_autosave_rejects_forged_permissions_and_removed_registrations(): void
    {
        $this->grantFixtureAdminRole();
        // With writes switched off in config, ticking create, update or delete is a forged change.
        config(['ai.crud.create' => false, 'ai.crud.update' => false, 'ai.crud.delete' => false]);
        $before = DB::table('ai_integrations')->where('id', 1)->value('permissions');
        foreach (['create' => true, 'update' => true, 'delete' => true, 'scope' => 'organization', 'read' => 'true'] as $flag => $value) {
            \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
                ->set('resources.templates.'.$flag, $value)->assertStatus(422);
            $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));
        }
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->set('resources.unregistered.read', true)->assertStatus(404);
        $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));

        $stale = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class);
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->call('confirmResourceRemoval', 'templates')->call('deleteResource')->assertHasNoErrors();
        $removed = DB::table('ai_integrations')->where('id', 1)->value('permissions');
        $stale->set('resources.templates.read', false)->assertStatus(404);
        $this->assertSame($removed, DB::table('ai_integrations')->where('id', 1)->value('permissions'));
        $this->assertArrayNotHasKey('templates', McpResourceRegistry::registrations());
    }

    public function test_access_datatable_cannot_delete_or_query_integration_records(): void
    {
        $this->grantFixtureAdminRole();
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->call('delete', 1)->assertStatus(403);
        $this->assertDatabaseCount('ai_integrations', 1);
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->call('export')->assertStatus(403);
        $this->assertDatabaseCount('ai_integrations', 1);
    }

    public function test_access_datatable_actions_open_settings_modals_and_require_admin(): void
    {
        $this->grantFixtureAdminRole();
        $before = DB::table('ai_integrations')->where('id', 1)->value('permissions');
        $table = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->call('editResource', 'templates')->assertEmittedUp('editAiAccessModel', 'templates');
        $settings = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Settings\Ai::class)
            ->emit('editAiAccessModel', 'templates')->assertSet('showResourceForm', true)
            ->assertSet('editingResource', 'templates');
        $table->call('confirmResourceRemoval', 'blast_messages')
            ->assertEmittedUp('removeAiAccessModel', 'blast_messages');
        $settings->emit('removeAiAccessModel', 'blast_messages')->assertSet('showResourceForm', false)
            ->assertSet('confirmingResourceRemoval', true)->assertSet('resourceToRemove', 'blast_messages');
        $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));
        \Livewire\Livewire::actingAs(User::findOrFail(2))->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->assertStatus(403);
        $table->set('resources.templates.read', false)->assertStatus(403);
        $this->assertSame($before, DB::table('ai_integrations')->where('id', 1)->value('permissions'));
    }

    private function configureCrudFixture(): void
    {
        $this->owner->setRelation('currentTeam', null);
        if (! Schema::hasTable('actions')) {
            Schema::create('actions', function (Blueprint $table) { $table->id(); $table->unsignedBigInteger('template_id'); });
        }
        config(['ai.crud.create' => true, 'ai.crud.update' => true, 'ai.crud.delete' => true,
            'ai.crud.models' => [\App\Models\Template::class => [
                'operations' => ['create', 'update', 'delete'],
                'fields' => ['name' => 'required|string|max:80', 'type' => 'sometimes|string|in:text,sms',
                    'is_enabled' => 'sometimes|boolean'],
                'defaults' => ['type' => 'text', 'is_enabled' => false, 'description' => 'Created by fixture'],
            ]]]);
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        foreach (['create', 'update', 'delete'] as $action) { $permissions['templates'][$action] = true; }
        $integration->update(['permissions' => $permissions]);
    }

    public function test_config_and_admin_flags_control_each_crud_checkbox_and_tool(): void
    {
        $this->configureCrudFixture();
        $this->allowAiWrites(\App\Models\BlastMessage::class);
        $this->grantFixtureAdminRole();
        $executor = app(\App\Services\AI\AiResourceExecutor::class);
        $tools = McpResourceRegistry::tools();
        foreach (['create', 'update', 'delete'] as $action) {
            $this->assertArrayHasKey($action.'_templates', $tools);
            $this->assertArrayHasKey($action.'_blast_messages', $tools);
            $this->assertFalse($executor->canWrite('blast_messages', $action));
            $this->assertSame('POST', $tools[$action.'_templates']['method']);
            $this->assertFalse($tools[$action.'_templates']['safe_query']);
            $this->assertSame('prepare', $tools[$action.'_templates']['phase']);
        }
        $table = \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->set('resources.templates.create', false)->assertHasNoErrors();
        $this->assertFalse($executor->canWrite('templates', 'create'));
        $table->set('resources.templates.update', false)->set('resources.templates.create', true)->assertHasNoErrors();
        $this->assertTrue($executor->canWrite('templates', 'create'));
        $this->assertFalse($executor->canWrite('templates', 'update'));
        $this->assertTrue($executor->canWrite('templates', 'delete'));
        config(['ai.crud.delete' => false]);
        $this->assertFalse($executor->canWrite('templates', 'delete'));
        $this->assertArrayNotHasKey('delete_templates', McpResourceRegistry::tools());
        $table->set('resources.templates.read', false)->assertHasNoErrors();
        $this->assertFalse($executor->canWrite('templates', 'create'));
        config(['ai.crud.read' => false]);
        $this->assertArrayNotHasKey('count_templates', McpResourceRegistry::tools());
        $this->assertFalse($executor->canRead('blast_messages'));
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        $permissions['templates']['read'] = true;
        $integration->update(['permissions' => $permissions]);
        $this->assertFalse($executor->canWrite('templates', 'create'));
    }

    public function test_hub_assertions_are_one_time_and_need_a_jti(): void
    {
        $token = McpActorIdentity::sign($this->owner, 'http://source.test');
        $this->getJson('/api/ai/v1/templates/count', $this->headers($token))->assertOk();
        // A captured assertion cannot be replayed while it is still valid.
        $this->getJson('/api/ai/v1/templates/count', $this->headers($token))->assertStatus(403);
        // A correctly signed assertion without a jti is refused.
        $payload = ['app_key' => 'hireach', 'aud' => 'http://source.test', 'exp' => time() + 60,
            'tenant_id' => McpActorIdentity::tenant($this->owner), 'user_ref' => 'hireach_user_'.$this->owner->getKey()];
        ksort($payload);
        $raw = json_encode($payload, JSON_UNESCAPED_SLASHES);
        $encode = fn (string $value) => rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
        $withoutJti = $encode($raw).'.'.$encode(hash_hmac('sha256', $raw, $this->secret, true));
        $this->getJson('/api/ai/v1/templates/count', $this->headers($withoutJti))->assertStatus(403);
    }

    public function test_connector_requires_https_when_configured_and_is_never_cached(): void
    {
        $response = $this->getJson('/api/ai/v1/health', $this->headers())->assertOk()->assertHeader('X-Content-Type-Options', 'nosniff');
        $this->assertStringContainsString('no-store', (string) $response->headers->get('Cache-Control'));
        $this->assertStringContainsString('no-store', (string) $this->getJson('/api/ai/v1/health')->assertStatus(401)->headers->get('Cache-Control'));
        config(['ai.mcp.hub.require_https' => true]);
        $this->getJson('/api/ai/v1/health', $this->headers())->assertStatus(401);
        $this->getJson('https://source.test/api/ai/v1/health', $this->headers())->assertOk();
    }

    public function test_models_without_a_policy_or_rule_offer_no_ai_writes(): void
    {
        $this->configureCrudFixture();
        $this->grantFixtureAdminRole();
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        $permissions['blast_messages'] = ['enabled' => true, 'read' => true, 'create' => true, 'update' => true, 'delete' => true];
        $integration->update(['permissions' => $permissions]);
        // Config and admin flags alone are not enough: BlastMessage has neither a Laravel policy nor an authorize rule.
        $tools = McpResourceRegistry::tools();
        foreach (['create', 'update', 'delete'] as $action) {
            $this->assertArrayNotHasKey($action.'_blast_messages', $tools);
            $this->assertFalse(app(\App\Services\AI\AiResourceExecutor::class)->canWrite('blast_messages', $action));
        }
        $module = collect(McpResourceRegistry::manifest()['modules'])->firstWhere('key', 'blast_messages');
        $this->assertSame(['read'], $module['supported_operations']);
        $this->assertArrayNotHasKey('write_endpoints', $module);
        $this->postJson('/api/ai/v1/blast_messages/prepare_create', ['title' => 'Forged'], $this->headers())->assertStatus(403);
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->set('resources.blast_messages.create', true)->assertStatus(422);
        // An invalid rule is refused instead of silently allowing writes.
        config(['ai.crud.models.'.\App\Models\BlastMessage::class.'.authorize' => [AiWritePolicyFixture::class, 'missing']]);
        $this->expectException(\InvalidArgumentException::class);
        McpResourceRegistry::writePolicy('blast_messages');
    }

    public function test_billing_profile_rule_allows_only_updating_ones_own_profile(): void
    {
        $guard = new \App\Services\AI\AiToolAccessGuard();
        $own = new \App\Models\BillingUser(['user_id' => $this->owner->getKey()]);
        $other = new \App\Models\BillingUser(['user_id' => $this->owner->getKey() + 1]);
        $this->assertTrue($guard->ownBillingProfile($this->owner, 'update', $own));
        foreach (['create', 'delete'] as $action) { $this->assertFalse($guard->ownBillingProfile($this->owner, $action, $own)); }
        $this->assertFalse($guard->ownBillingProfile($this->owner, 'update', $other));
        $this->assertSame(['update'], config('ai.crud.models.'.\App\Models\BillingUser::class.'.operations'));
    }

    public function test_prepare_honours_idempotency_keys(): void
    {
        $this->configureCrudFixture();
        $key = ['Idempotency-Key' => 'tr_'.str_repeat('a', 32)];
        $first = $this->postJson('/api/ai/v1/templates/prepare_create', ['name' => 'Once only'], $this->headers() + $key)->assertOk();
        $again = $this->postJson('/api/ai/v1/templates/prepare_create', ['name' => 'Once only'], $this->headers() + $key)->assertOk();
        $this->assertSame($first->json('data.0.proposal_ref'), $again->json('data.0.proposal_ref'));
        $this->postJson('/api/ai/v1/templates/prepare_create', ['name' => 'Something else'], $this->headers() + $key)
            ->assertStatus(409)->assertJsonPath('error.code', 'IDEMPOTENCY_CONFLICT');
        $this->postJson('/api/ai/v1/templates/prepare_create', ['name' => 'Bad key'], $this->headers() + ['Idempotency-Key' => 'no spaces!'])
            ->assertStatus(403);
    }

    public function test_create_proposal_changes_no_business_data_until_actor_confirms_once(): void
    {
        $this->configureCrudFixture();
        $before = DB::table('templates')->count();
        $result = $this->postJson('/api/ai/v1/templates/prepare_create', ['name' => 'Reviewed draft', 'is_enabled' => false], $this->headers())
            ->assertOk()->assertJsonPath('data.0.requires_confirmation', true)
            ->assertJsonPath('data.0.tenant_id', 'hireach_account_1');
        $ref = $result->json('data.0.proposal_ref');
        $this->assertDatabaseCount('templates', $before);
        $this->actingAs(User::findOrFail(2))->postJson('/api/internal/ai/confirm', ['proposal_ref' => $ref])->assertStatus(403);
        $this->assertDatabaseCount('templates', $before);
        $this->actingAs($this->owner)->postJson('/api/internal/ai/confirm', ['proposal_ref' => $ref])->assertOk()
            ->assertJsonPath('data.action', 'create')->assertJsonPath('data.data.name', 'Reviewed draft')->assertDontSee('user_id');
        $this->assertDatabaseHas('templates', ['name' => 'Reviewed draft', 'user_id' => 1, 'is_enabled' => false]);
        $this->assertDatabaseCount('templates', $before + 1);
        $this->postJson('/api/internal/ai/confirm', ['proposal_ref' => $ref])->assertStatus(403);
        $this->assertDatabaseCount('templates', $before + 1);
        $this->postJson('/api/ai/v1/templates/create', ['name' => 'Unconfirmed'], $this->headers())->assertStatus(404);
        $this->assertDatabaseCount('templates', $before + 1);
    }

    public function test_update_and_soft_delete_use_exact_owned_refs_and_confirmed_values(): void
    {
        $this->configureCrudFixture();
        $this->postJson('/api/ai/v1/templates/prepare_update', ['ref' => 'tpl_2', 'name' => 'Wrong owner'], $this->headers())->assertStatus(403);
        $update = $this->postJson('/api/ai/v1/templates/prepare_update', ['ref' => 'tpl_1', 'name' => 'Renamed', 'is_enabled' => false], $this->headers())->assertOk();
        $this->assertDatabaseHas('templates', ['id' => 1, 'name' => 'Welcome 1']);
        $this->actingAs($this->owner)->postJson('/api/internal/ai/confirm', ['proposal_ref' => $update->json('data.0.proposal_ref')])->assertOk();
        $this->assertDatabaseHas('templates', ['id' => 1, 'name' => 'Renamed', 'is_enabled' => false, 'user_id' => 1]);
        $this->assertDatabaseHas('templates', ['id' => 2, 'name' => 'Welcome 2']);
        $delete = $this->postJson('/api/ai/v1/templates/prepare_delete', ['ref' => 'tpl_1'], $this->headers())->assertOk();
        $this->assertNull(DB::table('templates')->where('id', 1)->value('deleted_at'));
        $this->postJson('/api/internal/ai/confirm', ['proposal_ref' => $delete->json('data.0.proposal_ref')])->assertOk();
        $this->assertNotNull(DB::table('templates')->where('id', 1)->value('deleted_at'));
        $this->assertDatabaseCount('templates', 3);
        $this->assertNull(DB::table('templates')->where('id', 2)->value('deleted_at'));
    }

    public function test_crud_arguments_require_reviewed_fields_types_and_business_rules(): void
    {
        $this->configureCrudFixture();
        foreach ([['name' => 'Allowed', 'user_id' => 2], ['name' => 'Allowed', 'password' => 'not-secret'],
            ['name' => 'Allowed', 'is_enabled' => 'false'], ['name' => str_repeat('x', 81)],
            ['name' => 'Allowed', 'type' => 'unexpected'], ['name' => ['unexpected']], []] as $arguments) {
            $this->postJson('/api/ai/v1/templates/prepare_create', $arguments, $this->headers())->assertStatus(422);
        }
        $this->postJson('/api/ai/v1/templates/prepare_create', ['name' => 'private.canary@example.test'], $this->headers())->assertStatus(403);
        $this->postJson('/api/ai/v1/templates/prepare_update', ['ref' => 'tpl_1'], $this->headers())->assertStatus(422);
        $this->postJson('/api/ai/v1/templates/prepare_delete', ['ref' => 'tpl_1', 'name' => 'Forged'], $this->headers())->assertStatus(422);
        $this->postJson('/api/ai/v1/templates/prepare_delete', ['ref' => 'tpl_1'], ['Authorization' => 'Bearer '.$this->key])->assertStatus(403);
        $this->assertDatabaseCount('templates', 3);
        try { app(\App\Services\AI\AiResourceExecutor::class)->execute('templates', 'delete', ['ref' => 'tpl_1'], $this->owner); $this->fail('Unconfirmed execute accepted'); }
        catch (\RuntimeException $error) { $this->assertStringContainsString('confirmation', $error->getMessage()); }
        $this->assertNull(DB::table('templates')->where('id', 1)->value('deleted_at'));
    }

    public function test_prepared_change_is_invalidated_by_revocation_config_record_change_or_expiry(): void
    {
        foreach (['permission', 'global', 'configuration', 'record', 'expiry'] as $change) {
            $this->permissions(true);
            $this->configureCrudFixture();
            $executor = app(\App\Services\AI\AiResourceExecutor::class);
            $proposal = $executor->prepareProposal('templates', 'update', ['ref' => 'tpl_1', 'name' => 'Must not save'], $this->owner);
            if ($change === 'permission') {
                $integration = \App\Models\AiIntegration::findOrFail(1);
                $permissions = $integration->permissions;
                $permissions['templates']['update'] = false;
                $integration->update(['permissions' => $permissions]);
            } elseif ($change === 'global') { \App\Models\AiIntegration::findOrFail(1)->update(['enabled' => false]); }
            elseif ($change === 'configuration') { config(['ai.crud.models.'.\App\Models\Template::class.'.fields.name' => 'required|string|max:70']); }
            elseif ($change === 'record') { DB::table('templates')->where('id', 1)->update(['name' => 'External change']); }
            else { $this->travel(301)->seconds(); }
            try { $executor->commitProposal($proposal['proposal_ref'], $this->owner); $this->fail('Invalidated change committed: '.$change); }
            catch (\RuntimeException $error) { $this->assertNotSame('', $error->getMessage()); }
            $this->assertNotSame('Must not save', DB::table('templates')->where('id', 1)->value('name'));
            $this->travelBack();
        }
    }

    public function test_generic_crud_supports_another_owner_column_and_hard_delete_requires_explicit_config(): void
    {
        $this->registerProjectFixture();
        $this->projectPermission(true);
        config(['ai.crud.create' => true, 'ai.crud.update' => true, 'ai.crud.delete' => true,
            'ai.crud.models' => [AiProjectFixture::class => ['operations' => ['create', 'update', 'delete'],
                'fields' => ['title' => 'required|string|max:80', 'status' => 'sometimes|in:LIVE,DRAFT'],
                'defaults' => ['status' => 'DRAFT', 'active' => false, 'budget' => 0, 'private_email' => 'Internal default']]]]);
        $this->allowAiWrites(AiProjectFixture::class);
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        $permissions['projects']['create'] = $permissions['projects']['update'] = $permissions['projects']['delete'] = true;
        $integration->update(['permissions' => $permissions]);
        $executor = app(\App\Services\AI\AiResourceExecutor::class);
        $this->assertFalse($executor->canWrite('projects', 'delete'));
        $proposal = $executor->prepareProposal('projects', 'create', ['title' => 'Owned project'], $this->owner);
        $result = $executor->commitProposal($proposal['proposal_ref'], $this->owner);
        $this->assertSame('Owned project', $result['data']['title']);
        $this->assertArrayNotHasKey('private_email', $result['data']);
        $this->assertDatabaseHas('hub_projects', ['title' => 'Owned project', 'owner_id' => 1]);
        config(['ai.crud.models.'.AiProjectFixture::class.'.allow_hard_delete' => true]);
        $this->assertTrue($executor->canWrite('projects', 'delete'));
        $ref = 'projects_'.DB::table('hub_projects')->where('title', 'Owned project')->value('id');
        $delete = $executor->prepareProposal('projects', 'delete', ['ref' => $ref], $this->owner);
        $executor->commitProposal($delete['proposal_ref'], $this->owner);
        $this->assertDatabaseCount('hub_projects', 2);
    }

    public function test_generic_crud_infers_fillable_types_defaults_and_required_fields_without_model_config(): void
    {
        $this->registerProjectFixture();
        $this->projectPermission(true);
        config(['ai.crud.create' => true, 'ai.crud.update' => true, 'ai.crud.delete' => true,
            'ai.crud.allow_hard_delete' => true, 'ai.crud.models' => []]);
        $this->allowAiWrites(AiProjectFixture::class, AiRecordFixture::class);
        Schema::create('hub_records', function (Blueprint $t) {
            $t->id(); $t->unsignedBigInteger('user_id'); $t->string('label'); $t->boolean('active')->default(false);
            $t->double('rating')->default(1); $t->dateTime('reviewed_at')->nullable(); $t->string('optional_note')->nullable();
            $t->string('guarded_field')->default('Internal'); $t->unsignedInteger('otp')->default(0);
            $t->string('pin_code')->nullable(); $t->timestamps();
        });
        $integration = \App\Models\AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        $permissions['_resources']['records'] = ['model' => AiRecordFixture::class, 'owner' => 'user_id',
            'fields' => ['label' => 'string:40', 'active' => 'boolean', 'rating' => 'number', 'reviewed_at' => 'datetime',
                'optional_note' => 'string:80', 'guarded_field' => 'string', 'created_at' => 'datetime',
                'otp' => 'integer', 'pin_code' => 'string:20']];
        foreach (['projects', 'records'] as $resource) {
            $permissions[$resource] = ['read' => true, 'enabled' => true, 'create' => true, 'update' => true, 'delete' => true];
        }
        $integration->update(['permissions' => $permissions]);
        $tools = McpResourceRegistry::tools();
        $record = $tools['create_records']['input_schema'];
        $this->assertSame(['label'], $record['required']);
        $this->assertSame(40, $record['properties']['label']['maxLength']);
        $this->assertSame(['string', 'null'], $record['properties']['optional_note']['type']);
        $this->assertSame('number', $record['properties']['rating']['type']);
        foreach (['user_id', 'guarded_field', 'created_at'] as $field) { $this->assertArrayNotHasKey($field, $record['properties']); }
        // One-time and secret codes stay readable as registered but are never write inputs (MCP Hub refuses them).
        foreach (['otp', 'pin_code'] as $field) { $this->assertArrayNotHasKey($field, $record['properties']); }
        $executor = app(\App\Services\AI\AiResourceExecutor::class);
        // Different model, owner and fillable attributes use the same executor with no overrides.
        $project = $executor->prepareProposal('projects', 'create', ['title' => 'Generic project'], $this->owner);
        $executor->commitProposal($project['proposal_ref'], $this->owner);
        $this->assertDatabaseHas('hub_projects', ['title' => 'Generic project', 'owner_id' => 1, 'active' => false]);
        $proposal = $executor->prepareProposal('records', 'create', ['label' => 'Generic record', 'optional_note' => null,
            'rating' => 2.5, 'reviewed_at' => '2026-10-10T10:00:00+08:00'], $this->owner);
        $this->assertDatabaseCount('hub_records', 0);
        $executor->commitProposal($proposal['proposal_ref'], $this->owner);
        $this->assertDatabaseHas('hub_records', ['label' => 'Generic record', 'user_id' => 1, 'active' => false, 'rating' => 2.5]);
        $ref = 'records_'.DB::table('hub_records')->value('id');
        $update = $executor->prepareProposal('records', 'update', ['ref' => $ref, 'active' => true, 'reviewed_at' => null], $this->owner);
        $executor->commitProposal($update['proposal_ref'], $this->owner);
        $this->assertDatabaseHas('hub_records', ['active' => true, 'reviewed_at' => null]);
        $this->getJson('/api/ai/v1/records/list', $this->headers())->assertOk()
            ->assertJsonPath('data.0.reviewed_at', null)->assertJsonPath('data.0.active', true)
            ->assertJsonPath('data.0.rating', 2.5);
        foreach ([[], ['label' => str_repeat('x', 41)], ['label' => 'Valid', 'user_id' => 2],
            ['label' => 'Valid', 'guarded_field' => 'Bypass'], ['label' => 'Valid', 'rating' => 'bad'],
            ['label' => 'Valid', 'reviewed_at' => 'not a date'], ['label' => null]] as $arguments) {
            try { $executor->prepareProposal('records', 'create', $arguments, $this->owner); $this->fail('Invalid generic arguments accepted'); }
            catch (\Illuminate\Validation\ValidationException $error) { $this->assertDatabaseCount('hub_records', 1); }
        }
        $delete = $executor->prepareProposal('records', 'delete', ['ref' => $ref], $this->owner);
        $executor->commitProposal($delete['proposal_ref'], $this->owner);
        $this->assertDatabaseCount('hub_records', 0);
    }

    public function test_generic_fillable_changes_invalidate_pending_proposals_and_keep_admin_grants_authoritative(): void
    {
        $this->registerProjectFixture();
        $this->projectPermission(true);
        config(['ai.crud.create' => true, 'ai.crud.update' => true, 'ai.crud.models' => []]);
        $this->allowAiWrites(AiProjectFixture::class);
        $executor = app(\App\Services\AI\AiResourceExecutor::class);
        $this->assertFalse($executor->canWrite('projects', 'update'));
        $this->grantFixtureAdminRole();
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->set('resources.projects.update', true)->assertHasNoErrors();
        $this->assertTrue($executor->canWrite('projects', 'update'));
        $proposal = $executor->prepareProposal('projects', 'update', ['ref' => 'projects_1', 'title' => 'Pending edit'], $this->owner);
        AiProjectFixture::$editableTitle = false;
        try {
            $this->assertArrayNotHasKey('title', McpResourceRegistry::tools()['update_projects']['input_schema']['properties']);
            try { $executor->commitProposal($proposal['proposal_ref'], $this->owner); $this->fail('Old fillable policy accepted'); }
            catch (\RuntimeException $error) { $this->assertDatabaseHas('hub_projects', ['id' => 1, 'title' => 'Project 1']); }
        } finally { AiProjectFixture::$editableTitle = true; }
        \Livewire\Livewire::actingAs($this->owner)->test(\App\Http\Livewire\Table\AiAccessTable::class)
            ->set('resources.projects.update', false)->assertHasNoErrors();
        $this->assertFalse($executor->canWrite('projects', 'update'));
        // Fields and rules still follow the model; the only per-model setting is the explicit write authorization.
        $this->assertSame([AiProjectFixture::class => ['authorize' => [AiWritePolicyFixture::class, 'allow']]], config('ai.crud.models'));
    }

    public function test_hub_write_tool_requires_publication_and_returns_only_a_bound_proposal(): void
    {
        $this->configureCrudFixture();
        $spec = McpResourceRegistry::tools()['create_templates'];
        Http::fake(function ($request) use ($spec) {
            $result = $request['method'] === 'tools/list' ? ['tools' => [['name' => $spec['mcp_name'], 'inputSchema' => $spec['input_schema']]]]
                : ['isError' => false, 'structuredContent' => ['success' => true,
                    'data' => [app(\App\Services\AI\AiResourceExecutor::class)->prepareProposal('templates', 'create', $request['params']['arguments'], $this->owner)],
                    'meta' => ['contains_personal_data' => false]]];
            return Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => $result]);
        });
        $names = array_column(array_column(app(McpHubClient::class)->openaiTools($this->owner), 'function'), 'name');
        $this->assertContains('create_templates', $names);
        $this->assertNotContains('update_templates', $names);
        $prepared = app(McpHubClient::class)->query('create_templates', ['name' => 'From MCP'], $this->owner);
        $this->assertTrue($prepared['data']['requires_confirmation']);
        $this->assertDatabaseCount('templates', 3);
        $this->assertSame('templates', app(\App\Services\AI\AiResourceExecutor::class)->proposal($prepared['data']['proposal_ref'], $this->owner)['resource']);
    }

    public function test_crud_manifest_declares_source_write_routes_and_retains_existing_read_routes(): void
    {
        $this->configureCrudFixture();
        $module = collect(McpResourceRegistry::manifest()['modules'])->firstWhere('key', 'templates');
        $this->assertSame(['read', 'create', 'update', 'delete'], $module['supported_operations']);
        $this->assertSame(['create', 'update', 'delete'], array_column($module['write_endpoints'], 'operation'));
        $this->assertCount(3, $module['read_endpoints']);
        $this->assertNotContains('proposal_ref', $module['readable_fields']);
        $this->assertContains('ref', $module['writable_fields']);
        foreach ($module['write_endpoints'] as $route) {
            $this->assertFalse($route['safe_query']);
            $this->assertTrue($route['requires_user_context']);
            $this->assertSame('tenant_id', $route['tenant_field']);
        }
        config(['ai.crud.create' => false, 'ai.crud.update' => false, 'ai.crud.delete' => false]);
        $module = collect(McpResourceRegistry::manifest()['modules'])->firstWhere('key', 'templates');
        $this->assertSame(['read'], $module['supported_operations']);
        $this->assertArrayNotHasKey('write_endpoints', $module);
        $this->assertArrayNotHasKey('writable_fields', $module);
    }

    public function test_full_and_streamed_chat_append_only_the_server_proposal_and_do_not_commit(): void
    {
        $this->configureCrudFixture();
        $this->actingAs($this->owner);
        $spec = McpResourceRegistry::tools()['create_templates'];
        Http::fake(function ($request) use ($spec) {
            $result = $request['method'] === 'tools/list' ? ['tools' => [['name' => $spec['mcp_name'], 'inputSchema' => $spec['input_schema']]]]
                : ['structuredContent' => ['success' => true,
                    'data' => [app(\App\Services\AI\AiResourceExecutor::class)->prepareProposal('templates', 'create', $request['params']['arguments'], $this->owner)],
                    'meta' => ['contains_personal_data' => false]]];
            return Http::response(['jsonrpc' => '2.0', 'id' => $request['id'], 'result' => $result]);
        });
        foreach ([false, true] as $streamed) {
            $round = 0;
            $response = function ($messages, $options) use (&$round) {
                $this->assertContains('create_templates', array_column(array_column($options['tools'], 'function'), 'name'));
                if ($round++ === 0) {
                    return ['tool_calls' => array_map(fn ($id) => ['id' => $id, 'type' => 'function',
                        'function' => ['name' => 'create_templates', 'arguments' => '{"name":"Review me"}']], ['call_first', 'call_second'])];
                }
                $results = array_values(array_filter($messages, fn ($message) => $message['role'] === 'tool'));
                $this->assertTrue(json_decode($results[0]['content'], true)['data']['requires_confirmation']);
                $this->assertFalse(json_decode($results[1]['content'], true)['ok']);
                return ['content' => 'Review the change. <<<CONFIRM {"proposal_ref":"change_'.str_repeat('1', 32).'"} CONFIRM>>>'];
            };
            $this->mock(\App\Services\AI\AiProviderClient::class, function ($mock) use ($streamed, $response) {
                $mock->shouldReceive('usesMcpProvider')->andReturn(true);
                if ($streamed) {
                    $mock->shouldReceive('chatStream')->twice()->andReturnUsing(function ($model, $messages, $metadata, $options) use ($response) {
                        $message = $response($messages, $options);
                        if (isset($message['tool_calls'])) {
                            foreach ($message['tool_calls'] as $index => &$call) { $call['index'] = $index; }
                            unset($call);
                        }
                        yield 'data: '.json_encode(['choices' => [['delta' => $message]]])."\n\ndata: [DONE]\n\n";
                    });
                } else {
                    $mock->shouldReceive('chat')->twice()->andReturnUsing(fn ($model, $messages, $stream, $metadata, $options) =>
                        ['choices' => [['message' => $response($messages, $options)]]]);
                }
            });
            $agent = app(AiChatOrchestrator::class);
            $history = [['role' => 'user', 'content' => 'Buat template saya bernama Review me']];
            $reply = $streamed ? implode('', iterator_to_array($agent->stream('dummy-model', $history, $this->owner, [])))
                : $agent->complete('dummy-model', $history, $this->owner, []);
            if ($streamed) {
                $event = json_decode(substr(explode("\n", $reply)[0], 6), true);
                $reply = $event['choices'][0]['delta']['content'];
            }
            $this->assertSame(1, substr_count($reply, '<<<CONFIRM'));
            $this->assertStringNotContainsString('change_'.str_repeat('1', 32), $reply);
            $pending = app(\App\Services\AI\AiResourceExecutor::class)->parseProposal($reply);
            $this->assertSame('templates', $pending['resource']);
            $this->assertSame('create', $pending['action']);
            $this->assertStringContainsString('Review me', $pending['summary']);
            $this->assertDatabaseCount('templates', 3);
        }
    }

    public function test_config_authorization_callback_cannot_override_the_models_policy(): void
    {
        $this->configureCrudFixture();
        config(['ai.crud.models.'.\App\Models\Template::class.'.authorize' => [AiWritePolicyFixture::class, 'allow']]);
        \Illuminate\Support\Facades\Gate::policy(\App\Models\Template::class, AiWritePolicyFixture::class);
        $this->expectException(\Illuminate\Auth\Access\AuthorizationException::class);
        app(\App\Services\AI\AiResourceExecutor::class)->prepareProposal('templates', 'create', ['name' => 'Denied by policy'], $this->owner);
    }

    public function test_native_read_lookup_still_uses_registered_fields_and_user_scope_with_crud(): void
    {
        $this->configureCrudFixture();
        $executor = app(\App\Services\AI\AiResourceExecutor::class);
        $this->assertSame('Welcome 1', $executor->execute('templates', 'get', ['name' => 'Welcome 1'], $this->owner)['data']['name']);
        $this->expectException(\RuntimeException::class);
        $executor->execute('templates', 'get', ['name' => 'Welcome 2'], $this->owner);
    }

    public function test_chat_proposal_marker_uses_server_values_and_confirm_ignores_forged_arguments(): void
    {
        $this->configureCrudFixture();
        $this->actingAs($this->owner);
        $executor = app(\App\Services\AI\AiResourceExecutor::class);
        $proposal = $executor->prepareProposal('templates', 'create', ['name' => 'Approved value'], $this->owner);
        $ref = $proposal['proposal_ref'];
        $marker = '<<<CONFIRM '.json_encode(['proposal_ref' => $ref, 'summary' => 'Forged summary', 'arguments' => ['name' => 'Forged value']]).' CONFIRM>>>';
        $parsed = $executor->parseProposal($marker);
        $this->assertSame($proposal['summary'], $parsed['summary']);
        $this->assertArrayNotHasKey('arguments', $parsed);
        $this->assertNull($executor->parseProposal('<<<CONFIRM {"resource":"templates","action":"delete","arguments":{"ref":"tpl_1"}} CONFIRM>>>'));
        $chat = new \App\Http\Livewire\AI\Chat;
        $chat->sessionId = 'isolated-chat';
        $chat->pendingAction = $parsed + ['arguments' => ['name' => 'Forged value']];
        session()->put('hireach.ai.pending.1.isolated-chat', $parsed);
        $chat->confirmPending();
        $this->assertDatabaseHas('templates', ['name' => 'Approved value', 'user_id' => 1]);
        $this->assertDatabaseMissing('templates', ['name' => 'Forged value']);
        $chat->confirmPending();
        $this->assertDatabaseCount('templates', 4);
        $cancel = $executor->prepareProposal('templates', 'create', ['name' => 'Cancelled value'], $this->owner);
        $chat->pendingAction = ['proposal_ref' => $cancel['proposal_ref']];
        session()->put('hireach.ai.pending.1.isolated-chat', $chat->pendingAction);
        $chat->rejectPending();
        try { $executor->commitProposal($cancel['proposal_ref'], $this->owner); $this->fail('Cancelled proposal committed'); }
        catch (\RuntimeException $error) { $this->assertDatabaseCount('templates', 4); }
    }

    public function test_user_ai_navigation_follows_saved_status_on_desktop_and_mobile(): void
    {
        $this->prepareNavigationUser();
        \Illuminate\Support\Facades\Route::get('/_fixture/ai-navigation', fn () => view('navigation-menu'));
        $link = 'href="'.route('ai.chat').'"';
        $this->assertSame(2, substr_count($this->get('/_fixture/ai-navigation')->assertOk()->getContent(), $link));

        DB::table('ai_integrations')->insert(['id' => 2, 'name' => 'Current settings', 'api_url' => 'mcp://telixcell',
            'enabled' => false, 'permissions' => '{}']);
        $disabled = $this->get('/_fixture/ai-navigation')->assertOk()->getContent();
        $this->assertSame(0, substr_count($disabled, $link));
        $this->assertSame(2, substr_count($disabled, 'href="'.route('dashboard.balance').'"'));

        DB::table('ai_integrations')->where('id', 2)->update(['enabled' => true]);
        $this->assertSame(2, substr_count($this->get('/_fixture/ai-navigation')->assertOk()->getContent(), $link));
        DB::table('ai_integrations')->delete();
        $this->assertSame(0, substr_count($this->get('/_fixture/ai-navigation')->assertOk()->getContent(), $link));
    }

    public function test_user_ai_side_menus_follow_saved_status_for_new_and_existing_chats(): void
    {
        $this->prepareNavigationUser();
        \Illuminate\Support\Facades\Route::get('/_fixture/ai-sidebar', fn () => view('menu.user-menu'))->name('ai.chat');
        \Illuminate\Support\Facades\Route::get('/_fixture/ai-mobile', fn () => view('menu.user-menu-mobile'))->name('ai.chat.show');
        foreach ([false, true, false] as $enabled) {
            DB::table('ai_integrations')->where('id', 1)->update(['enabled' => $enabled]);
            foreach (['/_fixture/ai-sidebar', '/_fixture/ai-mobile'] as $url) {
                $html = $this->get($url)->assertOk()->getContent();
                $this->assertSame($enabled ? 1 : 0, substr_count($html, 'href="'.url('ai').'"'));
            }
        }
    }
}

class AiProjectFixture extends \Illuminate\Database\Eloquent\Model
{
    public static bool $editableTitle = true;
    protected $table = 'hub_projects';
    protected $fillable = ['title', 'status', 'active', 'budget'];
    protected $casts = ['active' => 'boolean', 'budget' => 'integer'];
    protected $attributes = ['status' => 'DRAFT', 'active' => false, 'budget' => 0, 'private_email' => 'Internal'];

    public function __construct(array $attributes = [])
    {
        parent::__construct($attributes);
        if (! self::$editableTitle) { $this->fillable(array_diff($this->getFillable(), ['title'])); }
    }
}

class AiRecordFixture extends \Illuminate\Database\Eloquent\Model
{
    protected $table = 'hub_records';
    protected $fillable = ['label', 'active', 'rating', 'reviewed_at', 'optional_note', 'user_id', 'created_at', 'otp', 'pin_code'];
    protected $casts = ['active' => 'boolean', 'rating' => 'double', 'reviewed_at' => 'datetime'];
}

class AiWritePolicyFixture
{
    public function allow(): bool { return true; }
    public function create(User $user): bool { return false; }
}

class AiNavigationWidgetFixture extends \Livewire\Component
{
    public $client_id;

    public function render()
    {
        return '<div></div>';
    }
}
