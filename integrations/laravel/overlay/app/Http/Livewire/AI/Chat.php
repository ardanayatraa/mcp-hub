<?php

namespace App\Http\Livewire\AI;

use App\Services\AI\AiProviderClient;
use App\Services\AI\AiChatOrchestrator;
use App\Services\AI\AiResourceExecutor;
use Illuminate\Support\Str;
use Livewire\Component;
use Throwable;

class Chat extends Component
{
    public array $messages = [];

    public string $input = '';

    public string $model = 'kr/claude-haiku-4.5';

    public bool $isThinking = false;

    public string $error = '';

    public array $modelOptions = [];

    public string $modelsError = '';

    public string $sessionTitle = 'New chat';

    public string $sessionId = '';

    public string $activeSession = '';

    public array $pendingAction = [];

    public string $pendingDeleteId = '';

    public string $pendingDeleteTitle = '';

    public array $sessions = [];

    public array $usage = [];

    protected $listeners = [
        'hireachAiComplete' => 'completeSend',
    ];

    public function updatedModel($value): void
    {
        $this->selectModel((string) $value);
    }

    public function selectModel(string $id): void
    {
        try {
            $this->model = app(AiProviderClient::class)->resolveModel($id);
        } catch (Throwable $e) {
            try {
                $this->model = app(AiProviderClient::class)->defaultModel();
            } catch (Throwable $ignored) {
                $this->model = '';
            }
        }

        $this->storeSelectedModel($this->model);
    }

    public function mount($uuid = ''): void
    {
        session()->forget($this->pendingKey());
        $this->loadModels();
        $this->loadSessions();
        $this->loadUsage();

        $uuid = is_string($uuid) ? trim($uuid) : '';
        if ($uuid !== '') {
            $this->openSession($uuid);

            return;
        }

        $this->sessionId = '';
        $this->activeSession = '';
        $this->messages = [];
    }

    public function send(): void
    {
        $text = trim($this->input);

        if ($text === '' || $this->isThinking) {
            return;
        }

        if (mb_strlen($text) > 4000) {
            $this->error = 'Pesan terlalu panjang. Maksimal 4.000 karakter.';
            return;
        }

        if (session()->has($this->pendingKey()) && $this->isAffirmative($text)) {
            $this->input = '';
            $this->confirmPending();

            return;
        }

        session()->forget($this->pendingKey());
        $this->pendingAction = [];
        $this->error = '';
        $this->ensureSession();
        $this->messages[] = ['role' => 'user', 'content' => $text];
        $this->input = '';
        $this->isThinking = true;
        $this->rememberSessionTitle($text);
        $this->dispatchBrowserEvent('hireach-ai-think');
        $this->dispatchBrowserEvent('hireach-ai-stream', [
            'model' => $this->model,
            'session_id' => $this->sessionId,
            'messages' => $this->requestMessages(),
        ]);
    }

    public function completeSend(): void
    {
        if (! $this->isThinking) {
            return;
        }

        $text = $this->lastUserText();

        try {
            $this->model = app(AiProviderClient::class)->resolveModel($this->model);
            $raw = app(AiChatOrchestrator::class)->complete(
                $this->model,
                $this->requestMessages(),
                auth()->user(),
                $this->metadata()
            );
            $this->messages[] = [
                'role' => 'assistant',
                'content' => $this->finalizeAssistant($raw, $text),
            ];
            $this->saveConversation();
        } catch (Throwable $e) {
            $this->error = 'Layanan AI sedang tidak tersedia. Coba lagi beberapa saat.';

            $this->messages[] = [
                'role' => 'assistant',
                'content' => 'Maaf, saya belum bisa menjawab karena layanan AI sedang tidak tersedia. Coba lagi beberapa saat.',
            ];
        } finally {
            $this->isThinking = false;
            $this->loadSessions();
            $this->loadUsage();
            $this->dispatchBrowserEvent('hireach-ai-scroll');
            $this->dispatchBrowserEvent('hireach-ai-focus');
        }
    }

