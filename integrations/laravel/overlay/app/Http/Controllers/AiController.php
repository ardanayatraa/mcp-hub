<?php

namespace App\Http\Controllers;

use App\Services\AI\AiProviderClient;
use App\Services\AI\AiToolAccessGuard;
use App\Services\AI\AiChatOrchestrator;
use App\Services\AI\AiResourceExecutor;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Http\Response;
use Illuminate\Support\Facades\Cache;
use Symfony\Component\HttpFoundation\BinaryFileResponse;
use Symfony\Component\HttpFoundation\StreamedResponse;
use Illuminate\Validation\Rule;
use RuntimeException;
use Throwable;

class AiController extends Controller
{
    public function settings()
    {
        abort_unless(optional(optional(auth()->user()?->activeRoles)->role)->role_for === 'admin', 403);
        return view('settings.ai');
    }

    public function chat(Request $request, AiProviderClient $ai, AiChatOrchestrator $agent): JsonResponse
    {
        try {
            $allowedModels = $ai->allowedModels();
        } catch (Throwable $e) {
            return response()->json(['success' => false, 'message' => 'AI service is unavailable. Please try again later.'], 503);
        }

        $data = $request->validate([
            'model' => ['nullable', 'string', 'max:191', Rule::in($allowedModels)],
            'message' => ['required_without:messages', 'string', 'max:4000'],
            'messages' => ['required_without:message', 'array', 'min:1', 'max:40'],
            'messages.*.role' => ['required_with:messages', 'string', 'in:user,assistant'],
            'messages.*.content' => ['required_with:messages', 'string', 'max:4000'],
            'session_id' => ['nullable', 'string', 'max:191'],
            'data_route' => ['nullable', 'string', Rule::in(['mcp'])],
        ]);

        $user = $request->user();
        if (! $user) {
            return response()->json(['success' => false, 'message' => 'Unauthenticated.'], 401);
        }

        $history = $data['messages'] ?? [];
        if (! empty($data['message'])) {
            $history[] = ['role' => 'user', 'content' => $data['message']];
        }

        $metadata = [
            'end_user_id' => (string) $user->getKey(),
            'feature' => 'hireach_ai_chat',
            'session_id' => $data['session_id'] ?? ('hireach-user-'.$user->getKey()),
        ];

        try {
            $reply = $agent->complete($data['model'] ?? null, $history, $user, $metadata);

            return response()->json([
                'success' => true,
                'reply' => $reply,
            ]);
        } catch (RuntimeException $e) {
            if ($e->getMessage() === 'AI Chat cannot accept personal data.') {
                return response()->json(['success' => false, 'message' => $e->getMessage()], 422);
            }
            $status = str_contains($e->getMessage(), 'not allowed') ? 403 : 502;

            $message = $e->getMessage() === 'This month\'s AI quota is used up.'
                ? $e->getMessage()
                : ($status === 403 ? 'Model is not allowed.' : 'AI service is unavailable. Please try again later.');

            return response()->json(['success' => false, 'message' => $message], $status);
        } catch (Throwable $e) {
            return response()->json(['success' => false, 'message' => 'Unable to process AI request.'], 502);
        }
    }

    public function stream(Request $request, AiProviderClient $ai, AiChatOrchestrator $agent): StreamedResponse|JsonResponse
    {
        try {
            $allowedModels = $ai->allowedModels();
        } catch (Throwable $e) {
            return response()->json(['success' => false, 'message' => 'AI service is unavailable. Please try again later.'], 503);
        }

        $data = $request->validate([
            'model' => ['nullable', 'string', 'max:191', Rule::in($allowedModels)],
            'message' => ['required_without:messages', 'string', 'max:4000'],
            'messages' => ['required_without:message', 'array', 'min:1', 'max:40'],
            'messages.*.role' => ['required_with:messages', 'string', 'in:user,assistant'],
            'messages.*.content' => ['required_with:messages', 'string', 'max:4000'],
            'session_id' => ['nullable', 'string', 'max:191'],
            'data_route' => ['nullable', 'string', Rule::in(['mcp'])],
        ]);

        $user = $request->user();
        if (! $user) {
            return response()->json(['success' => false, 'message' => 'Unauthenticated.'], 401);
        }

        $history = $data['messages'] ?? [];
        if (! empty($data['message'])) {
            $history[] = ['role' => 'user', 'content' => $data['message']];
        }

        $metadata = [
            'end_user_id' => (string) $user->getKey(),
            'feature' => 'hireach_ai_chat',
            'session_id' => $data['session_id'] ?? ('hireach-chat-'.$user->getKey()),
        ];

        $model = $data['model'] ?? null;
        return response()->stream(function () use ($agent, $model, $history, $user, $metadata) {
            if (! app()->runningUnitTests()) {
                @ini_set('output_buffering', 'off');
                @ini_set('zlib.output_compression', false);
                while (ob_get_level() > 0) {
                    @ob_end_flush();
                }
            }

            try {
                foreach ($agent->stream($model, $history, $user, $metadata) as $chunk) {
                    echo $chunk;
                    if (ob_get_level() > 0) {
                        @ob_flush();
                    }
                    @flush();
                    if (connection_aborted()) {
                        break;
                    }
                }
            } catch (Throwable $e) {
                echo 'data: '.json_encode([
                    'error' => ['message' => 'AI service is unavailable. Please try again later.'],
                ])."\n\n";
                if (ob_get_level() > 0) {
                    @ob_flush();
                }
                @flush();
            }
        }, 200, [
            'Content-Type' => 'text/event-stream',
            'Cache-Control' => 'no-cache, no-transform',
            'X-Accel-Buffering' => 'no',
        ]);
    }

