<?php

namespace App\Services\AI;

use App\Models\User;
use App\Services\Mcp\McpClient;
use App\Services\Mcp\McpHubClient;
use App\Services\Mcp\McpResourceRegistry;
use Illuminate\Support\Str;

class AiChatOrchestrator
{
    private const MAX_TOOL_ROUNDS = 3;

    public const USER_COUNT_UNAVAILABLE_REPLY = 'Saya belum memiliki tool yang diizinkan untuk menghitung user HiReach.';

    private array $reportLinks = [];
    private ?string $pendingProposal = null;

    public function __construct(
        private AiProviderClient $ai,
        private AiResourceExecutor $tools,
        private McpClient $mcp
    ) {
    }

    /**
     * @param  array<int,array<string,mixed>>  $history
     */
    public function complete(?string $model, array $history, User $user, array $metadata): string
    {
        if (McpHubClient::enabled()) { \App\Services\Mcp\McpPrivacyGuard::messages($history); }
        $this->assertMcpTransport();

        if (self::asksAboutCapabilities($history)) {
            return $this->capabilityReply($history, $user);
        }

        if ($this->userCountToolUnavailable($history, $user)) {
            return self::USER_COUNT_UNAVAILABLE_REPLY;
        }

        if (($denied = $this->unavailableResourceReply($history, $user)) !== null) {
            return $denied;
        }

        $this->reportLinks = [];
        $this->pendingProposal = null;
        $outOfScope = self::isOutOfScope($history);
        $messages = $this->seed($history, $user, $outOfScope);
        $dataQuestion = $this->asksAboutHireachData($history);
        $tools = ! $outOfScope && ($dataQuestion || $this->wantsTools($history))
            ? $this->availableTools($user)
            : [];
        $mustUseTool = $tools !== [] && $dataQuestion;

        for ($round = 0; $round < self::MAX_TOOL_ROUNDS + 1; $round++) {
            $options = [];
            if ($tools !== []) {
                $options['tools'] = $tools;
                $options['tool_choice'] = $round >= self::MAX_TOOL_ROUNDS
                    ? 'none'
                    : ($round === 0 && $mustUseTool ? 'required' : 'auto');
            }

            $result = $this->ai->chat($model, $messages, false, $metadata, $options);
            $message = $result['choices'][0]['message'] ?? [];
            if (! is_array($message)) {
                $message = [];
            }

            $calls = $this->normalizeToolCalls($message['tool_calls'] ?? []);
            if ($round === 0 && $mustUseTool && $calls === []) {
                return 'Data HiReach belum bisa diperiksa saat ini.';
            }
            if ($calls === [] || $tools === [] || $round >= self::MAX_TOOL_ROUNDS) {
                return trim(self::cleanReportReply((string) ($message['content'] ?? '')).$this->reportMarkdown().$this->proposalMarker());
            }

            $messages[] = [
                'role' => 'assistant',
                'content' => $message['content'] ?? null,
                'tool_calls' => $calls,
            ];
            $messages = array_merge($messages, $this->toolMessages($calls, $user));
        }

        return '';
    }

