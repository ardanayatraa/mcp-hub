<?php

namespace App\Services\AI;

use App\Models\User;
use App\Services\Mcp\McpClient;
use App\Services\Mcp\McpHubClient;
use App\Services\Mcp\McpResourceRegistry;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Str;

class AiChatOrchestrator
{
    private const MAX_TOOL_ROUNDS = 3;

    public const USER_COUNT_UNAVAILABLE_REPLY = 'Saya belum memiliki tool yang diizinkan untuk menghitung user HiReach.';

    private array $reportLinks = [];
    private ?string $reportError = null;
    private ?string $pendingProposal = null;
    private bool $offerList = false;
    private ?string $listSuggestionLanguage = null;
    private array $availableToolNames = [];
    private string $currentQuestion = '';
    private ?array $verifiedList = null;

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
        $this->currentQuestion = self::latestUserText($history);
        if (McpHubClient::enabled()) { \App\Services\Mcp\McpPrivacyGuard::messages($history); }
        $this->assertMcpTransport();

        if (($denied = self::otherAccountReply($history, $user)) !== null) {
            return $denied;
        }

        if (($unsupported = self::unsupportedReportFormatReply($history)) !== null) {
            return $unsupported;
        }

        if (self::asksAboutCapabilities($history)) {
            return $this->capabilityReply($history, $user);
        }

        if ($this->userCountToolUnavailable($history, $user)) {
            return self::USER_COUNT_UNAVAILABLE_REPLY;
        }

        if (($denied = $this->unsupportedStatusFilterReply($history, $user)) !== null) {
            return $denied;
        }

        if (($denied = $this->unavailableResourceReply($history, $user)) !== null) {
            return $denied;
        }