    public function tools(Request $request, AiResourceExecutor $executor): JsonResponse
    {
        if ($denied = AiToolAccessGuard::rejectIfTokenLacksTools($request)) {
            return $denied;
        }

        $index = \App\Services\Mcp\McpResourceRegistry::tools();
        $tools = [];
        foreach ($executor->toolCatalog($request->user()) as $tool) {
            $name = $tool['name'];
            $tools[] = [
                'name' => $name,
                'description' => $tool['description'],
                'inputSchema' => $tool['schema'],
                'resource' => $index[$name]['resource'] ?? null,
                'action' => $index[$name]['action'] ?? null,
            ];
        }

        return response()->json(['success' => true, 'data' => $tools]);
    }

    public function downloadReport(string $token): BinaryFileResponse
    {
        $meta = $this->reportMeta($token);
        abort_unless(is_string($meta['path'] ?? null) && is_file($meta['path']), 404);

        $response = response()->download($meta['path'], (string) ($meta['name'] ?? 'report'));
        $response->headers->set('Cache-Control', 'private, no-store, max-age=0');
        $response->headers->set('X-Content-Type-Options', 'nosniff');

        return $response;
    }

    public function previewReport(string $token): Response
    {
        $meta = $this->reportMeta($token);
        $path = $meta['preview_path'] ?? null;
        abort_unless(is_string($path) && is_file($path), 404);

        return response(file_get_contents($path), 200)
            ->header('Content-Type', 'text/html; charset=UTF-8')
            ->header('Cache-Control', 'private, no-store, max-age=0')
            ->header('X-Content-Type-Options', 'nosniff')
            ->header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; img-src data:; script-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
    }

    private function reportMeta(string $token): array
    {
        abort_unless(preg_match('/^[a-f0-9]{32}$/', $token), 404);
        $meta = Cache::get('hireach.ai.report.'.$token);
        abort_unless(is_array($meta), 404);
        abort_unless((int) ($meta['user_id'] ?? 0) === (int) auth()->id(), 404);
        $resource = $meta['resource'] ?? null;
        $executor = app(AiResourceExecutor::class);
        $signature = is_string($resource)
            ? $executor->reportAccessSignature($resource, auth()->user())
            : null;
        abort_unless(is_string($signature) && hash_equals($signature, (string) ($meta['access_signature'] ?? '')), 404);
        abort_unless(is_array($meta['record_ids'] ?? null)
            && $executor->reportRowsStillAccessible($resource, auth()->user(), $meta['record_ids'], $meta['status_filter'] ?? null), 404);

        return $meta;
    }

    public function confirm(Request $request, AiResourceExecutor $executor): JsonResponse
    {
        if ($denied = AiToolAccessGuard::rejectIfTokenLacksTools($request)) { return $denied; }
        $data = $request->validate(['proposal_ref' => ['required', 'string', 'regex:/^change_[a-p]{32}$/D']]);
        try {
            return response()->json(['success' => true, 'data' => $executor->publicResult($executor->commitProposal($data['proposal_ref'], $request->user()))]);
        } catch (Throwable $error) {
            return response()->json(['success' => false, 'message' => 'Confirmation failed. Prepare the change again.'], 403);
        }
    }

