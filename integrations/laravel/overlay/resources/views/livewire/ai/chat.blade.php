<div
    class="ai-chat-root fixed left-0 right-0 bottom-0 top-16 flex bg-white text-gray-900 dark:bg-gray-900 dark:text-gray-100{{ $pendingDeleteId !== '' ? ' is-modal' : '' }}"
    data-hireach-chat
    data-stream-url="{{ url('/ai/stream') }}"
    data-csrf="{{ csrf_token() }}"
    x-data="hireachAiChat()"
    x-init="boot()"
    x-on:hireach-ai-think.window="onThink()"
    x-on:hireach-ai-stream.window="startStream($event.detail)"
    x-on:hireach-ai-scroll.window="scrollThread()"
    x-on:hireach-ai-url.window="onUrl($event)"
    x-on:hireach-ai-focus.window="focusBox()"
>
    <style>
        [x-cloak] { display: none !important; }
        .ai-chat-root {
            z-index: 20;
            overflow: hidden;
        }
        .ai-chat-root.is-modal {
            z-index: 1100;
            overflow: visible;
        }
        .ai-pane {
            width: 18rem;
            transform: translateX(0);
            transition:
                width 280ms cubic-bezier(0.22, 1, 0.36, 1),
                transform 280ms cubic-bezier(0.22, 1, 0.36, 1),
                border-color 280ms ease;
        }
        .ai-pane.is-closed {
            width: 0;
            border-color: transparent;
        }
        .ai-pane button:focus {
            outline: none;
            box-shadow: none;
        }
        .ai-recent {
            display: flex;
            align-items: center;
            gap: 2px;
        }
        .ai-recent-del {
            opacity: 0;
            flex: 0 0 auto;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 1.75rem;
            height: 1.75rem;
            border: 0;
            border-radius: 0.4rem;
            background: transparent;
            color: #9ca3af;
            cursor: pointer;
        }
        .ai-recent:hover .ai-recent-del,
        .ai-recent-del:focus {
            opacity: 1;
        }
        .ai-recent-del:hover {
            background: #f3f4f6;
            color: #b91c1c;
        }
        .dark .ai-recent-del:hover {
            background: #1f2937;
            color: #fca5a5;
        }
        @media (hover: none) {
            .ai-recent-del { opacity: .7; }
        }
        .ai-modal-bg {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 1101;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1.25rem;
            background: rgba(17, 24, 39, 0.18);
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
        }
        .ai-modal {
            width: min(22.5rem, 100%);
            border-radius: 1rem;
            background: #fff;
            padding: 1.2rem 1.25rem 1.1rem;
            box-shadow: 0 24px 48px rgba(0, 0, 0, 0.18);
        }
        .dark .ai-modal {
            background: #111827;
            box-shadow: 0 24px 48px rgba(0, 0, 0, 0.45);
        }
        .ai-modal h3 {
            margin: 0;
            font-size: 1rem;
            font-weight: 600;
            color: #111827;
        }
        .dark .ai-modal h3 { color: #f9fafb; }
        .ai-modal p {
            margin: 0.4rem 0 0;
            font-size: 0.875rem;
            line-height: 1.45;
            color: #6b7280;
        }
        .dark .ai-modal p { color: #9ca3af; }
        .ai-modal-actions {
            display: flex;
            justify-content: flex-end;
            gap: 0.5rem;
            margin-top: 1.1rem;
        }
        .ai-pane-backdrop {
            opacity: 0;
            pointer-events: none;
            transition: opacity 280ms ease;
        }
        .ai-pane-backdrop.is-open {
            opacity: 1;
            pointer-events: auto;
        }
        @media (max-width: 1023px) {
            .ai-pane {
                position: fixed;
                top: 4rem;
                bottom: 0;
                left: 0;
                z-index: 30;
                width: 18rem;
            }
            .ai-pane.is-closed {
                width: 18rem;
                transform: translateX(-100%);
            }
        }
        .ai-thread {
            min-width: 0;
            min-height: 0;
            flex: 1 1 auto;
            height: 100%;
            display: flex;
            flex-direction: column;
        }
        .ai-messages {
            flex: 1 1 auto;
            min-height: 0;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
        }
        .ai-stage {
            flex: 1 1 auto;
            min-height: 0;
            display: flex;
            flex-direction: column;
        }
        .ai-composer {
            flex: 0 0 auto;
            position: sticky;
            bottom: 0;
            z-index: 10;
            padding: 0.5rem 1.5rem 1.25rem;
            background: #fff;
        }
        .dark .ai-composer { background: #111827; }
        .ai-composer-box {
            display: flex;
            flex-direction: column;
            align-items: stretch;
            gap: 4px;
            width: 100%;
            border-radius: 1.5rem;
            border: 1px solid #d1d5db;
            background: #fff;
            padding: 10px 10px 8px 14px;
            box-shadow: 0 1px 2px rgba(0, 0, 0, .04);
        }
        .ai-composer-toolbar {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 4px;
        }
        .dark .ai-composer-box {
            border-color: #374151;
            background: #1f2937;
        }
        .ai-composer-box:focus-within {
            border-color: #9ca3af;
            box-shadow: 0 4px 12px rgba(0, 0, 0, .06);
        }
        .dark .ai-composer-box:focus-within { border-color: #6b7280; }
        .ai-thread.is-empty .ai-stage {
            justify-content: center;
            overflow-y: auto;
            padding: 0 1.5rem 3rem;
        }
        .ai-thread.is-empty .ai-messages {
            flex: 0 0 auto;
            overflow: visible;
            padding: 0;
        }
        .ai-thread.is-empty .ai-composer {
            flex: 0 0 auto;
            position: static;
            width: 100%;
            padding: 1rem 0 0;
            background: transparent;
        }
        .ai-composer-box textarea {
            min-height: 36px;
            max-height: 10rem;
            overflow-y: auto;
        }
        .ai-thread.is-empty .ai-composer-box textarea {
            max-height: min(40vh, 16rem);
        }
        .ai-thread.is-empty .ai-composer form,
        .ai-thread.is-empty .ai-empty-hero {
            width: 100%;
            max-width: 48rem;
            margin-left: auto;
            margin-right: auto;
        }
        .ai-empty-hero {
            padding: 0 0 1rem;
            text-align: center;
        }
        .ai-empty-hero h2 {
            margin: 0;
            font-size: 1.5rem;
            line-height: 1.3;
            font-weight: 600;
            letter-spacing: -0.02em;
            color: #111827;
        }
        .dark .ai-empty-hero h2 { color: #f9fafb; }
        .ai-row {
            display: flex;
            align-items: flex-start;
            margin-bottom: 0.7rem;
        }
        .ai-row-user {
            justify-content: flex-end;
            align-items: flex-start;
        }
        .ai-row-assistant {
            justify-content: flex-start;
            align-items: flex-start;
        }
        .ai-msg {
            display: flex;
            align-items: flex-start;
            gap: 6px;
            max-width: 100%;
        }
        .ai-row-user .ai-msg { flex-direction: row-reverse; }
        .ai-copy {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            margin-top: 2px;
            flex-shrink: 0;
            border: 0;
            border-radius: 8px;
            background: transparent;
            color: #9ca3af;
            cursor: pointer;
            opacity: 0;
        }
        .ai-msg:hover .ai-copy,
        .ai-copy:focus,
        .ai-copy[data-copied] { opacity: 1; }
        .ai-copy:hover { background: #f3f4f6; color: #4b5563; }
        .dark .ai-copy:hover { background: #1f2937; color: #d1d5db; }
        .ai-copy:focus { outline: none; box-shadow: none; }
        .ai-copy-on { display: none; }
        .ai-copy[data-copied] .ai-copy-off { display: none; }
        .ai-copy[data-copied] .ai-copy-on { display: block; color: #16a34a; }
        @media (hover: none) {
            .ai-copy { opacity: .5; }
        }
        .ai-bubble {
            display: block;
            width: fit-content;
            max-width: min(32rem, 78%);
            overflow-wrap: anywhere;
            word-break: break-word;
            line-height: 1.5;
            font-size: 16px;
            text-align: left;
            vertical-align: top;
        }
        .ai-bubble-user {
            background: #f3f4f6;
            color: #111827;
            padding: 0.6rem 0.9rem;
            border-radius: 1.15rem 1.15rem 0.4rem 1.15rem;
            white-space: normal;
        }
        .ai-bubble-user p {
            margin: 0 0 0.7em;
        }
        .ai-bubble-user p:last-child { margin-bottom: 0; }
        .ai-bubble-assistant {
            background: transparent;
            color: #111827;
            padding: 0.1rem 0;
            width: 100%;
            max-width: 100%;
            white-space: normal;
        }
        .ai-md > :first-child { margin-top: 0; }
        .ai-md > :last-child { margin-bottom: 0; }
        .ai-md p { margin: 0 0 0.8em; }
        .ai-md strong { font-weight: 600; }
        .ai-md em { font-style: italic; }
        .ai-md del { text-decoration: line-through; color: #6b7280; }
        .ai-md ul {
            list-style: disc outside;
            margin: 0.4em 0 0.85em;
            padding-left: 1.35rem;
        }
        .ai-md ol {
            list-style: decimal outside;
            margin: 0.4em 0 0.85em;
            padding-left: 1.35rem;
        }
        .ai-md ul ul { list-style-type: circle; margin: 0.2em 0; }
        .ai-md ul ul ul { list-style-type: square; }
        .ai-md ol ol { list-style-type: lower-alpha; }
        .ai-md li { margin: 0.2em 0; padding-left: 0.15rem; }
        .ai-md li::marker { color: #6b7280; }
        .ai-md li > p { margin: 0; }
        .ai-md li > p + p { margin-top: 0.35em; }
        .ai-md :not(pre) > code {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 0.84em;
            background: #f3f4f6;
            border: 1px solid #e5e7eb;
            padding: 0.12em 0.4em;
            border-radius: 0.35rem;
        }
        .ai-md pre {
            margin: 0.7em 0 0.95em;
            padding: 0.85rem 1rem;
            overflow-x: auto;
            border: 1px solid #e5e7eb;
            border-radius: 0.75rem;
            background: #f9fafb;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 13px;
            line-height: 1.55;
            overflow-wrap: normal;
            word-break: normal;
            white-space: pre;
        }
        .ai-md pre code {
            background: transparent;
            border: 0;
            padding: 0;
            font-size: inherit;
        }
        .ai-md a {
            color: #2563eb;
            text-decoration: underline;
            text-underline-offset: 2px;
            cursor: pointer;
        }
        .dark .ai-md a { color: #93c5fd; }
        .ai-md img {
            max-width: 100%;
            height: auto;
            border-radius: 0.5rem;
        }
        .ai-md blockquote {
            margin: 0.65em 0 0.9em;
            padding: 0.15em 0 0.15em 0.85rem;
            border-left: 3px solid #d1d5db;
            color: #4b5563;
        }
        .ai-md hr {
            border: 0;
            border-top: 1px solid #e5e7eb;
            margin: 0.9em 0;
        }
        .ai-table {
            margin: 0.7em 0 1em;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            border: 1px solid #e5e7eb;
            border-radius: 0.75rem;
            background: #fff;
        }
        .ai-md table {
            width: 100%;
            min-width: 28rem;
            border-collapse: collapse;
            margin: 0;
            font-size: 14px;
            line-height: 1.45;
        }
        .ai-md thead th {
            background: #f9fafb;
            font-weight: 600;
            white-space: nowrap;
        }
        .ai-md th,
        .ai-md td {
            border: 0;
            border-bottom: 1px solid #f3f4f6;
            padding: 0.55rem 0.8rem;
            text-align: left;
            vertical-align: top;
        }
        .ai-md tbody tr:last-child th,
        .ai-md tbody tr:last-child td { border-bottom: 0; }
        .ai-md h1,
        .ai-md h2,
        .ai-md h3,
        .ai-md h4 {
            font-size: 16px;
            font-weight: 600;
            margin: 0.85em 0 0.4em;
            line-height: 1.35;
        }
        .dark .ai-bubble-user {
            background: #1f2937;
            color: #f3f4f6;
        }
        .dark .ai-bubble-assistant {
            background: transparent;
            color: #e5e7eb;
        }
        .dark .ai-md :not(pre) > code,
        .dark .ai-md pre {
            background: #111827;
            border-color: #374151;
        }
        .dark .ai-table {
            border-color: #374151;
            background: #1f2937;
        }
        .dark .ai-md thead th {
            background: #111827;
        }
        .dark .ai-md th,
        .dark .ai-md td,
        .dark .ai-md hr {
            border-color: #374151;
        }
        .dark .ai-md blockquote {
            border-left-color: #4b5563;
            color: #9ca3af;
        }
        .dark .ai-md li::marker {
            color: #9ca3af;
        }
        .dark .ai-contrast-button {
            color: #111827;
        }
        .ai-confirm {
            margin: 0 auto 12px;
            max-width: 48rem;
            padding: 12px 14px;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            background: #fffbeb;
        }
        .dark .ai-confirm {
            border-color: #374151;
            background: #1c1917;
        }
        .ai-confirm-title {
            margin: 0 0 4px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: .04em;
            text-transform: uppercase;
            color: #92400e;
        }
        .dark .ai-confirm-title { color: #fbbf24; }
        .ai-confirm-kicker {
            margin: 0 0 6px;
            font-size: 12px;
            color: #a16207;
        }
        .dark .ai-confirm-kicker { color: #fbbf24; }
        .ai-confirm-body {
            margin: 0 0 10px;
            font-size: 16px;
            line-height: 1.5;
        }
        .ai-confirm-actions { display: flex; justify-content: flex-end; gap: 8px; }
        .ai-quota {
            margin: 8px 12px 12px;
            padding: 10px 12px;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
        }
        .dark .ai-quota { border-color: #1f2937; }
        .ai-quota-bar {
            height: 6px;
            margin-top: 8px;
            overflow: hidden;
            border-radius: 999px;
            background: #f3f4f6;
        }
        .dark .ai-quota-bar { background: #1f2937; }
        .ai-quota-bar > span {
            display: block;
            height: 100%;
            border-radius: 999px;
            background: #3b82f6;
        }
        .ai-quota-bar.is-warn > span { background: #d97706; }
        .ai-quota-bar.is-over > span { background: #dc2626; }
        .ai-thinking {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 16px;
            color: #9ca3af;
        }
        .ai-thinking-dots {
            display: inline-flex;
            gap: 4px;
        }
        .ai-thinking-dots span {
            width: 6px;
            height: 6px;
            border-radius: 999px;
            background: currentColor;
            animation: ai-think 1s infinite ease-in-out;
        }
        .ai-thinking-dots span:nth-child(2) { animation-delay: .15s; }
        .ai-thinking-dots span:nth-child(3) { animation-delay: .3s; }
        .ai-stream {
            white-space: pre-line;
        }
        .ai-stream::after {
            content: '▍';
            margin-left: 1px;
            animation: ai-caret 1s step-end infinite;
        }
        @keyframes ai-caret {
            50% { opacity: 0; }
        }
        @keyframes ai-think {
            0%, 80%, 100% { opacity: .25; transform: translateY(0); }
            40% { opacity: 1; transform: translateY(-3px); }
        }
        @media (prefers-reduced-motion: reduce) {
            .ai-pane,
            .ai-pane-backdrop {
                transition: none;
            }
        }
    </style>

    <button
        type="button"
        class="ai-pane-backdrop fixed left-0 right-0 bottom-0 top-16 z-20 bg-black bg-opacity-30 lg:hidden"
        :class="{ 'is-open': open }"
        @click="toggle()"
        aria-label="Close sidebar"
    ></button>

    <aside
        class="ai-pane z-30 flex h-full shrink-0 flex-col overflow-hidden border-r border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900"
        :class="{ 'is-closed': ! open }"
    >
        <div class="flex h-full w-72 shrink-0 flex-col">
            <div class="flex shrink-0 items-center justify-between px-4 pb-2 pt-4">
                <div class="text-lg font-semibold tracking-tight text-gray-950 dark:text-white">
                    AI Chat
                </div>

                <button
                    type="button"
                    class="flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
                    title="Close sidebar"
                    aria-label="Close sidebar"
                    @click="toggle()"
                >
                    <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <rect x="5" y="4" width="14" height="16" rx="1" stroke="currentColor" stroke-width="1.5" />
                        <path d="M10 4V20" stroke="currentColor" stroke-width="1.5" />
                    </svg>
                </button>
            </div>

            <div class="shrink-0 px-3 pb-2">
                <button
                    type="button"
                    wire:click="resetChat"
                    class="flex w-full items-center gap-3 rounded-xl bg-gray-100 px-3 py-2 text-left text-sm font-medium text-gray-900 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-white dark:hover:bg-gray-700"
                >
                    <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M12 5V19M5 12H19" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
                    </svg>
                    <span>New chat</span>
                </button>
            </div>

            <div class="flex min-h-0 flex-1 flex-col">
                <div class="shrink-0 px-5 pb-2 text-xs font-medium uppercase tracking-wide text-gray-400">
                    Recents
                </div>

                <div class="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
                    @forelse ($sessions as $chat)
                        <div class="ai-recent rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800">
                            <button
                                type="button"
                                wire:click="openSession('{{ $chat['session_id'] }}')"
                                class="flex min-w-0 flex-1 items-center gap-3 rounded-lg px-3 py-2 text-left focus:outline-none focus:ring-0"
                            >
                                <span @class([
                                    'h-1.5 w-1.5 shrink-0 rounded-full',
                                    'bg-blue-500' => $activeSession === ($chat['session_id'] ?? ''),
                                    'border border-gray-300 dark:border-gray-600' => $activeSession !== ($chat['session_id'] ?? ''),
                                ])></span>
                                <span @class([
                                    'truncate text-sm',
                                    'text-gray-900 dark:text-gray-100' => $activeSession === ($chat['session_id'] ?? ''),
                                    'text-gray-600 dark:text-gray-400' => $activeSession !== ($chat['session_id'] ?? ''),
                                ])>
                                    {{ $chat['title'] ?? 'Untitled' }}
                                </span>
                            </button>
                            <button
                                type="button"
                                class="ai-recent-del"
                                title="Delete"
                                aria-label="Delete chat"
                                wire:click="askDeleteSession('{{ $chat['session_id'] }}')"
                            >
                                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                    <path d="M9 4h6M5 7h14M8 7l.8 12.2A2 2 0 0 0 10.8 21h2.4a2 2 0 0 0 2-.8L16 7" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M10 11v6M14 11v6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>
                                </svg>
                            </button>
                        </div>
                    @empty
                        <p class="px-3 py-2 text-sm text-gray-400">Belum ada riwayat.</p>
                    @endforelse
                </div>
            </div>

            @if (!empty($this->usageCard['visible']))
                <div class="ai-quota shrink-0">
                    <div class="flex items-center justify-between gap-2">
                        <div class="text-xs font-medium uppercase tracking-wide text-gray-400">
                            {{ $this->usageCard['title'] }}
                        </div>
                        @if ($this->usageCard['percent_label'])
                            <div @class([
                                'text-xs font-semibold tabular-nums',
                                'text-gray-500 dark:text-gray-400' => $this->usageCard['percent'] < 70,
                                'text-amber-600 dark:text-amber-400' => $this->usageCard['percent'] >= 70 && $this->usageCard['percent'] < 90,
                                'text-red-600 dark:text-red-400' => $this->usageCard['percent'] >= 90,
                            ])>
                                {{ $this->usageCard['percent_label'] }}
                            </div>
                        @endif
                    </div>
                    <div class="mt-1 text-sm font-semibold text-gray-900 dark:text-white">
                        {{ $this->usageCard['headline'] }}
                    </div>
                    @if ($this->usageCard['percent'] !== null)
                        <div @class([
                            'ai-quota-bar',
                            'is-warn' => $this->usageCard['percent'] >= 70 && $this->usageCard['percent'] < 90,
                            'is-over' => $this->usageCard['percent'] >= 90,
                        ])>
                            <span style="width: {{ min(100, max(0, $this->usageCard['percent'])) }}%"></span>
                        </div>
                    @endif
                    @if ($this->usageCard['detail'])
                        <div class="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
                            {{ $this->usageCard['detail'] }}
                        </div>
                    @endif
                    @if ($this->usageCard['note'])
                        <div class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                            {{ $this->usageCard['note'] }}
                        </div>
                    @endif
                </div>
            @endif
        </div>
    </aside>

    <div @class(['ai-thread relative', 'is-empty' => $messages === [] && ! $isThinking])>
        <div class="flex h-12 shrink-0 items-center justify-between border-b border-gray-200 px-3 dark:border-gray-700">
            <div class="flex min-w-0 items-center gap-2">
                <button
                    type="button"
                    class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
                    title="Open sidebar"
                    aria-label="Open sidebar"
                    x-show="! open"
                    @click="toggle()"
                >
                    <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <rect x="5" y="4" width="14" height="16" rx="1" stroke="currentColor" stroke-width="1.5" />
                        <path d="M10 4V20" stroke="currentColor" stroke-width="1.5" />
                    </svg>
                </button>

                <a href="{{ route('ai.chat') }}" class="flex-shrink-0 rounded-md px-2 py-1 text-sm text-gray-500 transition-colors hover:bg-gray-100 hover:text-blue-600 dark:text-gray-400 dark:hover:bg-gray-800">AI</a>
                <svg class="h-4 w-4 flex-shrink-0 text-gray-300 dark:text-gray-500" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                    <path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd"></path>
                </svg>
                <h1 class="min-w-0 truncate rounded-md bg-gray-100 px-2 py-1 text-sm font-medium text-blue-600 dark:bg-gray-800 dark:text-blue-400" title="{{ $sessionTitle }}">
                    {{ $sessionTitle }}
                </h1>
            </div>

            <button
                type="button"
                wire:click="resetChat"
                class="rounded-lg px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800 lg:hidden"
            >
                New
            </button>
        </div>

        <div class="ai-stage">
        <div class="ai-messages px-4 py-5 sm:px-6" x-ref="thread">
            @if ($messages === [] && ! $isThinking)
                <div class="ai-empty-hero">
                    <h2>How can I help you today?</h2>
                </div>
            @endif

            <div class="mx-auto w-full max-w-3xl">
                @foreach ($messages as $message)
                    @if (($message['role'] ?? '') === 'user')
                        <div class="ai-row ai-row-user">
                            <div class="ai-msg">
                                <div class="ai-bubble ai-bubble-user">{!! $this->formatUserMessage((string) ($message['content'] ?? '')) !!}</div>
                                <button type="button" class="ai-copy" title="Copy" aria-label="Copy" @click="copyMsg($event.currentTarget)">
                                    <svg class="ai-copy-off h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                        <rect x="9" y="9" width="11" height="13" rx="2" stroke="currentColor" stroke-width="1.7"/>
                                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" stroke="currentColor" stroke-width="1.7"/>
                                    </svg>
                                    <svg class="ai-copy-on h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                        <path d="M5 12l4 4 10-10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                    @else
                        <div class="ai-row ai-row-assistant">
                            <div class="ai-msg">
                                <div class="ai-bubble ai-bubble-assistant ai-md">
                                    {!! $this->formatMessage((string) ($message['content'] ?? '')) !!}
                                </div>
                                <button type="button" class="ai-copy" title="Copy" aria-label="Copy" @click="copyMsg($event.currentTarget)">
                                    <svg class="ai-copy-off h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                        <rect x="9" y="9" width="11" height="13" rx="2" stroke="currentColor" stroke-width="1.7"/>
                                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" stroke="currentColor" stroke-width="1.7"/>
                                    </svg>
                                    <svg class="ai-copy-on h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                        <path d="M5 12l4 4 10-10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                    @endif
                @endforeach

                @if ($isThinking)
                    <div class="ai-row ai-row-assistant" wire:key="thinking" x-show="! streamDraft">
                        <div class="ai-thinking" aria-live="polite">
                            <span x-text="activityLabel">Thinking</span>
                            <span class="ai-thinking-dots" aria-hidden="true">
                                <span></span>
                                <span></span>
                                <span></span>
                            </span>
                        </div>
                    </div>
                    <div class="ai-row ai-row-assistant" x-show="streamDraft" x-cloak>
                        <div class="ai-bubble ai-bubble-assistant ai-stream" style="white-space: pre-wrap" x-text="visibleDraft(streamDraft)"></div>
                    </div>
                @endif
            </div>
        </div>

        @if ($error)
            <div class="shrink-0 px-4 pb-2 text-center text-sm text-red-600">
                {{ $error }}
            </div>
        @endif

        @if (! empty($pendingAction))
            <div class="ai-confirm">
                <p class="ai-confirm-title">Needs your confirmation</p>
                <p class="ai-confirm-kicker">{{ ucfirst((string) ($pendingAction['action'] ?? 'change')) }} · nothing is saved until you confirm</p>
                <p class="ai-confirm-body">{{ $pendingAction['summary'] ?? '' }}</p>
                <div class="ai-confirm-actions">
                    <button type="button" class="rounded-lg px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800" wire:click="rejectPending">
                        Cancel
                    </button>
                    <button type="button" class="ai-contrast-button rounded-lg bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 dark:bg-white dark:text-gray-900" wire:click="confirmPending">
                        Confirm
                    </button>
                </div>
            </div>
        @endif

        <div class="ai-composer">
            @php $emptyComposer = $messages === [] && ! $isThinking; @endphp
            <form wire:submit.prevent="send" class="mx-auto w-full max-w-3xl">
                <div class="ai-composer-box">
                    <textarea
                        x-ref="box"
                        wire:model.defer="input"
                        rows="1"
                        placeholder="{{ $emptyComposer ? 'Message' : 'How can I help you today?' }}"
                        autocomplete="off"
                        @if ($isThinking) disabled @endif
                        class="min-w-0 w-full resize-none border-0 bg-transparent py-1 text-[16px] leading-6 text-gray-900 placeholder-gray-400 outline-none focus:ring-0 disabled:opacity-60 dark:text-white dark:placeholder-gray-500"
                        x-init="resizeBox($el)"
                        @input="resizeBox($event.target)"
                        @keydown.enter="
                            if (!$event.shiftKey) {
                                $event.preventDefault();
                                const form = $event.target.form;
                                const submit = form && form.querySelector('[type=submit]');
                                if (submit && ! submit.disabled) {
                                    submit.click();
                                }
                            }
                        "
                    ></textarea>

                    <div class="ai-composer-toolbar">
                        @include('livewire.ai.model-picker', ['inline' => true, 'openDown' => $emptyComposer])

                        <button
                            type="submit"
                            wire:loading.attr="disabled"
                            @if ($isThinking) disabled @endif
                            class="ai-contrast-button flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-900 text-white transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-200"
                            title="Send"
                        >
                            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                <path d="M12 19V5M6 11L12 5L18 11" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                            </svg>
                        </button>
                    </div>
                </div>
            </form>

            @if ($modelsError)
                <div class="mx-auto mt-2 max-w-3xl text-xs text-red-600">
                    {{ $modelsError }}
                </div>
            @endif
        </div>
        </div>
    </div>
    @if ($pendingDeleteId !== '')
        <div class="ai-modal-bg" wire:click="cancelDelete">
            <div class="ai-modal" onclick="event.stopPropagation()">
                <h3>Delete chat?</h3>
                <p>This will remove “{{ $pendingDeleteTitle }}” from Recents. It cannot be undone.</p>
                <div class="ai-modal-actions">
                    <button type="button" class="rounded-lg px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800" wire:click="cancelDelete">
                        Cancel
                    </button>
                    <button type="button" class="rounded-lg bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-500" wire:click="confirmDelete">
                        Delete
                    </button>
                </div>
            </div>
        </div>
    @endif
    <script>
        window.hireachAiChat = function () {
            return {
                open: (function () {
                    try { return localStorage.getItem('hireach.ai.sidebar') !== '0'; } catch (e) { return true; }
                })(),
                modelsOpen: false,
                streamDraft: '',
                activityLabel: 'Thinking',
                streamUrl: '',
                csrf: '',
                toggle: function () {
                    this.open = ! this.open;
                    try { localStorage.setItem('hireach.ai.sidebar', this.open ? '1' : '0'); } catch (e) {}
                },
                boot: function () {
                    this.streamUrl = this.$el.getAttribute('data-stream-url') || '/ai/stream';
                    this.csrf = this.$el.getAttribute('data-csrf') || '';
                    var self = this;
                    this.$nextTick(function () {
                        self.scrollThread();
                    });
                    if (window.__hireachAiPopBound) {
                        return;
                    }
                    window.__hireachAiPopBound = true;
                    window.addEventListener('popstate', function () {
                        var root = document.querySelector('[data-hireach-chat]');
                        if (! root || ! window.livewire) {
                            return;
                        }
                        var wire = window.livewire.find(root.getAttribute('wire:id'));
                        if (! wire) {
                            return;
                        }
                        var match = window.location.pathname.match(/^\/ai\/([0-9a-fA-F-]{36})$/);
                        if (match) {
                            wire.call('restoreSession', match[1]);
                        } else if (window.location.pathname === '/ai' || window.location.pathname === '/ai/') {
                            wire.call('resetChat');
                        }
                    });
                },
                wire: function () {
                    var id = this.$el.getAttribute('wire:id');
                    return window.livewire ? window.livewire.find(id) : null;
                },
                onThink: function () {
                    this.activityLabel = 'Thinking';
                    var self = this;
                    this.$nextTick(function () {
                        self.resizeBox();
                        self.scrollThread();
                    });
                },
                focusBox: function () {
                    var self = this;
                    this.$nextTick(function () {
                        setTimeout(function () {
                            var el = self.$refs.box;
                            if (el && ! el.disabled) {
                                el.focus();
                            }
                        }, 40);
                    });
                },
                onUrl: function (event) {
                    var uuid = event && event.detail ? (event.detail.uuid || '') : '';
                    this.setChatUrl(uuid);
                },
                setChatUrl: function (uuid) {
                    var path = uuid ? ('/ai/' + uuid) : '/ai';
                    if (window.location.pathname !== path) {
                        history.pushState({ chat: uuid || '' }, '', path);
                    }
                },
                nearBottom: function () {
                    var el = this.$refs.thread;
                    if (! el) {
                        return true;
                    }
                    return (el.scrollHeight - el.scrollTop - el.clientHeight) < 96;
                },
                scrollThread: function (mode) {
                    var self = this;
                    this.$nextTick(function () {
                        var el = self.$refs.thread;
                        if (! el) {
                            return;
                        }
                        if (mode === 'follow' && ! self.nearBottom()) {
                            return;
                        }
                        el.scrollTop = el.scrollHeight;
                    });
                },
                scrollFollow: function () {
                    var self = this;
                    if (this._followTimer) {
                        return;
                    }
                    this._followTimer = setTimeout(function () {
                        self._followTimer = null;
                        self.scrollThread('follow');
                    }, 140);
                },
                resizeBox: function (el) {
                    el = el || this.$refs.box;
                    if (! el) {
                        return;
                    }
                    var max = parseFloat(window.getComputedStyle(el).maxHeight) || 260;
                    el.style.overflowY = 'hidden';
                    el.style.height = 'auto';
                    var next = el.scrollHeight;
                    if (next > max) {
                        el.style.height = max + 'px';
                        el.style.overflowY = 'auto';
                    } else {
                        el.style.height = Math.max(36, next) + 'px';
                    }
                },
                visibleDraft: function (text) {
                    text = text || '';
                    text = text.replace(/<\/?(?:final_answer|answer|thinking|thought|response)\b[^>]*>/gi, '');
                    var cut = text.indexOf('<<<CONFIRM');
                    return cut < 0 ? text : text.slice(0, cut);
                },
                copyMsg: function (btn) {
                    var wrap = btn && btn.closest ? btn.closest('.ai-msg') : null;
                    var bubble = wrap ? wrap.querySelector('.ai-bubble') : null;
                    var text = bubble && bubble.innerText ? bubble.innerText.replace(/\n{3,}/g, '\n\n').trim() : '';
                    if (! text) {
                        return;
                    }
                    var done = function () {
                        btn.setAttribute('data-copied', '1');
                        setTimeout(function () { btn.removeAttribute('data-copied'); }, 1200);
                    };
                    var fallback = function () {
                        var ta = document.createElement('textarea');
                        ta.value = text;
                        document.body.appendChild(ta);
                        ta.select();
                        var copied = false;
                        try { copied = document.execCommand('copy'); } catch (e) {}
                        document.body.removeChild(ta);
                        if (copied) done();
                    };
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(text).then(done).catch(fallback);
                        return;
                    }
                    fallback();
                },
                startStream: function (detail) {
                    this.streamDraft = '';
                    this.activityLabel = 'Thinking';
                    var self = this;
                    var payload = detail || {};
                    fetch(this.streamUrl, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'text/event-stream',
                            'X-CSRF-TOKEN': this.csrf,
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify({
                            model: payload.model || '',
                            session_id: payload.session_id || '',
                            messages: payload.messages || []
                        })
                    }).then(function (res) {
                        if (! res.ok || ! res.body) {
                            throw new Error('stream failed');
                        }
                        var reader = res.body.getReader();
                        var decoder = new TextDecoder();
                        var carry = '';
                        function eat(chunk) {
                            carry += chunk;
                            var lines = carry.split('\n');
                            carry = lines.pop();
                            for (var i = 0; i < lines.length; i++) {
                                var line = lines[i].replace(/\r$/, '').trim();
                                if (line.indexOf('data:') !== 0) {
                                    continue;
                                }
                                var data = line.slice(5).trim();
                                if (! data || data === '[DONE]') {
                                    continue;
                                }
                                var json;
                                try {
                                    json = JSON.parse(data);
                                } catch (ignore) {
                                    continue;
                                }
                                if (json && json.error && json.error.message) {
                                    throw new Error(json.error.message);
                                }
                                if (json && ['Membaca data HiReach', 'Menyiapkan laporan dan preview Anda',
                                    'Memeriksa permintaan perubahan'].indexOf(json.activity) !== -1) {
                                    self.activityLabel = json.activity;
                                }
                                var choice = json && json.choices && json.choices[0] ? json.choices[0] : null;
                                var delta = choice && choice.delta ? choice.delta.content : null;
                                if (typeof delta === 'string' && delta !== '') {
                                    self.streamDraft += delta;
                                }
                            }
                        }
                        function pump() {
                            return reader.read().then(function (result) {
                                if (result.done) {
                                    eat(decoder.decode() + '\n');
                                    var raw = self.streamDraft;
                                    var live = self.wire();
                                    if (live && raw) {
                                        live.call('finishStream', raw);
                                    } else if (live) {
                                        live.call('failStream', 'Empty reply');
                                    }
                                    return;
                                }
                                eat(decoder.decode(result.value, { stream: true }));
                                self.scrollFollow();
                                return pump();
                            });
                        }
                        return pump();
                    }).catch(function (err) {
                        var live = self.wire();
                        if (live) {
                            live.call('failStream', err && err.message ? err.message : '');
                        }
                    });
                }
            };
        };
    </script>
</div>
