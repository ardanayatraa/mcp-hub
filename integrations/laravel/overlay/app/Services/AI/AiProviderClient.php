<?php

namespace App\Services\AI;

use App\Models\AiIntegration;
use App\Services\Mcp\McpClient;
use Illuminate\Http\Client\PendingRequest;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use RuntimeException;

class AiProviderClient
{
    private function mcpAi(): bool
    {
        $integration = AiIntegration::query()->latest('id')->first();

        return config('ai.mcp.ai_provider') === 'telixcell'
            && $integration?->enabled
            && $integration?->api_url === 'mcp://telixcell';
    }

    public function usesMcpProvider(): bool
    {
        return $this->mcpAi();
    }

    protected function integration(): AiIntegration
    {
        $integration = AiIntegration::query()
            ->latest('id')
            ->first();

        if (!$integration || ! $integration->enabled) {
            throw new RuntimeException(
                'AI integration is not configured or disabled.'
            );
        }

        if (config('ai.mcp.ai_only', true) && ! $this->mcpAi()) {
            throw new RuntimeException('AI Chat requires an active MCP integration.');
        }

        if (empty($integration->api_url)) {
            throw new RuntimeException(
                'AI endpoint is not configured.'
            );
        }

        if (empty($integration->api_key)
            && ! (config('ai.mcp.ai_provider') === 'telixcell' && $integration->api_url === 'mcp://telixcell')) {
            throw new RuntimeException(
                'AI API key is not configured.'
            );
        }

        return $integration;
    }

    protected function client(): PendingRequest
    {
        $integration = $this->integration();

        $request = Http::acceptJson()
            ->withToken($integration->api_key)
            ->withoutRedirecting()
            ->timeout((int) config('ai.request_timeout', 210))
            ->baseUrl($this->baseUrl($integration));

        $user = auth()->user();
        if ($user) {
            $headers = [
                'X-End-User-Id' => (string) $user->getKey(),
            ];
            $request = $request->withHeaders($headers);
        }

        return $request;
    }

    public function baseUrl(?AiIntegration $integration = null): string
    {
        $url = rtrim((string) ($integration ?? $this->integration())->api_url, '/');
        $url = preg_replace('#/api/v1/ai(?:/chat/completions|/models)?/?$#', '', $url) ?: $url;

        $parts = parse_url($url);
        $scheme = strtolower((string) ($parts['scheme'] ?? ''));
        $host = strtolower((string) ($parts['host'] ?? ''));
        $local = in_array($host, ['localhost', '127.0.0.1', '::1'], true)
            || (app()->runningUnitTests() && $host === 'ai.test');
        if (! is_array($parts) || $host === '' || ! in_array($scheme, ['http', 'https'], true)
            || ($scheme !== 'https' && ! (app()->environment('local', 'testing') && $local))
            || isset($parts['user'], $parts['pass']) || isset($parts['user'])
            || isset($parts['query']) || isset($parts['fragment'])) {
            throw new RuntimeException('AI endpoint must use HTTPS (or local HTTP) without credentials or query parameters.');
        }

        return rtrim($url, '/');
    }

    /**
     * @return string[]
     */
    public function allowedModels(): array
    {
        return array_values(array_filter(array_column($this->catalog(), 'id')));
    }

    public function defaultModel(): string
    {
        $catalog = $this->catalog();
        $ids = array_column($catalog, 'id');
        $remote = $catalog[0]['default'] ?? null;
        $preferred = (string) config('ai.default_model', '');

        if ($preferred !== '' && in_array($preferred, $ids, true)) {
            return $preferred;
        }

        foreach ($ids as $id) {
            if ($preferred !== '' && str_starts_with($id, $preferred.'-')) {
                return $id;
            }
        }

        $preferred = (string) $remote;

        if ($preferred !== '' && in_array($preferred, $ids, true)) {
            return $preferred;
        }

        if ($ids === []) {
            throw new RuntimeException('No models are available for this application.');
        }

        return $ids[0];
    }

    public function resolveModel(?string $model): string
    {
        $allowed = $this->allowedModels();
        $chosen = $model ?: $this->defaultModel();

        if ($allowed === [] || ! in_array($chosen, $allowed, true)) {
            throw new RuntimeException('Model is not allowed.');
        }

        return $chosen;
    }

    /**
     * @return array<string,string>
     */
    public function labeledModels(): array
    {
        $out = [];
        $seen = [];
        foreach ($this->catalog() as $row) {
            if (empty($row['id'])) {
                continue;
            }
            $label = $this->prettyLabel($row['id'], $row['name'] ?? null);
            $key = mb_strtolower($label);
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $out[$row['id']] = $label;
        }

        return $out;
    }