    public function finishStream(string $raw): void
    {
        if (! $this->isThinking) {
            return;
        }

        $this->messages[] = [
            'role' => 'assistant',
            'content' => $this->finalizeAssistant($raw, $this->lastUserText()),
        ];
        $this->saveConversation();
        $this->isThinking = false;
        $this->error = '';
        $this->loadSessions();
        $this->loadUsage();
        $this->dispatchBrowserEvent('hireach-ai-scroll');
        $this->dispatchBrowserEvent('hireach-ai-focus');
    }

    public function failStream(?string $message = null): void
    {
        if (! $this->isThinking) {
            return;
        }

        $this->error = 'Layanan AI sedang tidak tersedia. Coba lagi beberapa saat.';
        $this->messages[] = [
            'role' => 'assistant',
            'content' => 'Maaf, saya belum bisa menjawab karena layanan AI sedang tidak tersedia. Coba lagi beberapa saat.',
        ];
        $this->isThinking = false;
        $this->loadSessions();
        $this->loadUsage();
        $this->dispatchBrowserEvent('hireach-ai-scroll');
        $this->dispatchBrowserEvent('hireach-ai-focus');
    }

    public function loadModels(): void
    {
        try {
            $client = app(AiProviderClient::class);
            $client->forgetCatalog();
            $this->modelOptions = $client->labeledModels();
            $this->modelsError = '';

            $saved = $this->storedSelectedModel();
            if ($saved !== '' && isset($this->modelOptions[$saved])) {
                $this->model = $saved;
            } elseif ($this->model === '' || ! isset($this->modelOptions[$this->model])) {
                $this->model = $client->defaultModel();
            }
        } catch (Throwable $e) {
            $this->modelOptions = [];
            $this->model = '';
            $this->modelsError = 'Unable to load AI models. Please try again later.';
        }
    }

    public function refreshModels(): void
    {
        try {
            $client = app(AiProviderClient::class);
            $client->forgetCatalog();
            $options = $client->labeledModels();
            $this->modelOptions = $options;
            $this->modelsError = $options === [] ? 'No AI models are currently available.' : '';

            if (! isset($options[$this->model])) {
                $this->model = $options === [] ? '' : $client->defaultModel();
                $this->storeSelectedModel($this->model);
            }
        } catch (Throwable $e) {
            $this->modelsError = 'Unable to refresh AI models. Please try again later.';
        }
    }

    public function resetChat(): void
    {
        session()->forget($this->pendingKey());
        $this->messages = [];
        $this->error = '';
        $this->pendingAction = [];
        $this->pendingDeleteId = '';
        $this->pendingDeleteTitle = '';
        $this->sessionTitle = 'New chat';
        $this->sessionId = '';
        $this->activeSession = '';
        $this->loadSessions();
        $this->loadUsage();
        $this->pushChatUrl('');
    }

    public function openSession(string $sessionId): void
    {
        session()->forget($this->pendingKey());
        if (! $this->hydrateSession($sessionId)) {
            return;
        }

        $this->pushChatUrl($this->sessionId);
    }

    public function askDeleteSession(string $sessionId): void
    {
        $sessionId = trim($sessionId);
        if ($sessionId === '') {
            return;
        }

        $this->pendingDeleteId = $sessionId;
        $this->pendingDeleteTitle = 'this chat';
        foreach ($this->sessions as $row) {
            if (! is_array($row)) {
                continue;
            }
            if ((string) ($row['session_id'] ?? '') === $sessionId) {
                $title = trim((string) ($row['title'] ?? ''));
                if ($title !== '') {
                    $this->pendingDeleteTitle = $title;
                }
                break;
            }
        }
    }

    public function cancelDelete(): void
    {
        $this->pendingDeleteId = '';
        $this->pendingDeleteTitle = '';
    }

    public function confirmDelete(): void
    {
        $sessionId = $this->pendingDeleteId;
        $this->cancelDelete();
        $this->deleteSession($sessionId);
    }

    public function deleteSession(string $sessionId): void
    {
        $sessionId = trim($sessionId);
        if ($sessionId === '') {
            return;
        }

        try {
            app(AiProviderClient::class)->deleteConversation($sessionId);
        } catch (Throwable $e) {
            $this->error = $e->getMessage();

            return;
        }

        $this->error = '';
        if ($this->sessionId === $sessionId || $this->activeSession === $sessionId) {
            $this->resetChat();

            return;
        }

        $this->loadSessions();
    }