    /**
     * Yield raw SSE bytes for the browser. Tool-call rounds are not forwarded.
     *
     * @param  array<int,array<string,mixed>>  $history
     * @return \Generator<int,string>
     */
    public function stream(?string $model, array $history, User $user, array $metadata): \Generator
    {
        if (McpHubClient::enabled()) { \App\Services\Mcp\McpPrivacyGuard::messages($history); }
        $this->assertMcpTransport();

        if (self::asksAboutCapabilities($history)) {
            yield 'data: '.json_encode(['choices' => [[
                'index' => 0,
                'delta' => ['content' => $this->capabilityReply($history, $user)],
            ]]], JSON_UNESCAPED_UNICODE)."\n\ndata: [DONE]\n\n";
            return;
        }

        if ($this->userCountToolUnavailable($history, $user)) {
            yield 'data: '.json_encode(['choices' => [[
                'index' => 0,
                'delta' => ['content' => self::USER_COUNT_UNAVAILABLE_REPLY],
            ]]], JSON_UNESCAPED_UNICODE)."\n\ndata: [DONE]\n\n";

            return;
        }

        if (($denied = $this->unavailableResourceReply($history, $user)) !== null) {
            yield 'data: '.json_encode(['choices' => [[
                'index' => 0, 'delta' => ['content' => $denied],
            ]]], JSON_UNESCAPED_UNICODE)."\n\ndata: [DONE]\n\n";
            return;
        }

        $this->reportLinks = [];
        $this->pendingProposal = null;
        $outOfScope = self::isOutOfScope($history);
        $messages = $this->seed($history, $user, $outOfScope);
        $dataQuestion = $this->asksAboutHireachData($history);
        $tools = ! $outOfScope && ($dataQuestion || $this->wantsTools($history))
            ? $this->availableTools($user)
            : [];
        $mustUseTool = $tools !== [] && $dataQuestion;

        if ($tools === []) {
            foreach ($this->ai->chatStream($model, $messages, $metadata, []) as $chunk) {
                yield $chunk;
            }

            return;
        }

        for ($round = 0; $round < self::MAX_TOOL_ROUNDS + 1; $round++) {
            $options = [
                'tools' => $tools,
                'tool_choice' => $round >= self::MAX_TOOL_ROUNDS
                    ? 'none'
                    : ($round === 0 && $mustUseTool ? 'required' : 'auto'),
            ];

            $buffer = '';
            foreach ($this->ai->chatStream($model, $messages, $metadata, $options) as $chunk) {
                $buffer .= $chunk;
            }

            $calls = $this->toolCallsFromSse($buffer);
            if ($round === 0 && $mustUseTool && $calls === []) {
                yield 'data: '.json_encode(['choices' => [[
                    'index' => 0,
                    'delta' => ['content' => 'Data HiReach belum bisa diperiksa saat ini.'],
                ]]], JSON_UNESCAPED_UNICODE)."\n\ndata: [DONE]\n\n";
                return;
            }
            if ($calls !== [] && $tools !== [] && $round < self::MAX_TOOL_ROUNDS) {
                $messages[] = [
                    'role' => 'assistant',
                    'content' => null,
                    'tool_calls' => $calls,
                ];
                $messages = array_merge($messages, $this->toolMessages($calls, $user));
                continue;
            }

            if ($calls !== [] && $round >= self::MAX_TOOL_ROUNDS && ! $this->sseHasContent($buffer)) {
                $message = 'AI could not finish this request.'.$this->reportMarkdown().$this->proposalMarker();
                yield 'data: '.json_encode(['choices' => [[
                    'index' => 0,
                    'delta' => ['content' => $message],
                ]]], JSON_UNESCAPED_SLASHES)."\n\ndata: [DONE]\n\n";
                return;
            }

            if ($buffer !== '' || $this->reportLinks !== [] || $this->pendingProposal !== null) {
                $buffer = $this->appendReportEvent($buffer);
                if (! str_ends_with($buffer, "\n")) {
                    $buffer .= "\n";
                }
                yield $buffer;
            }

            return;
        }
    }

    /**
     * @param  array<int,array<string,mixed>>  $history
     */
    protected function wantsTools(array $history): bool
    {
        $text = '';
        for ($i = count($history) - 1; $i >= 0; $i--) {
            if (($history[$i]['role'] ?? '') === 'user') {
                $text = trim((string) ($history[$i]['content'] ?? ''));
                break;
            }
        }
        $question = mb_strtolower($text);
        if ((str_contains($question, 'data') && str_contains($question, 'akses') && str_contains($question, 'bisa'))
            || (str_contains($question, 'what data') && str_contains($question, 'access'))) {
            return false;
        }
        if ($text === '' || mb_strlen($text) > 48) {
            return $text !== '';
        }

        $norm = mb_strtolower($text);
        $norm = preg_replace('/[^\p{L}\p{N}\s]/u', '', $norm) ?? $norm;
        $norm = trim(preg_replace('/\s+/', ' ', $norm) ?? $norm);

        if (self::isAboutChatContext($norm)) {
            return false;
        }

        return ! in_array($norm, [
            'hi', 'hai', 'halo', 'hello', 'hey', 'hallo',
            'pagi', 'siang', 'sore', 'malam',
            'thanks', 'thank you', 'makasih', 'terima kasih',
            'ok', 'oke', 'okay', 'yo', 'test',
        ], true);
    }