    public function prettyLabel(string $id, ?string $name = null): string
    {
        $name = is_string($name) ? trim($name) : '';
        if ($name !== '' && ! str_contains($name, '/') && strcasecmp($name, $id) !== 0) {
            return $name;
        }

        $slug = str_contains($id, '/') ? substr($id, strrpos($id, '/') + 1) : $id;
        $slug = trim((string) preg_replace('/[\-_]+/', ' ', $slug));
        if ($slug === '') {
            return $id;
        }

        $special = [
            'gpt' => 'GPT',
            'claude' => 'Claude',
            'gemini' => 'Gemini',
            'haiku' => 'Haiku',
            'sonnet' => 'Sonnet',
            'opus' => 'Opus',
            'flash' => 'Flash',
            'pro' => 'Pro',
            'mini' => 'Mini',
        ];

        $words = [];
        foreach (explode(' ', strtolower($slug)) as $word) {
            if ($word === '') {
                continue;
            }
            if (isset($special[$word])) {
                $words[] = $special[$word];
            } elseif (preg_match('/^\d/', $word)) {
                $words[] = $word;
            } else {
                $words[] = ucfirst($word);
            }
        }

        return implode(' ', $words) ?: $id;
    }

    public function forgetCatalog(): void
    {
        $integration = AiIntegration::query()->latest('id')->first();
        if ($integration) {
            Cache::forget($this->catalogKey($integration));
        }
    }

    /**
     * @return array<int,array{id:string,name:?string,default?:?string}>
     */
    protected function catalog(): array
    {
        $integration = $this->integration();
        $ttl = max(1, (int) config('ai.models_cache_ttl', 60));

        $cached = Cache::get($this->catalogKey($integration));
        if (is_array($cached) && $cached !== []) {
            return $cached;
        }

        if ($this->mcpAi()) {
            $result = app(McpClient::class)->call('list_ai_models');
            $rows = $result['data'] ?? null;
            $default = $result['default'] ?? null;
            if (! is_array($rows)) {
                throw new RuntimeException('Could not load AI models.');
            }
            $catalog = [];
            foreach ($rows as $row) {
                if (is_array($row) && is_string($row['id'] ?? null)) {
                    $catalog[] = ['id' => $row['id'], 'name' => $row['name'] ?? $row['id'], 'default' => $default];
                }
            }
            if ($catalog !== []) {
                Cache::put($this->catalogKey($integration), $catalog, $ttl);
            }
            return $catalog;
        }

        $response = $this->client()->timeout(15)->get('/api/v1/ai/models');

        if (! $response->successful()) {
            throw new RuntimeException('Could not load AI models.');
        }

        $rows = $response->json('data');
        if (! is_array($rows)) {
            return [];
        }

        $default = $response->json('default');
        $catalog = [];
        foreach ($rows as $row) {
            if (! is_array($row) || empty($row['id']) || ! is_string($row['id'])) {
                continue;
            }
            $catalog[] = [
                'id' => $row['id'],
                'name' => isset($row['name']) && is_string($row['name']) ? $row['name'] : $row['id'],
                'default' => is_string($default) ? $default : null,
            ];
        }

        if ($catalog !== []) {
            Cache::put($this->catalogKey($integration), $catalog, $ttl);
        }

        return $catalog;
    }

    protected function catalogKey(AiIntegration $integration): string
    {
        return $this->mcpAi()
            ? 'hireach.ai.models.mcp.telixcell.'.$integration->id
            : 'hireach.ai.models.v2.'.$integration->id;
    }

    public function chat(
        ?string $model,
        array $messages,
        bool $stream = false,
        array $metadata = [],
        array $options = []
    ): array {
        $model = $this->resolveModel($model);
        $metadata = array_intersect_key($metadata, array_flip([
            'end_user_id',
            'feature',
            'session_id',
        ]));

        $payload = [
            'model' => $model,
            'messages' => $this->maskMessages($messages),
            'stream' => $stream,
            'metadata' => $metadata,
        ];
        $payload = $this->withToolOptions($payload, $options);

        if ($this->mcpAi()) {
            unset($payload['stream']);
            $result = app(McpClient::class)->call('chat_ai', $payload);
            $integration = $this->integration();
            $integration->update(['last_used_at' => now()]);
            $message = data_get($result, 'choices.0.message');
            if (! is_array($message) || (! is_string($message['content'] ?? null) && empty($message['tool_calls']))) {
                throw new RuntimeException('AI service returned an invalid response.');
            }
            return $result;
        }

        $response = $this->client()->post(
            '/api/v1/ai/chat/completions',
            $payload
        );

        $integration = $this->integration();

        $integration->update([
            'last_used_at' => now(),
        ]);

        if (!$response->successful()) {
            $code = $response->json('error.code');
            if ($response->status() === 403 && $code === 'QUOTA_EXCEEDED') {
                throw new RuntimeException('This month\'s AI quota is used up.');
            }

            throw new RuntimeException(
                'AI service request failed with status ' .
                $response->status() .
                '.'
            );
        }

        $result = $response->json();
        $message = data_get($result, 'choices.0.message');
        if (! is_array($message) || (! is_string($message['content'] ?? null) && empty($message['tool_calls']))) {
            throw new RuntimeException('AI service returned an invalid response.');
        }

        return $result;
    }