        $this->reportLinks = [];
        $this->reportError = null;
        $this->pendingProposal = null;
        $this->verifiedList = null;
        $outOfScope = self::isOutOfScope($history);
        $dataQuestion = $this->asksAboutHireachData($history);
        $tools = ! $outOfScope && ($dataQuestion || $this->wantsTools($history))
            ? $this->toolsForQuestion($user)
            : [];
        $messages = $this->seed($history, $user, $outOfScope, $tools);
        $this->offerList = false;
        $this->listSuggestionLanguage = self::suggestionLanguage($history);
        $this->availableToolNames = array_column(array_column($tools, 'function'), 'name');
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
                $reply = $this->verifiedList !== null ? $this->verifiedListReply() : ($this->reportLinks === []
                    ? ($this->reportError ?? self::cleanReportReply((string) ($message['content'] ?? '')))
                    : $this->reportMarkdown());
                return $reply.$this->listSuggestion($reply).$this->proposalMarker();
            }

            $messages[] = [
                'role' => 'assistant',
                'content' => $message['content'] ?? null,
                'tool_calls' => $calls,
            ];
            $messages = array_merge($messages, $this->toolMessages($calls, $user));
            if ($this->verifiedList !== null) {
                return $this->verifiedListReply();
            }
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
        $this->currentQuestion = self::latestUserText($history);
        if (McpHubClient::enabled()) { \App\Services\Mcp\McpPrivacyGuard::messages($history); }
        $this->assertMcpTransport();

        if (($denied = self::otherAccountReply($history, $user)) !== null) {
            yield 'data: '.json_encode(['choices' => [[
                'index' => 0, 'delta' => ['content' => $denied],
            ]]], JSON_UNESCAPED_UNICODE)."\n\ndata: [DONE]\n\n";
            return;
        }

        if (($unsupported = self::unsupportedReportFormatReply($history)) !== null) {
            yield 'data: '.json_encode(['choices' => [[
                'index' => 0, 'delta' => ['content' => $unsupported],
            ]]], JSON_UNESCAPED_UNICODE)."\n\ndata: [DONE]\n\n";
            return;
        }

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

        if (($denied = $this->unsupportedStatusFilterReply($history, $user)) !== null) {
            yield 'data: '.json_encode(['choices' => [[
                'index' => 0, 'delta' => ['content' => $denied],
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
        $this->reportError = null;
        $this->pendingProposal = null;
        $this->verifiedList = null;
        $outOfScope = self::isOutOfScope($history);
        $dataQuestion = $this->asksAboutHireachData($history);
        $tools = ! $outOfScope && ($dataQuestion || $this->wantsTools($history))
            ? $this->toolsForQuestion($user)
            : [];
        $messages = $this->seed($history, $user, $outOfScope, $tools);
        $this->offerList = false;
        $this->listSuggestionLanguage = self::suggestionLanguage($history);
        $this->availableToolNames = array_column(array_column($tools, 'function'), 'name');
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
                $activity = 'Memeriksa permintaan perubahan';
                foreach ($calls as $call) {
                    $name = (string) ($call['function']['name'] ?? '');
                    if (! in_array($name, $this->availableToolNames, true)) { continue; }
                    if ($name === 'export_report') {
                        $activity = 'Menyiapkan laporan dan preview Anda';
                        break;
                    }
                    $action = McpResourceRegistry::tools()[$name]['action'] ?? null;
                    if (in_array($action, ['list', 'count', 'get'], true)) {
                        $activity = 'Membaca data HiReach';
                    }
                }
                yield 'data: '.json_encode(['activity' => $activity], JSON_UNESCAPED_UNICODE)."\n\n";
                $messages[] = [
                    'role' => 'assistant',
                    'content' => null,
                    'tool_calls' => $calls,
                ];
                $messages = array_merge($messages, $this->toolMessages($calls, $user));
                if ($this->verifiedList !== null) {
                    yield 'data: '.json_encode(['choices' => [[
                        'index' => 0, 'delta' => ['content' => $this->verifiedListReply()],
                    ]]], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)."\n\ndata: [DONE]\n\n";
                    return;
                }
                continue;
            }

            if ($calls !== [] && $round >= self::MAX_TOOL_ROUNDS && ! $this->sseHasContent($buffer)) {
                $message = ($this->reportLinks === [] ? ($this->reportError ?? 'AI could not finish this request.') : $this->reportMarkdown())
                    .$this->proposalMarker();
                yield 'data: '.json_encode(['choices' => [[
                    'index' => 0,
                    'delta' => ['content' => $message],
                ]]], JSON_UNESCAPED_SLASHES)."\n\ndata: [DONE]\n\n";
                return;
            }

            if ($this->verifiedList !== null) {
                yield 'data: '.json_encode(['choices' => [[
                    'index' => 0, 'delta' => ['content' => $this->verifiedListReply()],
                ]]], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)."\n\ndata: [DONE]\n\n";
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

        // An unfamiliar language is not evidence that a request is unrelated to HiReach.
        // Let the model interpret ambiguous wording with the current, permission-filtered tools.
        return preg_match('/\b(?:nasi\s+bungkus|makanan|resep|cuaca|weather|food|recipe|trivia|lelucon)\b/iu', $question) === 1;
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
            || preg_match('/\b(?:daftar(?:nya)?|list(?:nya)?|detail(?:nya)?|rinci(?:an(?:nya)?)?|semua data|lihat|tampilkan|sajikan|yang|kasih|kasi)\b/iu', $latest) === 1;
    }

    private static function mentionsRegisteredResource(string $question): bool
    {
        $question = mb_strtolower($question);
        foreach (AiResourceExecutor::resources() as $key => $resource) {
            $terms = $resource['keywords'] ?? [str_replace('_', ' ', (string) $key), $resource['label'] ?? ''];
            foreach ($terms as $term) {
                $term = trim(mb_strtolower((string) $term));
                if ($term !== '') {
                    $variants = [$term];
                    $singular = Str::singular($term);
                    if ($singular !== $term) {
                        $variants[] = $singular;
                    }
                    foreach ($variants as $variant) {
                        if (preg_match('/(?<!\pL)'.preg_quote($variant, '/').'(?!\pL)/iu', $question) === 1) {
                            return true;
                        }
                    }
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
    protected function seed(array $history, User $user, bool $outOfScope = false, ?array $tools = null): array
    {
        $names = $outOfScope ? []
            : array_map(fn (array $tool) => $tool['function']['name'], $tools ?? $this->availableTools($user));

        return array_merge([$this->tools->systemMessage($user, '', $names)], array_values($history));
    }

    private function availableTools(User $user): array
    {
        return McpHubClient::enabled() ? app(McpHubClient::class)->openaiTools($user) : $this->tools->openaiTools($user);
    }

    /** A tool result cannot grant access to a different operation or data model. */
    private function toolsForQuestion(User $user): array
    {
        $question = self::withoutExplicitRecordValue($this->currentQuestion);
        $resource = AiResourceExecutor::namedResource($question);
        $report = preg_match('/\b(?:pdf|xlsx|excel|export|ekspor|download|unduh)\b|\b(?:buat|bikin|create|generate|cetak|print)\s+(?:file\s+)?(?:laporan|report)\b/iu', $question) === 1;
        $write = $report ? null : (preg_match('/\b(?:hapus|delete|remove|buang)\b/iu', $question) ? 'delete'
            : (preg_match('/\b(?:ubah|edit|update|perbarui|ganti|change|modify)\b/iu', $question) ? 'update'
                : (preg_match('/\b(?:buat|bikin|tambah|tambahkan|create|add|new)\b/iu', $question) ? 'create' : null)));

        return array_values(array_filter($this->availableTools($user), static function (array $tool) use ($resource, $report, $write): bool {
            $name = $tool['function']['name'] ?? '';
            if ($name === 'export_report') { return $report; }
            $spec = McpResourceRegistry::tools()[$name] ?? null;
            if (! $spec) { return false; }
            if ($resource !== null && $spec['resource'] !== $resource) { return false; }
            if (isset($spec['phase'])) { return $resource !== null && $spec['resource'] === $resource && $spec['action'] === $write; }
            return true;
        }));
    }

    /** Permission inventory is metadata, never an AI guess or a data query. */
    public static function asksAboutCapabilities(array $history): bool
    {
        $question = self::latestUserText($history);
        if (preg_match('/\b(?:apa|mana|kemana|what|which)\b/iu', $question)
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

    /** Explicit requests for another account must explain the ownership boundary. */
    private static function otherAccountReply(array $history, User $user): ?string
    {
        $question = mb_strtolower(self::withoutExplicitRecordValue(self::latestUserText($history)));
        if (preg_match('/\b(?:tampilkan|lihat|ambil|daftar|list|show|get|fetch|berapa|jumlah|count)\b/iu', $question) !== 1) {
            return null;
        }
        $other = preg_match('/\b(?:pengguna|user|akun|account)\s+(?:lain|other|another)\b|\b(?:other|another)\s+(?:user|account)\b/iu', $question) === 1;
        if (preg_match('/\b(?:pengguna|user|akun)\s+#?([0-9]+)\b/iu', $question, $match) === 1
            && (string) (int) $match[1] !== (string) $user->getKey()) {
            $other = true;
        }
        if (! $other) { return null; }

        return self::suggestionLanguage($history) === 'en'
            ? 'I can only read data belonging to your account, so I cannot show another user’s data.'
            : 'Saya hanya bisa membaca data milik akun Anda, jadi tidak bisa menampilkan data pengguna lain.';
    }

    /** Never ask the model to invent a filter that the current Hub tool does not accept. */
    private function unsupportedStatusFilterReply(array $history, User $user): ?string
    {
        $question = self::latestUserText($history);
        if (preg_match('/\b(?:berstatus|status)\s*[:=]?\s*(FAILED|SUCCESS)\b/iu', $question, $match) !== 1) {
            return null;
        }
        $status = strtoupper($match[1]);
        $action = preg_match('/\b(?:berapa|jumlah|total|hitung|count|how many)\b/iu', $question) ? 'count' : 'list';
        $available = array_column($this->availableTools($user), 'function');
        $definitions = array_column($available, null, 'name');
        foreach (McpResourceRegistry::resources() as $key => $resource) {
            if (! isset($resource['fields']['status'])) { continue; }
            $terms = [$key, str_replace('_', ' ', $key), $resource['label'], ...($resource['keywords'] ?? [])];
            $mentioned = false;
            foreach ($terms as $term) {
                if ($term !== '' && preg_match('/(?<!\pL)'.preg_quote((string) $term, '/').'(?!\pL)/iu', $question)) {
                    $mentioned = true;
                    break;
                }
            }
            if (! $mentioned) { continue; }
            foreach (McpResourceRegistry::tools() as $name => $tool) {
                if ($tool['resource'] !== $key || $tool['action'] !== $action || ! isset($definitions[$name])) { continue; }
                if (array_key_exists('status', (array) ($definitions[$name]['parameters']['properties'] ?? []))) {
                    return null;
                }
                $label = Str::singular(mb_strtolower((string) $resource['label']));
                $english = self::suggestionLanguage($history) === 'en';
                if ($action === 'count') {
                    return $english
                        ? "I can read your {$label} data, but the {$status} status filter is not available, so I cannot give an accurate count."
                        : "Saya bisa membaca data {$label} milik akun Anda, tetapi filter status {$status} belum tersedia. Jadi, saya belum bisa memberi jumlah yang akurat.";
                }
                return $english
                    ? "I can read your {$label} data, but the {$status} status filter is not available, so I cannot show an accurate filtered list."
                    : "Saya bisa membaca data {$label} milik akun Anda, tetapi filter status {$status} belum tersedia. Jadi, saya belum bisa menampilkan daftar berdasarkan status itu.";
            }
        }

        return null;
    }

    /** A named unavailable model must never be replaced with another model's tool. */
    private function unavailableResourceReply(array $history, User $user): ?string
    {
        $question = self::withoutExplicitRecordValue(self::latestUserText($history));
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

        $english = self::suggestionLanguage($history) === 'en';
        return ($english ? 'I do not have access to that data.'
            : 'Saya tidak punya akses ke data yang Anda minta.')."\n\n"
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
        $verbs = $english ? ['read' => 'read', 'create' => 'create', 'update' => 'update', 'delete' => 'delete']
            : ['read' => 'membaca', 'create' => 'menambah', 'update' => 'mengubah', 'delete' => 'menghapus'];
        $byOperation = [];
        foreach ($resources as $resource) {
            $name = str_replace(["\r", "\n"], ' ', $resource['label']);
            if (! $english) {
                $name = \Illuminate\Support\Str::singular(mb_strtolower($name, 'UTF-8'));
            }
            $name = str_replace(['\\', '*', '_', '[', ']'], ['\\\\', '\\*', '\\_', '\\[', '\\]'], $name);
            foreach (array_keys(array_intersect_key($verbs, $resource['operations'])) as $operation) {
                $byOperation[$operation][] = $name;
            }
        }
        $sentences = [];
        foreach ($verbs as $operation => $verb) {
            $names = $byOperation[$operation] ?? [];
            if ($names === []) { continue; }
            $last = array_pop($names);
            $joined = $names === [] ? $last : implode(', ', $names)
                .(count($names) === 1 ? ($english ? ' and ' : ' dan ') : ($english ? ', and ' : ', dan ')).$last;
            $prefix = $sentences === [] ? ($english ? 'I can ' : 'Saya bisa ')
                : ($english ? 'I can also ' : 'Saya juga bisa ');
            $sentences[] = $prefix.$verb.($english ? ' data from ' : ' data dari ').$joined
                .($english ? ' in your account.' : ' milik akun Anda.');
        }

        return implode(' ', $sentences);
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
                if (! in_array($name, $this->availableToolNames, true)) {
                    throw new \RuntimeException('Tool was not authorized for this request.');
                }
                $spec = \App\Services\Mcp\McpResourceRegistry::tools()[$name] ?? [];
                // Some providers add a non-schema "reason" alongside function arguments.
                // Drop only that annotation; other unknown inputs still fail Hub validation.
                if (! array_key_exists('reason', (array) ($spec['input_schema']['properties'] ?? []))) {
                    unset($arguments['reason']);
                }
                if (($spec['action'] ?? '') === 'get' && isset($spec['resource'])) {
                    $lookup = McpResourceRegistry::resources()[$spec['resource']]['lookup'] ?? null;
                    if (is_string($lookup) && ! isset($arguments[$lookup])) {
                        $value = self::explicitLookupValue($this->currentQuestion, $lookup);
                        if ($value !== null && strlen($value) <= ($spec['input_schema']['properties'][$lookup]['maxLength'] ?? 200)) {
                            $arguments[$lookup] = $value;
                        }
                    }
                }
                if ($name === 'export_report') {
                    if (preg_match('/\bpdf\b/i', $this->currentQuestion)) {
                        $arguments['format'] = 'pdf';
                    } elseif (preg_match('/\b(?:excel|xlsx)\b/i', $this->currentQuestion)) {
                        $arguments['format'] = 'xlsx';
                    }
                    if (($namedResource = AiResourceExecutor::namedResource($this->currentQuestion)) !== null) {
                        $arguments['resource'] = $namedResource;
                    }
                    unset($arguments['status']);
                    if (preg_match('/\b(?:failed|gagal)\b/i', $this->currentQuestion)) {
                        $arguments['status'] = 'FAILED';
                    } elseif (preg_match('/\b(?:success|sukses|berhasil)\b/i', $this->currentQuestion)) {
                        $arguments['status'] = 'SUCCESS';
                    }
                }
                if (($schemaError = self::toolArgumentError($spec, $arguments, $name)) !== null) {
                    $out[] = ['role' => 'tool',
                        'tool_call_id' => (string) ($call['id'] ?? ('call_'.bin2hex(random_bytes(6)))),
                        'content' => json_encode(['ok' => false, 'error' => $schemaError], JSON_UNESCAPED_UNICODE)];
                    continue;
                }
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
                if ($name === 'export_report' && is_string($payload['preview_url'] ?? null)) {
                    $this->reportLinks[] = [
                        'url' => $payload['url'],
                        'preview_url' => $payload['preview_url'] ?? null,
                        'format' => $payload['format'] ?? 'xlsx',
                        'label' => $payload['label'] ?? 'data',
                        'count' => $payload['count'] ?? 0,
                        'print_only' => $payload['print_only'] ?? false,
                    ];
                    unset($payload['url']);
                    unset($payload['preview_url']);
                    $payload['preview_ready'] = true;
                    $payload['download_ready'] = empty($payload['print_only']);
                }
                if (($spec['action'] ?? '') === 'count'
                    && in_array('list_'.$spec['resource'], $this->availableToolNames, true)
                    && is_int($payload['data']['count'] ?? null) && $payload['data']['count'] > 0) {
                    $this->offerList = true;
                }
                if (($spec['action'] ?? '') === 'list' && self::isSimpleListRequest($this->currentQuestion)
                    && is_array($payload['data'] ?? null)) {
                    $rows = $payload['data'];
                    $cursor = $payload['meta']['next_cursor'] ?? null;
                    $seen = [];
                    while (is_string($cursor) && $cursor !== '' && count($rows) < 100 && ! isset($seen[$cursor])) {
                        $seen[$cursor] = true;
                        $nextArgs = $arguments;
                        $nextArgs['limit'] = min(50, 100 - count($rows));
                        $nextArgs['cursor'] = $cursor;
                        try {
                            $next = ($this->ai->usesMcpProvider() || McpHubClient::enabled())
                                ? $this->mcp->query('hireach', $name, $nextArgs, $user)
                                : $this->tools->callTool($name, $nextArgs, $user);
                            if (! is_array($next['data'] ?? null) || $next['data'] === []) { break; }
                            $rows = array_merge($rows, $next['data']);
                            $cursor = $next['meta']['next_cursor'] ?? null;
                        } catch (\Throwable $error) {
                            break;
                        }
                    }
                    $this->verifiedList = ['resource' => $spec['resource'], 'rows' => array_slice($rows, 0, 100),
                        'more' => is_string($cursor) && $cursor !== ''];
                }
                $content = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) ?: '{}';
            } catch (\Throwable $e) {
                if ($name === 'export_report') {
                    $this->reportError = preg_match('/^(?:Laporan (?:melebihi 1\.000 baris|terlalu besar)|Filter status )/u', $e->getMessage())
                        ? $e->getMessage()
                        : 'Laporan belum dapat dibuat. Periksa izin data atau coba lagi.';
                }
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

    private static function toolArgumentError(array $spec, array $arguments, string $name): ?string
    {
        if ($spec === []) { return null; }
        $schema = $spec['input_schema'] ?? [];
        $properties = (array) ($schema['properties'] ?? []);
        $required = (array) ($schema['required'] ?? []);
        $missing = array_values(array_diff($required, array_keys($arguments)));
        if ($missing !== []) {
            return 'Missing required argument: '.implode(', ', $missing).'. Retry '.$name
                .' with that value copied exactly from the user request or a prior tool result.';
        }
        $unknown = array_values(array_diff(array_keys($arguments), array_keys($properties)));
        if ($unknown !== []) {
            return 'Unsupported argument: '.implode(', ', $unknown).'. Retry '.$name
                .' using only: '.implode(', ', array_keys($properties)).'.';
        }
        if (isset($arguments['limit']) && (! is_int($arguments['limit']) || $arguments['limit'] < 1 || $arguments['limit'] > 50)) {
            return 'The limit must be an integer from 1 to 50. Retry with a valid limit.';
        }
        foreach ($arguments as $key => $value) {
            if (isset($properties[$key]['enum']) && ! in_array($value, $properties[$key]['enum'], true)) {
                return 'Invalid '.$key.' value. Retry using one of: '.implode(', ', $properties[$key]['enum']).'.';
            }
        }
        return null;
    }

    private static function explicitLookupValue(string $question, string $field): ?string
    {
        $label = $field === 'title' ? '(?:berjudul|judul|titled|title)' : '(?:bernama|nama|named|name)';
        if (preg_match('/\b'.$label.'\s*[:=]?\s*(?:"([^"]+)"|“([^”]+)”|\x27([^\x27]+)\x27|(.+?)(?=\s+milik\s+(?:saya|aku)|\s+(?:saya|aku|my|mine)\b|[?.!]|$))/iu',
            $question, $match) !== 1) { return null; }
        $value = trim((string) (($match[1] ?? '') ?: ($match[2] ?? '') ?: ($match[3] ?? '') ?: ($match[4] ?? '')));
        return $value !== '' ? $value : null;
    }

    private static function withoutExplicitRecordValue(string $question): string
    {
        // Names and titles are record values, even when they contain words such as "User".
        foreach (['title' => '(?:berjudul|titled)', 'name' => '(?:bernama|named)'] as $field => $label) {
            if (preg_match('/\b'.$label.'\b/iu', $question)
                && ($value = self::explicitLookupValue($question, $field)) !== null) {
                $question = str_replace($value, ' ', $question);
            }
        }
        return $question;
    }

    private function assertMcpTransport(): void
    {
        if (config('ai.mcp.ai_only', true) && ! $this->ai->usesMcpProvider()) {
            throw new \RuntimeException('AI Chat requires an active MCP integration.');
        }
    }

    private function reportMarkdown(): string
    {
        $lines = [];
        foreach ($this->reportLinks as $report) {
            $pdf = $report['format'] === 'pdf';
            $kind = $pdf ? 'PDF' : 'Excel';
            $count = (int) ($report['count'] ?? 0);
            $label = (string) ($report['label'] ?? 'data');
            $line = 'Laporan '.$kind.' '.$label.' berisi '.number_format($count, 0, ',', '.')
                .' data milik akun Anda sudah siap. [Lihat preview]('.$report['preview_url'].')';
            $lines[] = ! empty($report['print_only'])
                ? $line.'. Untuk huruf di luar Latin, pilih "Cetak / Simpan PDF" pada preview agar teks tetap utuh.'
                : $line.' · [Download '.$kind.']('.$report['url'].')';
        }

        return implode("\n\n", $lines);
    }

    private function proposalMarker(): string
    {
        return $this->pendingProposal === null ? '' : "\n<<<CONFIRM ".json_encode(['proposal_ref' => $this->pendingProposal]).' CONFIRM>>>';
    }

    private function listSuggestion(string $reply): string
    {
        if (! $this->offerList || $reply === '' || $this->listSuggestionLanguage === null
            || preg_match('/\b(?:mau|ingin|would you like)\b.{0,70}\b(?:lihat|tampilkan|daftar|list|show|see)\b/iu', $reply)) {
            return '';
        }

        return $this->listSuggestionLanguage === 'en'
            ? "\n\nWould you like me to show the list?"
            : "\n\nMau saya tampilkan daftarnya?";
    }

    private static function isSimpleListRequest(string $question): bool
    {
        return preg_match('/\b(?:daftar(?:nya)?|list(?:nya)?|tampilkan|lihat|show)\b/iu', $question) === 1
            && preg_match('/\b(?:laporan|report|pdf|excel|xlsx|detail|rinci|berapa|jumlah|count|hapus|ubah|buat)\b/iu', $question) !== 1;
    }

    private function verifiedListReply(): string
    {
        $rows = $this->verifiedList['rows'];
        $label = str_replace('_', ' ', rtrim((string) $this->verifiedList['resource'], 's'));
        if ($rows === []) { return 'Belum ada '.$label.' yang dapat ditampilkan untuk akun Anda.'; }
        $first = reset($rows);
        $fields = [];
        foreach (['name', 'title', 'code', 'type', 'status', 'is_enabled', 'created_at'] as $field) {
            if (is_array($first) && array_key_exists($field, $first)) { $fields[] = $field; }
        }
        $fields = array_slice($fields, 0, 3);
        if ($fields === [] && is_array($first)) {
            $fields = array_slice(array_keys(array_filter($first,
                static fn ($value, $key) => is_scalar($value) && ! in_array($key, ['id', 'ref', 'user_id'], true),
                ARRAY_FILTER_USE_BOTH)), 0, 3);
        }
        $headings = ['name' => 'Nama', 'title' => 'Judul', 'code' => 'Kode', 'type' => 'Tipe',
            'status' => 'Status', 'is_enabled' => 'Aktif', 'created_at' => 'Dibuat'];
        $lines = ['Berikut '.count($rows).' '.$label.' milik akun Anda:', '',
            '| No. | '.implode(' | ', array_map(static fn ($field) => $headings[$field] ?? ucfirst($field), $fields)).' |',
            '| ---: | '.implode(' | ', array_fill(0, count($fields), '---')).' |'];
        foreach ($rows as $index => $row) {
            if (! is_array($row)) { continue; }
            $cells = array_map(static function ($field) use ($row): string {
                $value = $row[$field] ?? null;
                if ($value === null) { return '—'; }
                if (is_bool($value)) { return $value ? 'Ya' : 'Tidak'; }
                if (! is_scalar($value)) { return '—'; }
                $safe = htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
                return str_replace(["\\", '|', "`", '*', '_', '[', ']', "\r", "\n"],
                    ["\\\\", '\\|', '\\`', '\\*', '\\_', '\\[', '\\]', ' ', ' '], $safe);
            }, $fields);
            $lines[] = '| '.($index + 1).' | '.implode(' | ', $cells).' |';
        }
        if ($this->verifiedList['more']) {
            $lines[] = '';
            $lines[] = 'Masih ada data lain. Untuk daftar lengkap, minta laporan PDF atau Excel.';
        }
        return implode("\n", $lines);
    }

    private static function suggestionLanguage(array $history): ?string
    {
        $question = self::latestUserText($history);
        if (preg_match('/\b(?:berapa|jumlah|milik|saya|aku|tampilkan|lihat|daftar|kasih|kasi|lain|pengguna|berstatus)\b/iu', $question)) {
            return 'id';
        }
        if (preg_match('/\b(?:how many|count|my|account|show|list|please)\b/i', $question)) {
            return 'en';
        }

        return null;
    }

    private static function unsupportedReportFormatReply(array $history): ?string
    {
        $question = self::latestUserText($history);
        return preg_match('/\bcsv\b/i', $question)
            && preg_match('/\b(?:buat|unduh|download|export|ekspor|laporan|report)\b/iu', $question)
            && ! preg_match('/\b(?:pdf|excel|xlsx)\b/i', $question)
                ? 'Format CSV belum tersedia. Saya bisa membuat laporan Excel atau PDF.'
                : null;
    }

    public static function cleanReportReply(string $reply): string
    {
        // Confirmation references come from the server, never the model's text.
        $reply = preg_replace('/<<<CONFIRM[\\s\\S]*?(?:CONFIRM>>>|$)/', '', $reply) ?? $reply;
        $reply = preg_replace_callback(
            '/\[(Download (?:Excel|PDF)|Lihat preview)\]\(([^)\s]+)\)/i',
            static function (array $match): string {
                $url = parse_url($match[2]);
                $base = parse_url(url('/'));
                if (! is_array($url) || ! is_array($base)
                    || ($url['scheme'] ?? null) !== ($base['scheme'] ?? null)
                    || ($url['host'] ?? null) !== ($base['host'] ?? null)
                    || ($url['port'] ?? null) !== ($base['port'] ?? null)
                    || isset($url['query']) || isset($url['fragment']) || isset($url['user'])
                    || ! preg_match('~^/ai/report/([a-f0-9]{32})(/preview)?$~i', $url['path'] ?? '', $parts)
                    || (strcasecmp($match[1], 'Lihat preview') === 0) !== isset($parts[2])) {
                    return '';
                }
                $meta = Cache::get('hireach.ai.report.'.strtolower($parts[1]));
                return is_array($meta) && (int) ($meta['user_id'] ?? 0) === (int) auth()->id()
                    ? $match[0] : '';
            },
            $reply
        ) ?? $reply;

        return trim(preg_replace('/([:;,])\s*\.(?=\s|$)/u', '$1', $reply) ?? $reply);
    }

    private function appendReportEvent(string $buffer): string
    {
        $markdown = $this->reportMarkdown();
        if ($markdown === '' && $this->reportError === null && $this->pendingProposal === null && ! $this->offerList && ! str_contains($buffer, '<<<CONFIRM')) {
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
        $content = $this->reportLinks === []
            ? ($this->reportError ?? self::cleanReportReply($content))
            : $markdown;
        $content .= $this->listSuggestion($content).$this->proposalMarker();

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