    public function restoreSession(string $sessionId): void
    {
        $this->hydrateSession($sessionId);
    }

    public function loadSessions(): void
    {
        try {
            $this->sessions = app(AiProviderClient::class)->listConversations();
        } catch (Throwable $e) {
            $this->sessions = [];
        }
    }

    public function loadUsage(): void
    {
        try {
            $this->usage = app(AiProviderClient::class)->usage();
        } catch (Throwable $e) {
            $this->usage = [];
        }
    }

    public function confirmPending(): void
    {
        $pending = session()->get($this->pendingKey(), []);
        if (($pending['proposal_ref'] ?? '') !== ($this->pendingAction['proposal_ref'] ?? '')) {
            $this->messages[] = ['role' => 'assistant', 'content' => 'The proposal changed. Review it again.'];
            return;
        }
        session()->forget($this->pendingKey());
        $this->pendingAction = [];

        if (! is_array($pending) || empty($pending['proposal_ref'])) {
            return;
        }

        try {
            $result = app(AiResourceExecutor::class)->commitProposal((string) $pending['proposal_ref'], auth()->user());

            $this->messages[] = [
                'role' => 'assistant',
                'content' => app(AiResourceExecutor::class)->formatResult($result),
            ];
        } catch (Throwable $e) {
            $this->messages[] = [
                'role' => 'assistant',
                'content' => 'Confirmation failed. Nothing was saved.',
            ];
        }

        $this->dispatchBrowserEvent('hireach-ai-focus');
    }

    public function rejectPending(): void
    {
        $pending = session()->get($this->pendingKey(), []);
        if (! empty($pending['proposal_ref'])) {
            try { app(AiResourceExecutor::class)->cancelProposal($pending['proposal_ref'], auth()->user()); }
            catch (Throwable $error) { /* Already expired or consumed. */ }
        }
        session()->forget($this->pendingKey());
        $this->pendingAction = [];
        $this->messages[] = [
            'role' => 'assistant',
            'content' => 'Cancelled. Nothing was changed.',
        ];
        $this->dispatchBrowserEvent('hireach-ai-focus');
    }

    public static function getName()
    {
        return 'ai.chat';
    }

    private function pendingKey(): string
    {
        return 'hireach.ai.pending.'.auth()->id().'.'.$this->sessionId;
    }

    private function saveConversation(): void
    {
        app(AiProviderClient::class)->saveLocalConversation($this->sessionId, $this->sessionTitle, $this->messages);
    }

    /** Keep the transport within AiController's 40-message and 4,000-character limits. */
    private function requestMessages(): array
    {
        $history = [];
        foreach (array_slice($this->messages, -20) as $message) {
            if (! is_array($message) || ! in_array($message['role'] ?? null, ['user', 'assistant'], true)
                || ! is_string($message['content'] ?? null) || trim($message['content']) === '') {
                continue;
            }
            $content = $message['content'];
            if (mb_strlen($content) > 4000) {
                $content = mb_substr($content, 0, 3999).'…';
            }
            $history[] = ['role' => $message['role'], 'content' => $content];
        }

        return $history;
    }