    /**
     * @return \Generator<int,string>
     */
    public function chatStream(
        ?string $model,
        array $messages,
        array $metadata = [],
        array $options = []
    ): \Generator {
        if ($this->mcpAi()) {
            $result = $this->chat($model, $messages, false, $metadata, $options);
            $message = data_get($result, 'choices.0.message', []);
            yield 'data: '.json_encode(['choices' => [[
                'index' => 0,
                'message' => $message,
                'delta' => $message,
                'finish_reason' => 'stop',
            ]]], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)."\n\ndata: [DONE]\n\n";
            return;
        }

        $model = $this->resolveModel($model);
        $metadata = array_intersect_key($metadata, array_flip([
            'end_user_id',
            'feature',
            'session_id',
        ]));

        $payload = [
            'model' => $model,
            'messages' => $this->maskMessages($messages),
            'stream' => true,
            'metadata' => $metadata,
        ];
        $payload = $this->withToolOptions($payload, $options);

        $response = $this->client()
            ->timeout((int) config('ai.request_timeout', 210))
            ->withOptions(['stream' => true])
            ->post(
                '/api/v1/ai/chat/completions',
                $payload
            );

        $this->integration()->update([
            'last_used_at' => now(),
        ]);

        if (! $response->successful()) {
            $code = $response->json('error.code');
            if ($response->status() === 403 && $code === 'QUOTA_EXCEEDED') {
                throw new RuntimeException('This month\'s AI quota is used up.');
            }

            throw new RuntimeException(
                'AI service request failed with status '.$response->status().'.'
            );
        }

        $body = $response->toPsrResponse()->getBody();
        while (! $body->eof()) {
            $chunk = $body->read(256);
            if ($chunk !== '') {
                yield $chunk;
            }
        }
    }

