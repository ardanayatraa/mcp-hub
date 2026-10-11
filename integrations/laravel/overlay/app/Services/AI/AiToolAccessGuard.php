<?php

namespace App\Services\AI;

use App\Models\User;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;

class AiToolAccessGuard
{
    public static function rejectIfTokenLacksTools(Request $request): ?JsonResponse
    {
        $user = $request->user();
        if (! $user) {
            return response()->json([
                'success' => false,
                'message' => 'Unauthenticated.',
            ], 401);
        }

        $token = $user->currentAccessToken();
        if ($token && ! $user->tokenCan('mcp')) {
            return response()->json([
                'success' => false,
                'message' => 'This token cannot use AI tools.',
            ], 403);
        }

        if ($token && ($token->name ?? '') === 'mcp-ai-query'
            && (!$token->created_at || $token->created_at->lt(now()->subMinutes(2)))) {
            return response()->json([
                'success' => false,
                'message' => 'AI tool token expired.',
            ], 403);
        }

        return null;
    }

    public static function log(User $user, string $event, array $context = []): void
    {
        Log::info('ai.mcp.'.$event, array_merge([
            'user_id' => $user->getKey(),
        ], $context));
    }
}
