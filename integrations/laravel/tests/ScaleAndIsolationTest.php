<?php

namespace Tests\Feature;

use App\Models\AiIntegration;
use App\Models\User;
use App\Services\Mcp\McpActorIdentity;
use Illuminate\Support\Facades\DB;

class ScaleAndIsolationTest extends McpConnectorTest
{
    private function actorHeaders(int $userId): array
    {
        return [
            'Authorization' => 'Bearer isolated-source-api-key-32-characters',
            'X-Hub-Assertion' => McpActorIdentity::sign(User::findOrFail($userId), 'http://source.test'),
        ];
    }

    private function seedMany(): array
    {
        $ownTemplateIds = [];
        $ownFailed = 1; // The parent fixture has one FAILED message for user 1.
        foreach ([1, 2] as $userId) {
            for ($start = 0; $start < 600; $start += 100) {
                $templates = [];
                $messages = [];
                for ($i = $start; $i < $start + 100; $i++) {
                    $templates[] = [
                        'user_id' => $userId, 'name' => "Scale Template {$userId}-{$i}",
                        'type' => 'text', 'is_enabled' => true,
                        'description' => 'private-canary@example.test',
                        'deleted_at' => $i < 10 ? now() : null,
                        'created_at' => now(), 'updated_at' => now(),
                    ];
                    $status = $i % 2 === 0 ? 'FAILED' : 'SUCCESS';
                    if ($userId === 1 && $status === 'FAILED' && $i >= 10) {
                        $ownFailed++;
                    }
                    $messages[] = [
                        'user_id' => $userId, 'title' => "Scale Message {$userId}-{$i}",
                        'type' => 'sms', 'status' => $status,
                        'msisdn' => '6281234567890', 'message_content' => 'private-canary@example.test',
                        'deleted_at' => $i < 10 ? now() : null,
                        'created_at' => now(), 'updated_at' => now(),
                    ];
                }
                DB::table('templates')->insert($templates);
                DB::table('blast_messages')->insert($messages);
            }
        }
        $ownTemplateIds = DB::table('templates')->where('user_id', 1)
            ->whereNull('deleted_at')->pluck('id')->all();
        return [$ownTemplateIds, $ownFailed];
    }

    public function test_large_dataset_pagination_filters_and_access_revocation(): void
    {
        [$ownTemplateIds, $ownFailed] = $this->seedMany();
        $expected = count($ownTemplateIds);
        $this->assertSame(592, $expected);
        $this->getJson('/api/ai/v1/templates/count', $this->actorHeaders(1))
            ->assertOk()->assertJsonPath('data.0.count', $expected);
        $this->getJson('/api/ai/v1/templates/count', $this->actorHeaders(2))
            ->assertOk()->assertJsonPath('data.0.count', 591);

        $seen = [];
        $cursor = null;
        do {
            $url = '/api/ai/v1/templates/list?limit=50'.($cursor ? '&cursor='.$cursor : '');
            $page = $this->getJson($url, $this->actorHeaders(1))->assertOk()
                ->assertJsonPath('meta.total_count', $expected);
            $page->assertJsonPath('meta.coverage', $page->json('meta.has_more') ? 'partial' : 'complete');
            $this->assertLessThanOrEqual(50, count($page->json('data')));
            $this->assertStringNotContainsString('private-canary@example.test', $page->getContent());
            $this->assertStringNotContainsString('msisdn', $page->getContent());
            foreach ($page->json('data') as $row) {
                $this->assertSame('hireach_account_1', $row['tenant_id']);
                $seen[] = (int) substr($row['ref'], 4);
            }
            $cursor = $page->json('meta.next_cursor');
        } while ($cursor !== null);
        $this->assertCount($expected, $seen);
        $this->assertSame($ownTemplateIds, array_values(array_intersect($ownTemplateIds, $seen)));
        $this->assertCount($expected, array_unique($seen));

        $this->getJson('/api/ai/v1/blast_messages/count?status=FAILED', $this->actorHeaders(1))
            ->assertOk()->assertJsonPath('data.0.count', $ownFailed);
        $this->getJson('/api/ai/v1/blast_messages/count?status=UNKNOWN', $this->actorHeaders(1))
            ->assertStatus(422);
        $this->getJson('/api/ai/v1/templates/list?limit=51', $this->actorHeaders(1))
            ->assertStatus(422);
        $this->getJson('/api/ai/v1/templates/list?user_id=2', $this->actorHeaders(1))
            ->assertStatus(403);
        $this->getJson('/api/ai/v1/templates/get?name=Scale%20Template%202-100', $this->actorHeaders(1))
            ->assertOk()->assertJsonCount(0, 'data');

        $integration = AiIntegration::findOrFail(1);
        $permissions = $integration->permissions;
        $permissions['templates']['read'] = false;
        $integration->update(['permissions' => $permissions]);
        $this->getJson('/api/ai/v1/templates/count', $this->actorHeaders(1))->assertStatus(403);
        $this->getJson('/api/ai/v1/blast_messages/count', $this->actorHeaders(1))->assertOk();
    }
}