    private function asksAboutHireachData(array $history): bool
    {
        for ($i = count($history) - 1; $i >= 0; $i--) {
            if (($history[$i]['role'] ?? '') === 'user') {
                return self::mentionsRegisteredResource((string) ($history[$i]['content'] ?? ''))
                    || self::isDataFollowUp($history);
            }
        }

        return false;
    }

    /** @param array<int,array<string,mixed>> $history */
    public static function isOutOfScope(array $history): bool
    {
        if (self::asksAboutCapabilities($history)) { return false; }
        $latest = '';
        $previous = '';
        for ($i = count($history) - 1; $i >= 0; $i--) {
            if (($history[$i]['role'] ?? '') !== 'user') {
                continue;
            }
            if ($latest === '') {
                $latest = trim((string) ($history[$i]['content'] ?? ''));
            } else {
                $previous = trim((string) ($history[$i]['content'] ?? ''));
                break;
            }
        }

        if ($latest === '') {
            return false;
        }

        $question = mb_strtolower($latest);
        $domain = '/\b(?:hireach|hi\s*reach|templates?|templat|blast|kampanye|campaigns?|scheduler|jadwal|dashboard|contacts?|kontak|audience|sms|waba|whatsapp|email|validasi|validation|billing|tagihan|saldo|payments?|pembayaran|reports?|laporan|live\s*chat|ai\s*chat|admin|pengaturan|settings|users?|pengguna|akun|member)\b/iu';
        if (preg_match($domain, $question) === 1 || self::mentionsRegisteredResource($question)) {
            return false;
        }

        if (preg_match('/^(?:hi|hai|halo|hello|hey|hallo|selamat (?:pagi|siang|sore|malam)|terima kasih|makasih|thanks|thank you|ok|oke|test)[\s!.?]*$/iu', $question) === 1
            || preg_match('/^(?:apa yang bisa (?:anda|kamu) (?:lakukan|akses)|what can you do|data apa (?:saja )?yang bisa (?:anda|kamu) akses)[\s?.!]*$/iu', $question) === 1
            || self::isAboutChatContext($question)) {
            return false;
        }

        $followUp = '/^(?:berapa (?:jumlah|total)(?:nya)?|(?:yang )?tadi|(?:lebih )?detail(?:nya)?|rinci(?:annya)?|lanjut(?:kan)?|tampilkan lagi|jelaskan lagi|apa statusnya)[\s?.!]*$/iu';
        if ($previous !== '' && preg_match($domain, mb_strtolower($previous)) === 1
            && preg_match($followUp, $question) === 1) {
            return false;
        }

        if (self::isDataFollowUp($history)) {
            return false;
        }

        return true;
    }

    /** @param array<int,array<string,mixed>> $history */
    private static function isDataFollowUp(array $history): bool
    {
        $latest = '';
        $hasPriorDataQuestion = false;
        for ($i = count($history) - 1; $i >= 0; $i--) {
            if (($history[$i]['role'] ?? '') !== 'user') {
                continue;
            }
            $content = mb_strtolower(trim((string) ($history[$i]['content'] ?? '')));
            if ($latest === '') {
                $latest = $content;
            } elseif (self::mentionsRegisteredResource($content)) {
                $hasPriorDataQuestion = true;
                break;
            }
        }

        if (! $hasPriorDataQuestion || $latest === '' || mb_strlen($latest) > 100) {
            return false;
        }

        return preg_match('/^(?:ya|iya|boleh|oke|ok|lanjut)[\s?.!]*$/iu', $latest) === 1
            || preg_match('/\b(?:daftar(?:nya)?|detail(?:nya)?|rinci(?:an(?:nya)?)?|semua data|lihat|tampilkan|sajikan|yang|kasih|kasi)\b/iu', $latest) === 1;
    }

    private static function mentionsRegisteredResource(string $question): bool
    {
        $question = mb_strtolower($question);
        foreach (AiResourceExecutor::resources() as $key => $resource) {
            $terms = $resource['keywords'] ?? [str_replace('_', ' ', (string) $key), $resource['label'] ?? ''];
            foreach ($terms as $term) {
                $term = trim(mb_strtolower((string) $term));
                if ($term !== '' && preg_match('/(?<!\pL)'.preg_quote($term, '/').'(?!\pL)/iu', $question) === 1) {
                    return true;
                }
            }
        }

        return false;
    }