    public function getUsageCardProperty(): array
    {
        $user = is_array($this->usage['user'] ?? null) ? $this->usage['user'] : [];
        $quota = is_array($this->usage['quota'] ?? null) ? $this->usage['quota'] : [];
        if ($user === [] && $quota === []) {
            return ['visible' => false];
        }

        $requests = (int) ($user['requests'] ?? 0);
        $tokens = (int) ($user['total_tokens'] ?? 0);
        $kind = (string) ($quota['kind'] ?? 'none');
        $currency = (string) ($quota['currency'] ?? 'USD');
        $detail = $this->formatCount($requests).' messages · '.$this->formatCount($tokens).' tokens';

        $used = $quota['user_used'] ?? $quota['used'] ?? $user['cost'] ?? null;
        $limit = $quota['user_limit'] ?? $quota['limit'] ?? null;
        if ($kind === 'application') {
            $used = $quota['used'] ?? $used;
            $limit = $quota['limit'] ?? $limit;
        }

        $percent = isset($quota['percent']) ? (float) $quota['percent'] : null;
        if ($percent === null && is_numeric($used) && is_numeric($limit) && (float) $limit > 0) {
            $percent = min(100, ((float) $used / (float) $limit) * 100);
        }
        $percentLabel = $percent === null ? null : ((int) round(max(0, min(100, $percent)))).'%';

        $headline = $this->moneyPair(
            $used,
            $limit,
            $currency,
            $quota['user_used_formatted'] ?? $quota['used_formatted'] ?? $user['cost_formatted'] ?? null,
            $quota['user_limit_formatted'] ?? $quota['limit_formatted'] ?? null
        );

        if ($kind === 'user' || $kind === 'application') {
            return [
                'visible' => true,
                'title' => $kind === 'user' ? 'Monthly quota' : 'Usage this month',
                'headline' => $headline,
                'detail' => $detail,
                'percent' => $percent,
                'percent_label' => $percentLabel,
                'note' => null,
            ];
        }

        return [
            'visible' => true,
            'title' => 'Usage this month',
            'headline' => $this->formatMoney($user['cost'] ?? null, $currency, $user['cost_formatted'] ?? null) ?: $detail,
            'detail' => ($user['cost'] ?? null) !== null ? $detail : '',
            'percent' => null,
            'percent_label' => null,
            'note' => null,
        ];
    }

    public function formatMessage(string $content): string
    {
        $content = $this->visibleReply($content);
        $content = preg_replace('/\s+(?=(?:Templates|Blast Messages|Exports):)/i', "\n", $content) ?? $content;
        $content = preg_replace('/(^|\n)(Templates|Blast Messages|Exports):/i', '$1- **$2:**', $content) ?? $content;
        $content = preg_replace('/^[\x{2022}\x{2023}\x{25E6}\x{2043}\x{2219}]\s+/mu', '- ', $content) ?? $content;
        $content = $this->markdownDownloadLinks($content);

        $html = Str::markdown($content, [
            'html_input' => 'strip',
            'allow_unsafe_links' => false,
        ]);

        $html = preg_replace('/<table\b[^>]*>.*?<\/table>/is', '<div class="ai-table">$0</div>', $html) ?? $html;
        $html = $this->keepIssuedReportLinks($html);
        $html = preg_replace('/<a href="/', '<a target="_blank" rel="noopener" href="', $html) ?? $html;

        return $html;
    }

    private function markdownDownloadLinks(string $content): string
    {
        return preg_replace_callback(
            '#(?<!\]\()(https?://[^\s)<>]+/ai/report/[a-f0-9]{32})(?:\s*\((xlsx|xls|excel|pdf)\))?#i',
            function ($match) {
                $kind = strtolower($match[2] ?? '');
                if ($kind === 'pdf') {
                    $label = 'Download PDF';
                } elseif (in_array($kind, ['xlsx', 'xls', 'excel'], true)) {
                    $label = 'Download Excel';
                } else {
                    $label = 'Download report';
                }

                return '['.$label.']('.$match[1].')';
            },
            $content
        ) ?? $content;
    }

    private function keepIssuedReportLinks(string $html): string
    {
        return preg_replace_callback(
            '#<a\b[^>]*\bhref="([^"]*)"[^>]*>(.*?)</a>#is',
            static function (array $match): string {
                $url = parse_url(html_entity_decode($match[1], ENT_QUOTES | ENT_HTML5, 'UTF-8'));
                $base = parse_url(url('/'));
                if (! is_array($url) || ! is_array($base)
                    || ($url['scheme'] ?? null) !== ($base['scheme'] ?? null)
                    || ($url['host'] ?? null) !== ($base['host'] ?? null)
                    || ($url['port'] ?? null) !== ($base['port'] ?? null)
                    || isset($url['query']) || isset($url['fragment']) || isset($url['user'])
                    || ! preg_match('~^/ai/report/([a-f0-9]{32})(?:/preview)?$~i', $url['path'] ?? '', $parts)) {
                    return $match[2];
                }
                $meta = \Illuminate\Support\Facades\Cache::get('hireach.ai.report.'.strtolower($parts[1]));
                return is_array($meta) && (int) ($meta['user_id'] ?? 0) === (int) auth()->id()
                    ? $match[0] : $match[2];
            },
            $html
        ) ?? $html;
    }

