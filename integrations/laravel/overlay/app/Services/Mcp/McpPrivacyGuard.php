<?php

namespace App\Services\Mcp;

use RuntimeException;

class McpPrivacyGuard
{
    public static function messages(array $history): void
    {
        foreach ($history as $message) {
            $text = (string) ($message['content'] ?? '');
            $text = preg_replace('/\b\d{4}-\d{2}-\d{2}(?:T[0-9:.+Z-]+)?\b/', '', $text);
            if (preg_match('/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i', $text)
                || preg_match('/(?<!\w)(?:\+?\d[ ()-]*){9,19}(?!\w)/', $text)
                || preg_match('/\b(?:sk-[a-z0-9_-]{12,}|hub_[a-z0-9_-]{12,}|(?:password|api_key|secret)\s*[:=]\s*\S+)/i', $text)) {
                throw new RuntimeException('AI Chat cannot accept personal data.');
            }
        }
    }
}