    private static function isAboutChatContext(string $question): bool
    {
        $question = mb_strtolower($question);
        $question = preg_replace('/[^\p{L}\p{N}\s]/u', ' ', $question) ?? $question;
        $question = trim(preg_replace('/\s+/', ' ', $question) ?? $question);

        return preg_match('/^(?:' .
            '(?:kamu|anda|kau|lu|lo)(?: ini)? siapa(?: sih)?|' .
            'siapa (?:kamu|anda|kau|lu|lo)(?: ini)?|' .
            '(?:ini )?(?:ai|asisten|assistant) (?:apa|siapa)(?: ini)?|' .
            '(?:kamu|anda) (?:asisten|assistant) (?:apa|siapa)|' .
            'apa (?:fungsi|tugas)(?:mu| kamu| anda)|' .
            '(?:saya|aku)(?: ini)? siapa|siapa (?:saya|aku)|who am i|' .
            '(?:ini )?(?:web|website|situs|aplikasi|platform)(?: ini)? apa|' .
            '(?:web|website|situs|aplikasi|platform) apa ini|' .
            'who are you|what are you|who is this assistant|what is this assistant|' .
            'what (?:site|website|app|application) is this' .
            ')$/iu', $question) === 1;
    }

    /** @param array<int,array<string,mixed>> $history */
    private function userCountToolUnavailable(array $history, User $user): bool
    {
        $question = '';
        for ($i = count($history) - 1; $i >= 0; $i--) {
            if (($history[$i]['role'] ?? '') === 'user') {
                $question = mb_strtolower((string) ($history[$i]['content'] ?? ''));
                break;
            }
        }

        if (preg_match('/\b(?:user|users|pengguna|akun|member)\b/iu', $question) !== 1
            || preg_match('/\b(?:berapa|jumlah|total|count|how many)\b/iu', $question) !== 1) {
            return false;
        }

        if (self::mentionsRegisteredResource($question)) { return false; }

        foreach ($this->availableTools($user) as $tool) {
            if (($tool['function']['name'] ?? '') === 'count_users') {
                return false;
            }
        }

        return true;
    }

    /**
     * @param  array<int,array<string,mixed>>  $history
     * @return array<int,array<string,mixed>>
     */
    protected function seed(array $history, User $user, bool $outOfScope = false): array
    {
        $names = $outOfScope ? [] : (($this->ai->usesMcpProvider() || McpHubClient::enabled())
            ? array_map(fn (array $tool) => $tool['function']['name'], $this->availableTools($user))
            : null);

        return array_merge([$this->tools->systemMessage($user, '', $names)], array_values($history));
    }

    private function availableTools(User $user): array
    {
        return McpHubClient::enabled() ? app(McpHubClient::class)->openaiTools($user) : $this->tools->openaiTools($user);
    }

    /** Permission inventory is metadata, never an AI guess or a data query. */
    public static function asksAboutCapabilities(array $history): bool
    {
        $question = self::latestUserText($history);
        if (preg_match('/\b(?:apa|mana|what|which)\b/iu', $question)
            && preg_match('/\b(?:data|models?|tabel|tools?|akses|access|laporan|reports?|ekspor|export)\b/iu', $question)
            && preg_match('/\b(?:bisa|dapat|mampu|akses|access|izinkan|diizinkan|tersedia|terhubung|available|connected|can|sajikan|menyajikan)\b/iu', $question)) {
            return true;
        }
        return preg_match('/\b(?:apa yang bisa (?:anda|kamu|lu|lo) (?:lakukan|bantu)|what can you do)\b/iu', $question) === 1
            || preg_match('/\b(?:daftar|list)\b.*\b(?:model|tools?|data)\b.*\b(?:diizinkan|tersedia|available|accessible)\b/iu', $question) === 1;
    }

    private static function latestUserText(array $history): string
    {
        for ($i = count($history) - 1; $i >= 0; $i--) {
            if (($history[$i]['role'] ?? '') === 'user') {
                return trim((string) ($history[$i]['content'] ?? ''));
            }
        }
        return '';
    }