    public function formatUserMessage(string $content): string
    {
        $content = trim($content);
        if ($content === '') {
            return '';
        }

        $parts = preg_split("/\n{2,}/", $content) ?: [$content];
        $html = '';
        foreach ($parts as $part) {
            $html .= '<p>'.nl2br(e($part), false).'</p>';
        }

        return $html;
    }

    public function render()
    {
        return view('livewire.ai.chat');
    }

    private function storedSelectedModel(): string
    {
        $saved = session($this->modelMemoryKey());

        return is_string($saved) ? $saved : '';
    }

    private function storeSelectedModel(string $id): void
    {
        if ($id === '') {
            return;
        }

        session([$this->modelMemoryKey() => $id]);
    }

    private function modelMemoryKey(): string
    {
        return 'hireach.ai.model.'.(string) (auth()->id() ?: 'guest');
    }

    private function hydrateSession(string $sessionId): bool
    {
        $sessionId = trim($sessionId);
        if ($sessionId === '') {
            return false;
        }

        try {
            $row = app(AiProviderClient::class)->getConversation($sessionId);
        } catch (Throwable $e) {
            $this->error = $e->getMessage();

            return false;
        }

        $this->sessionId = (string) ($row['session_id'] ?: $sessionId);
        $this->activeSession = $this->sessionId;
        $this->sessionTitle = (string) ($row['title'] ?: 'New chat');
        $this->messages = $row['messages'];
        $this->error = '';
        $this->pendingAction = [];
        $this->isThinking = false;
        $this->dispatchBrowserEvent('hireach-ai-scroll');

        return true;
    }

    private function ensureSession(): void
    {
        if ($this->sessionId !== '') {
            return;
        }

        $this->sessionId = (string) Str::uuid();
        $this->activeSession = $this->sessionId;
        $this->pushChatUrl($this->sessionId);
    }

    private function pushChatUrl(string $uuid): void
    {
        $this->dispatchBrowserEvent('hireach-ai-url', [
            'uuid' => $uuid,
        ]);
    }

    private function metadata(): array
    {
        $user = auth()->user();

        $metadata = [
            'end_user_id' => (string) $user->getKey(),
            'end_user_name' => $user->name,
            'feature' => 'hireach_ai_chat',
            'session_id' => $this->sessionId,
        ];

        if (!empty($user->email)) {
            $metadata['end_user_email'] = $user->email;
        }

        return $metadata;
    }

    private function visibleReply(string $content): string
    {
        $content = AiChatOrchestrator::cleanReportReply($content);
        $content = preg_replace('/<\/?(?:final_answer|answer|thinking|thought|response)\b[^>]*>/i', '', $content) ?? $content;
        $content = preg_replace(
            '/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}/',
            '',
            $content
        ) ?? $content;

        $content = preg_replace(
            '/\b(?:uuid|user_id|msg_id|end_user_id|session_id|template_id|blast_id|id)\s*[:=]\s*[A-Za-z0-9_\-]+/i',
            '',
            $content
        ) ?? $content;

        $content = preg_replace("/\n{3,}/", "\n\n", $content) ?? $content;
        $content = preg_replace('/\(\s*[,;]\s*\)/', '', $content) ?? $content;
        $content = trim($content);

        return $content !== '' ? $content : 'Maaf, AI tidak memberikan jawaban.';
    }

    private function isAffirmative(string $text): bool
    {
        $normalized = mb_strtolower(trim($text));
        $normalized = preg_replace('/[^\p{L}\p{N}\s]/u', '', $normalized) ?? $normalized;

        return in_array($normalized, [
            'ya', 'iya', 'yes', 'y', 'ok', 'oke', 'okay',
            'setuju', 'boleh', 'gas', 'silakan', 'silahkan',
            'konfirmasi', 'confirm', 'lanjut',
        ], true);
    }

    private function finalizeAssistant(string $raw, string $userText): string
    {
        return $this->attachExport($this->applyProposal(AiChatOrchestrator::cleanReportReply($raw), $userText), $userText);
    }