    public function query(Request $request, AiResourceExecutor $executor): JsonResponse
    {
        if ($request->exists('tool')) {
            $writeTool = \App\Services\Mcp\McpResourceRegistry::tools()[(string) $request->input('tool')] ?? null;
            if (($writeTool['phase'] ?? '') === 'prepare') {
                if ($denied = AiToolAccessGuard::rejectIfTokenLacksTools($request)) { return $denied; }
                $data = $request->validate(['arguments' => ['nullable', 'array']]);
                try {
                    return response()->json(['success' => true, 'data' => $executor->callTool($request->input('tool'), $data['arguments'] ?? [], $request->user())]);
                } catch (\Illuminate\Validation\ValidationException $error) {
                    return response()->json(['success' => false, 'message' => 'Invalid write arguments.'], 422);
                } catch (Throwable $error) {
                    return response()->json(['success' => false, 'message' => 'AI write access denied.'], 403);
                }
            }
            $data = $request->validate([
                'tool' => ['required', 'string', Rule::in(array_keys(AiResourceExecutor::readToolIndex()))],
                'arguments' => ['nullable', 'array'],
            ]);

            if ($denied = AiToolAccessGuard::rejectIfTokenLacksTools($request)) {
                return $denied;
            }

            $spec = AiResourceExecutor::readToolIndex()[$data['tool']];
            if (! in_array($spec['action'], ['list', 'get', 'count'], true)) {
                return response()->json(['success' => false, 'message' => 'AI query is unavailable or not permitted.'], 403);
            }

            $arguments = $data['arguments'] ?? [];
            if (array_diff($spec['required'], array_keys($arguments))
                || array_diff(array_keys($arguments), array_keys($spec['properties']))) {
                return response()->json(['success' => false, 'message' => 'Invalid tool arguments.'], 422);
            }

            try {
                $result = $executor->execute($spec['resource'], $spec['action'], $arguments, $request->user());
                AiToolAccessGuard::log($request->user(), 'query', [
                    'tool' => $data['tool'],
                    'resource' => $spec['resource'],
                    'action' => $spec['action'],
                ]);

                return response()->json(['success' => true, 'data' => $executor->publicResult($result)]);
            } catch (Throwable $e) {
                return response()->json(['success' => false, 'message' => 'AI query is unavailable or not permitted.'], 403);
            }
        }

        $data = $request->validate([
            'resource' => ['required', 'string', 'max:100'],
            'action' => ['required', 'string', 'max:100'],
            'arguments' => ['nullable', 'array'],
        ]);

        if ($denied = AiToolAccessGuard::rejectIfTokenLacksTools($request)) {
            return $denied;
        }

        $user = $request->user();

        if (in_array($data['action'], ['create', 'update', 'delete'], true)) {
            return response()->json([
                'success' => false,
                'message' => 'Create, update, and delete are not permitted.',
            ], 403);
        }

        try {
            $result = $executor->execute(
                $data['resource'],
                $data['action'],
                $data['arguments'] ?? [],
                $user
            );
            AiToolAccessGuard::log($user, 'query', [
                'resource' => $data['resource'],
                'action' => $data['action'],
            ]);

            return response()->json([
                'success' => true,
                'data' => $executor->publicResult($result),
            ]);
        } catch (Throwable $e) {
            return response()->json(['success' => false, 'message' => 'AI query is unavailable or not permitted.'], 403);
        }
    }

    public function export(Request $request, AiResourceExecutor $executor): JsonResponse
    {
        $data = $request->validate([
            'resource' => ['required', 'string', Rule::in(array_keys(AiResourceExecutor::resources()))],
            'format' => ['nullable', 'string', Rule::in(['xlsx', 'pdf'])],
            'status' => ['nullable', 'string', 'max:40'],
        ]);

        if ($denied = AiToolAccessGuard::rejectIfTokenLacksTools($request)) {
            return $denied;
        }

        $user = $request->user();

        try {
            $file = $executor->exportReport(
                $data['resource'],
                $data['format'] ?? 'xlsx',
                $user,
                (string) ($data['status'] ?? '')
            );
            AiToolAccessGuard::log($user, 'export', [
                'resource' => $data['resource'],
                'format' => $file['format'] ?? null,
            ]);

            return response()->json([
                'success' => true,
                'data' => $file,
            ]);
        } catch (Throwable $e) {
            return response()->json(['success' => false, 'message' => 'AI export is unavailable or not permitted.'], 403);
        }
    }
}