    /** A named unavailable model must never be replaced with another model's tool. */
    private function unavailableResourceReply(array $history, User $user): ?string
    {
        $question = self::latestUserText($history);
        if (! preg_match('/\b(?:tampilkan|lihat|ambil|sajikan|daftar|data|berapa|jumlah|total|hitung|terakhir|terbaru|list|show|get|fetch|count|latest|last|records?|export|ekspor|download|unduh|buat|tambahkan|ubah|edit|update|hapus|delete|remove)\b/iu', $question)) {
            return null;
        }

        $resources = McpResourceRegistry::resources();
        $models = McpResourceRegistry::modelOptions();
        foreach ($resources as $spec) { $models[$spec['model']] = class_basename($spec['model']); }
        $aliases = [];
        foreach ($models as $class => $name) {
            $name = str_replace('_', ' ', Str::snake(class_basename($class)));
            foreach ([$name, Str::plural($name), class_basename($class), Str::plural(class_basename($class))] as $term) {
                $aliases[mb_strtolower($term)] = $class;
            }
        }
        foreach ($resources as $key => $spec) {
            foreach ([$key, str_replace('_', ' ', $key), $spec['label'], ...($spec['keywords'] ?? [])] as $term) {
                $term = trim((string) $term);
                if ($term !== '') {
                    foreach ([$term, Str::singular($term), Str::plural($term)] as $alias) {
                        $aliases[mb_strtolower($alias)] = $spec['model'];
                    }
                }
            }
        }
        // Match Billing Users before Users, or Blast Messages before Messages.
        uksort($aliases, fn ($a, $b) => mb_strlen($b) <=> mb_strlen($a));
        $mentioned = [];
        foreach ($aliases as $term => $class) {
            $pattern = '/(?<![\pL\pN_])'.preg_quote($term, '/').'(?![\pL\pN_])/iu';
            if (preg_match($pattern, $question) === 1) {
                $mentioned[$class] = true;
                $question = preg_replace($pattern, ' ', $question) ?? $question;
            }
        }
        if ($mentioned === []) { return null; }

        $available = $this->availableTools($user);
        $index = McpResourceRegistry::tools();
        $permitted = [];
        foreach ($available as $definition) {
            $tool = $index[$definition['function']['name'] ?? ''] ?? null;
            if ($tool && isset($resources[$tool['resource']])) {
                $permitted[$resources[$tool['resource']]['model']] = true;
            }
        }
        if (array_diff_key($mentioned, $permitted) === []) { return null; }

        $english = preg_match('/\b(?:show|list|get|fetch|count|latest|records?|my)\b/i', self::latestUserText($history)) === 1;
        return ($english ? 'I do not have access to the requested data model.'
            : 'Saya tidak punya akses ke model data yang Anda minta.')."\n\n"
            .$this->capabilityReply($history, $user, $available);
    }

    private function capabilityReply(array $history, User $user, ?array $availableTools = null): string
    {
        $english = preg_match('/\b(?:what|which|can|available|accessible)\b/i', self::latestUserText($history)) === 1;
        $index = \App\Services\Mcp\McpResourceRegistry::tools();
        $resources = [];
        foreach ($availableTools ?? $this->availableTools($user) as $available) {
            $tool = $index[$available['function']['name'] ?? ''] ?? null;
            if (! $tool) { continue; }
            $operation = isset($tool['phase']) ? $tool['action'] : 'read';
            $resources[$tool['resource']]['label'] = $tool['label'];
            $resources[$tool['resource']]['operations'][$operation] = true;
        }
        if ($resources === []) {
            return $english ? 'No data models are currently allowed for your account.'
                : 'Belum ada model data yang diizinkan untuk akun Anda.';
        }
        $labels = $english ? ['read' => 'read', 'create' => 'create', 'update' => 'update', 'delete' => 'delete']
            : ['read' => 'baca', 'create' => 'tambah', 'update' => 'ubah', 'delete' => 'hapus'];
        $lines = [];
        foreach ($resources as $resource) {
            $operations = array_keys(array_intersect_key($labels, $resource['operations']));
            $name = str_replace(["\r", "\n"], ' ', $resource['label']);
            $name = str_replace(['\\', '*', '_', '[', ']'], ['\\\\', '\\*', '\\_', '\\[', '\\]'], $name);
            $lines[] = '- '.$name.' — '.implode(', ', array_map(fn ($operation) => $labels[$operation], $operations));
        }
        return ($english ? "Available data:\n\n" : "Data yang bisa diakses sekarang:\n\n")
            .implode("\n", $lines).($english ? "\n\nOnly your own records." : "\n\nHanya data milik akun Anda.");
    }