    private function attachExport(string $visible, string $userText): string
    {
        if (preg_match('/\bcsv\b/i', $userText)
            && ! preg_match('/\b(?:pdf|excel|xlsx)\b/i', $userText)
            && preg_match('/\b(?:buat|unduh|download|export|ekspor|laporan|report)\b/iu', $userText)) {
            return 'Format CSV belum tersedia. Saya bisa membuat laporan Excel atau PDF.';
        }
        if (AiChatOrchestrator::asksAboutCapabilities([['role' => 'user', 'content' => $userText]])) {
            return $visible;
        }
        if (str_contains($visible, '/ai/report/')) {
            return $visible;
        }

        $spec = $this->inferExport($userText);
        if ($spec === null) {
            return $visible;
        }

        try {
            $file = app(AiResourceExecutor::class)->exportReport(
                $spec['resource'],
                $spec['format'],
                auth()->user(),
                $userText
            );
        } catch (Throwable $e) {
            $message = preg_match('/^(?:Laporan (?:melebihi 1\.000 baris|terlalu besar)|Filter status )/u', $e->getMessage())
                ? $e->getMessage()
                : 'Laporan belum dapat dibuat. Periksa izin data atau coba lagi.';

            return trim($visible."\n\n".$message);
        }

        $kind = $file['format'] === 'pdf' ? 'PDF' : 'Excel';

        $report = 'Laporan '.$kind.' berisi '.$file['count'].' data sudah siap. '
            .'[Lihat preview]('.$file['preview_url'].')';
        $report .= ! empty($file['print_only'])
            ? '. Untuk huruf di luar Latin, pilih "Cetak / Simpan PDF" pada preview agar teks tetap utuh.'
            : ' · [Download '.$kind.']('.$file['url'].')';

        return trim($visible."\n\n".$report);
    }

    private function inferExport(string $userText): ?array
    {
        $q = mb_strtolower($userText);
        if (! preg_match('/\b(export|unduh|download|excel|xlsx|csv|pdf|laporan|report)\b/i', $q)) {
            return null;
        }

        $resource = AiResourceExecutor::namedResource($userText);
        if ($resource === null) {
            return null;
        }

        return [
            'resource' => $resource,
            'format' => preg_match('/\bpdf\b/i', $q) ? 'pdf' : 'xlsx',
        ];
    }

    private function applyProposal(string $raw, string $userText): string
    {
        $executor = app(AiResourceExecutor::class);
        $proposal = $executor->parseProposal($raw);
        $visible = $this->visibleReply($executor->stripProposal($raw));

        if ($proposal) {
            $this->pendingAction = $proposal;
            session()->put($this->pendingKey(), $proposal);
            if ($visible === 'Maaf, AI tidak memberikan jawaban.') {
                $visible = $proposal['summary'];
            }
        }

        return $visible;
    }

    private function formatCount(int $n): string
    {
        return number_format($n, 0, '.', ',');
    }

    private function moneyPair($used, $limit, string $currency, ?string $usedLabel = null, ?string $limitLabel = null): string
    {
        return $this->formatMoney($used, $currency, $usedLabel)
            .' / '
            .$this->formatMoney($limit, $currency, $limitLabel);
    }

    private function formatMoney($amount, string $currency, ?string $fallback = null): string
    {
        if ($amount === null || $amount === '') {
            $fallback = is_string($fallback) ? trim($fallback) : '';
            if ($fallback === '') {
                return '—';
            }

            return preg_replace('/\.00\b/', '', $fallback) ?: $fallback;
        }

        $amount = (float) $amount;
        if (strtoupper($currency) === 'IDR') {
            return 'Rp '.number_format($amount, 0, '.', ',');
        }

        $decimals = abs($amount - round($amount)) < 0.005 ? 0 : 2;

        return '$'.number_format($amount, $decimals, '.', ',');
    }

    private function lastUserText(): string
    {
        foreach (array_reverse($this->messages) as $message) {
            if (($message['role'] ?? '') === 'user') {
                return (string) ($message['content'] ?? '');
            }
        }

        return '';
    }

    private function rememberSessionTitle(string $text): void
    {
        if ($this->sessionTitle !== 'New chat') {
            return;
        }

        $title = trim(preg_replace('/\s+/', ' ', $text) ?? $text);
        $title = $title === '' ? 'New chat' : Str::limit($title, 42);

        $this->sessionTitle = $title;
        $this->activeSession = $this->sessionId;
    }
}