    /**
     * @param  array<int,mixed>  $messages
     * @return array<int,mixed>
     */
    protected function maskMessages(array $messages): array
    {
        return array_map(function ($message) {
            if (! is_array($message)) {
                return $message;
            }
            if (isset($message['content']) && is_string($message['content'])) {
                $decoded = ($message['role'] ?? '') === 'tool' ? json_decode($message['content'], true) : null;
                $message['content'] = is_array($decoded)
                    ? json_encode(AiResourceExecutor::sanitize($decoded), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
                    : AiResourceExecutor::maskText($message['content']);
            }
            foreach ($message['tool_calls'] ?? [] as $index => $call) {
                $raw = $call['function']['arguments'] ?? null;
                if (! is_string($raw)) {
                    continue;
                }
                $decoded = json_decode($raw, true);
                $message['tool_calls'][$index]['function']['arguments'] = is_array($decoded)
                    ? json_encode(AiResourceExecutor::sanitize($decoded), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
                    : AiResourceExecutor::maskText($raw);
            }

            return $message;
        }, $messages);
    }

    /**
     * @param  array<string,mixed>  $payload
     * @param  array<string,mixed>  $options
     * @return array<string,mixed>
     */
    protected function withToolOptions(array $payload, array $options): array
    {
        if (! empty($options['tools']) && is_array($options['tools'])) {
            $payload['tools'] = $options['tools'];
        }
        if (array_key_exists('tool_choice', $options) && $options['tool_choice'] !== null && $options['tool_choice'] !== '') {
            $payload['tool_choice'] = $options['tool_choice'];
        }

        return $payload;
    }

    /**
     * @return array<string,mixed>
     */
    public function usage(): array
    {
        if ($this->mcpAi()) {
            return [];
        }
        $response = $this->client()->timeout(15)->get('/api/v1/ai/usage');
        if (! $response->successful()) {
            return [];
        }

        $json = $response->json();

        return is_array($json) ? $json : [];
    }

    /**
     * @return array<int,array{id:string,session_id:string,title:string}>
     */
    public function listConversations(): array
    {
        $local = array_values(array_map(
            fn (array $row) => [
                'id' => $row['session_id'],
                'session_id' => $row['session_id'],
                'title' => $row['title'],
            ],
            array_reverse($this->localConversations())
        ));
        if ($this->mcpAi()) {
            return $local;
        }
        $response = $this->client()->timeout(15)->get('/api/v1/ai/conversations');
        if ($response->status() === 404) {
            session()->put($this->localModeKey(), true);
            return $local;
        }
        if (! $response->successful()) {
            return $local;
        }

        session()->forget($this->localModeKey());

        $rows = $response->json('data');
        if (! is_array($rows)) {
            return [];
        }

        $out = [];
        foreach ($rows as $row) {
            if (! is_array($row)) {
                continue;
            }
            $sessionId = (string) ($row['session_id'] ?? $row['id'] ?? '');
            if ($sessionId === '') {
                continue;
            }
            $out[] = [
                'id' => (string) ($row['id'] ?? $sessionId),
                'session_id' => $sessionId,
                'title' => (string) ($row['title'] ?? 'New chat'),
            ];
        }

        $known = array_column($out, 'session_id');
        foreach ($local as $row) {
            if (! in_array($row['session_id'], $known, true)) {
                array_unshift($out, $row);
            }
        }

        return $out;
    }

    /**
     * @return array{session_id:string,title:string,messages:array<int,array{role:string,content:string}>}
     */
    public function getConversation(string $id): array
    {
        $id = $this->validConversationId($id);
        $local = $this->localConversations()[$id] ?? null;
        if (is_array($local)) {
            return $local;
        }
        if ($this->mcpAi()) {
            throw new RuntimeException('Conversation not found.');
        }
        $response = $this->client()->timeout(15)->get('/api/v1/ai/conversations/'.$id);
        if ($response->status() === 404) {
            throw new RuntimeException('Conversation not found.');
        }
        if (! $response->successful()) {
            throw new RuntimeException('Conversation not found.');
        }

        $messages = [];
        foreach ((array) $response->json('messages') as $row) {
            if (! is_array($row) || empty($row['role'])) {
                continue;
            }
            $message = [
                'role' => (string) $row['role'],
                'content' => (string) ($row['content'] ?? ''),
            ];
            if ($message['role'] === 'user' && end($messages) === $message) {
                continue;
            }
            $messages[] = $message;
        }

        return [
            'session_id' => (string) ($response->json('session_id') ?: $id),
            'title' => (string) ($response->json('title') ?: 'New chat'),
            'messages' => $messages,
        ];
    }

    public function deleteConversation(string $id): void
    {
        $id = $this->validConversationId($id);
        if ($this->mcpAi()) {
            $conversations = $this->localConversations();
            unset($conversations[$id]);
            session()->put($this->localConversationKey(), $conversations);
            return;
        }

        $response = $this->client()->timeout(15)->delete('/api/v1/ai/conversations/'.$id);
        if ($response->status() !== 404 && ! $response->successful()) {
            throw new RuntimeException('Could not delete the chat.');
        }
        $conversations = $this->localConversations();
        unset($conversations[$id]);
        session()->put($this->localConversationKey(), $conversations);
    }

    public function saveLocalConversation(string $id, string $title, array $messages): void
    {
        if ($id === '' || ! auth()->check()) {
            return;
        }

        $safeMessages = [];
        foreach (array_slice($messages, -20) as $message) {
            if (! is_array($message) || ! in_array($message['role'] ?? null, ['user', 'assistant'], true)) {
                continue;
            }
            $safeMessages[] = [
                'role' => $message['role'],
                'content' => mb_substr((string) ($message['content'] ?? ''), 0, 4000),
            ];
        }

        $conversations = $this->localConversations();
        unset($conversations[$id]);
        $conversations[$id] = [
            'session_id' => $id,
            'title' => mb_substr($title, 0, 80),
            'messages' => $safeMessages,
        ];
        session()->put($this->localConversationKey(), array_slice($conversations, -10, null, true));
    }

    private function localConversations(): array
    {
        if (! auth()->check()) {
            return [];
        }

        return (array) session()->get($this->localConversationKey(), []);
    }

    private function validConversationId(string $id): string
    {
        $id = trim($id);
        if (! preg_match('/^[A-Za-z0-9_-]{1,191}$/', $id)) {
            throw new RuntimeException('Conversation not found.');
        }

        return $id;
    }

    private function localConversationKey(): string
    {
        return 'hireach.ai.local_conversations.'.auth()->id();
    }

    private function localModeKey(): string
    {
        return 'hireach.ai.local_history_enabled.'.auth()->id();
    }
}