    /**
     * @param  array<int,array<string,mixed>>  $calls
     * @return array<int,array<string,mixed>>
     */
    protected function toolMessages(array $calls, User $user): array
    {
        $out = [];
        foreach ($calls as $call) {
            $name = (string) ($call['function']['name'] ?? '');
            $rawArgs = $call['function']['arguments'] ?? '{}';
            $arguments = is_array($rawArgs) ? $rawArgs : json_decode((string) $rawArgs, true);
            if (! is_array($arguments)) {
                $arguments = [];
            }

            try {
                $spec = \App\Services\Mcp\McpResourceRegistry::tools()[$name] ?? [];
                if (isset($spec['phase']) && $this->pendingProposal !== null) {
                    throw new \RuntimeException('Review the existing proposal first.');
                }
                $payload = ($this->ai->usesMcpProvider() || McpHubClient::enabled()) && $name !== 'export_report'
                    ? $this->mcp->query('hireach', $name, $arguments, $user)
                    : $this->tools->callTool($name, $arguments, $user);
                if (isset($spec['phase'])) {
                    $ref = (string) ($payload['data']['proposal_ref'] ?? '');
                    $this->tools->proposal($ref, $user);
                    $this->pendingProposal = $ref;
                }
                if ($name === 'export_report' && is_string($payload['url'] ?? null)) {
                    $this->reportLinks[] = [
                        'url' => $payload['url'],
                        'format' => $payload['format'] ?? 'xlsx',
                    ];
                    unset($payload['url']);
                    $payload['download_ready'] = true;
                }
                $content = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) ?: '{}';
            } catch (\Throwable $e) {
                $content = '{"ok":false,"error":"AI tool request failed."}';
            }

            $out[] = [
                'role' => 'tool',
                'tool_call_id' => (string) ($call['id'] ?? ('call_'.bin2hex(random_bytes(6)))),
                'content' => $content,
            ];
        }

        return $out;
    }

    private function assertMcpTransport(): void
    {
        if (config('ai.mcp.ai_only', true) && ! $this->ai->usesMcpProvider()) {
            throw new \RuntimeException('AI Chat requires an active MCP integration.');
        }
    }

    private function reportMarkdown(): string
    {
        $links = [];
        foreach ($this->reportLinks as $report) {
            $label = $report['format'] === 'pdf' ? 'Download PDF' : 'Download Excel';
            $links[] = '['.$label.']('.$report['url'].')';
        }

        return $links === [] ? '' : "\n\n".implode("\n", $links);
    }

    private function proposalMarker(): string
    {
        return $this->pendingProposal === null ? '' : "\n<<<CONFIRM ".json_encode(['proposal_ref' => $this->pendingProposal]).' CONFIRM>>>';
    }

    public static function cleanReportReply(string $reply): string
    {
        // Confirmation references come from the server, never the model's text.
        $reply = preg_replace('/<<<CONFIRM[\\s\\S]*?(?:CONFIRM>>>|$)/', '', $reply) ?? $reply;
        $reply = preg_replace_callback(
            '/\[(Download (?:Excel|PDF))\]\(([^)\s]+)\)/i',
            fn (array $match) => preg_match('~/ai/report/[a-f0-9]{32}(?:$|[?#])~i', $match[2])
                ? $match[0]
                : '',
            $reply
        ) ?? $reply;

        return trim(preg_replace('/([:;,])\s*\.(?=\s|$)/u', '$1', $reply) ?? $reply);
    }

    private function appendReportEvent(string $buffer): string
    {
        $markdown = $this->reportMarkdown();
        if ($markdown === '' && $this->pendingProposal === null && ! str_contains($buffer, '<<<CONFIRM')) {
            return $buffer;
        }

        $content = '';
        foreach ($this->parseSse($buffer) as $event) {
            $choice = $event['choices'][0] ?? [];
            $delta = $choice['delta']['content'] ?? $choice['message']['content'] ?? null;
            if (is_string($delta)) {
                $content .= $delta;
            }
        }
        $content = self::cleanReportReply($content).$markdown.$this->proposalMarker();

        return 'data: '.json_encode(['choices' => [[
            'index' => 0,
            'delta' => ['content' => $content],
        ]]], JSON_UNESCAPED_SLASHES)."\n\ndata: [DONE]\n\n";
    }

    /**
     * @param  mixed  $calls
     * @return array<int,array<string,mixed>>
     */
    protected function normalizeToolCalls($calls): array
    {
        if (! is_array($calls) || $calls === []) {
            return [];
        }

        $out = [];
        foreach ($calls as $call) {
            if (! is_array($call)) {
                continue;
            }
            $fn = $call['function'] ?? [];
            if (! is_array($fn) || empty($fn['name'])) {
                continue;
            }
            $out[] = [
                'id' => (string) ($call['id'] ?? ('call_'.bin2hex(random_bytes(6)))),
                'type' => 'function',
                'function' => [
                    'name' => (string) $fn['name'],
                    'arguments' => is_string($fn['arguments'] ?? null)
                        ? $fn['arguments']
                        : json_encode($fn['arguments'] ?? new \stdClass()),
                ],
            ];
        }

        return $out;
    }

    protected function sseHasToolCalls(string $buffer): bool
    {
        return (bool) preg_match('/"tool_calls"\s*:/', $buffer);
    }

    protected function sseHasContent(string $buffer): bool
    {
        if (! preg_match('/"content"\s*:/', $buffer)) {
            return false;
        }

        foreach ($this->parseSse($buffer) as $event) {
            $delta = $event['choices'][0]['delta'] ?? [];
            $message = $event['choices'][0]['message'] ?? [];
            $content = $delta['content'] ?? $message['content'] ?? null;
            if (is_string($content) && $content !== '') {
                return true;
            }
        }

        return false;
    }

    /**
     * @return array<int,array<string,mixed>>
     */
    protected function toolCallsFromSse(string $buffer): array
    {
        $assembled = [];

        foreach ($this->parseSse($buffer) as $event) {
            $choice = $event['choices'][0] ?? [];
            $direct = $choice['message']['tool_calls'] ?? null;
            if (is_array($direct) && $direct !== []) {
                return $this->normalizeToolCalls($direct);
            }

            $deltas = $choice['delta']['tool_calls'] ?? [];
            if (! is_array($deltas)) {
                continue;
            }

            foreach ($deltas as $delta) {
                if (! is_array($delta)) {
                    continue;
                }
                $index = (int) ($delta['index'] ?? 0);
                if (! isset($assembled[$index])) {
                    $assembled[$index] = [
                        'id' => '',
                        'type' => 'function',
                        'function' => ['name' => '', 'arguments' => ''],
                    ];
                }
                if (! empty($delta['id'])) {
                    $assembled[$index]['id'] = (string) $delta['id'];
                }
                $fn = $delta['function'] ?? [];
                if (is_array($fn)) {
                    if (! empty($fn['name'])) {
                        $assembled[$index]['function']['name'] = (string) $fn['name'];
                    }
                    if (isset($fn['arguments']) && is_string($fn['arguments'])) {
                        $assembled[$index]['function']['arguments'] .= $fn['arguments'];
                    }
                }
            }
        }

        ksort($assembled);

        return $this->normalizeToolCalls(array_values($assembled));
    }

    /**
     * @return array<int,array<string,mixed>>
     */
    protected function parseSse(string $buffer): array
    {
        $events = [];
        foreach (preg_split("/\r?\n\r?\n/", $buffer) ?: [] as $block) {
            $block = trim($block);
            if ($block === '' || ! preg_match('/^data:\s*(.+)$/s', $block, $match)) {
                continue;
            }
            $data = trim($match[1]);
            if ($data === '' || $data === '[DONE]') {
                continue;
            }
            $json = json_decode($data, true);
            if (is_array($json)) {
                $events[] = $json;
            }
        }

        return $events;
    }
}
