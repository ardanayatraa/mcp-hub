<?php

namespace App\Http\Controllers;

use App\Services\AI\AiResourceExecutor;
use App\Services\Mcp\McpResourceRegistry;
use App\Services\Mcp\McpActorIdentity;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;
use Throwable;

class McpConnectorController extends Controller
{
    private function authenticated(Request $request): bool
    {
        $key = (string) config('ai.mcp.hub.source_key');
        return (bool) config('ai.mcp.hub.enabled') && strlen($key) >= 32
            && hash_equals($key, (string) $request->header('X-API-Key', ''));
    }

    private function denied(int $status = 403): JsonResponse
    {
        return response()->json(['success' => false, 'error' => ['code' => $status === 401
            ? 'UNAUTHENTICATED' : 'PERMISSION_DENIED', 'message' => 'Connector access denied.']], $status);
    }

    public function health(Request $request): JsonResponse
    {
        return $this->authenticated($request) ? response()->json(['status' => 'ok']) : $this->denied(401);
    }

    public function capabilities(Request $request): JsonResponse
    {
        return $this->authenticated($request) ? response()->json(McpResourceRegistry::manifest()) : $this->denied(401);
    }

    public function read(Request $request, string $resource, string $action, AiResourceExecutor $executor): JsonResponse
    {
        if (! $this->authenticated($request)) {
            return $this->denied(401);
        }
        try {
            $user = McpActorIdentity::verify((string) $request->header('X-Hub-Assertion', ''));
            if (! $executor->canRead($resource)) {
                return $this->denied();
            }
            $tool = collect(McpResourceRegistry::tools())->first(fn ($t) => $t['resource'] === $resource && $t['action'] === $action);
            if (! $tool || array_diff(array_keys($request->query()), array_keys((array) $tool['input_schema']['properties']))) {
                return $this->denied();
            }
            $config = McpResourceRegistry::resources()[$resource];
            $rules = [];
            foreach ((array) $tool['input_schema']['properties'] as $field => $schema) {
                $rules[$field] = match ($field) {
                    'limit' => ['sometimes', 'integer', 'min:1', 'max:50'],
                    'cursor' => ['sometimes', 'string', 'regex:/^page_[0-9]{1,5}$/D'],
                    default => $action === 'get'
                        ? ['required', 'string', 'min:1', 'max:'.$schema['maxLength']]
                        : ['sometimes', 'string', Rule::in($schema['enum'])],
                };
            }
            $arguments = $request->validate($rules);
            $query = $config['model']::query()->where($config['owner'], $user->getKey());
            foreach ($config['filters'] as $field => $values) {
                if (isset($arguments[$field])) { $query->where($field, $arguments[$field]); }
            }
            if ($action === 'get') {
                $key = $config['lookup'];
                $query->where($key, $arguments[$key]);
            }
            $total = (clone $query)->count();
            $tenant = McpActorIdentity::tenant($user);
            $limit = $action === 'list' ? (int) ($arguments['limit'] ?? 20) : 1;
            $offset = isset($arguments['cursor']) ? (int) substr($arguments['cursor'], 5) : 0;
            if ($action === 'count') {
                $rows = [['count' => $total, 'tenant_id' => $tenant]];
            } else {
                $primary = $query->getModel()->getKeyName();
                $rows = $query->select(array_merge([$primary], array_keys($config['fields'])))
                    ->orderByDesc($primary)->offset($offset)->limit($limit)->get()
                    ->map(function ($model) use ($config, $tenant) {
                        $row = ['ref' => $config['ref_prefix'].$model->getKey(), 'tenant_id' => $tenant];
                        foreach ($config['fields'] as $field => $type) {
                            $value = $model->getAttribute($field);
                            $row[$field] = self::presentValue($value, $type);
                        }
                        return $row;
                    })->all();
            }
            $more = $action === 'list' && $offset + count($rows) < $total;
            // Names/titles can repeat. GET returns the newest matching own record;
            // pagination and repeated titles must never imply complete coverage.
            $partial = $action !== 'count' && count($rows) < $total;
            return response()->json(['success' => true, 'data' => $rows, 'meta' => [
                'as_of' => now('UTC')->toIso8601String(), 'timezone' => 'UTC', 'scope' => 'authorized_records',
                'coverage' => $partial ? 'partial' : 'complete', 'total_count' => $total, 'has_more' => $more,
                'next_cursor' => $more ? 'page_'.($offset + count($rows)) : null,
            ]]);
        } catch (\Illuminate\Validation\ValidationException $e) {
            return response()->json(['success' => false, 'error' => ['code' => 'VALIDATION_FAILED', 'message' => 'Query is invalid.']], 422);
        } catch (Throwable $e) {
            return $this->denied();
        }
    }

    public function prepare(Request $request, string $resource, string $action, AiResourceExecutor $executor): JsonResponse
    {
        if (! $this->authenticated($request)) { return $this->denied(401); }
        try {
            $user = McpActorIdentity::verify((string) $request->header('X-Hub-Assertion', ''));
            if ($request->query() !== []) { return $this->denied(); }
            $proposal = $executor->prepareProposal($resource, $action, $request->json()->all(), $user);
            return response()->json(['success' => true, 'data' => [[...$proposal, 'tenant_id' => McpActorIdentity::tenant($user)]],
                'meta' => ['contains_personal_data' => false, 'coverage' => 'complete', 'requires_confirmation' => true]]);
        } catch (\Illuminate\Validation\ValidationException $error) {
            return response()->json(['success' => false, 'error' => ['code' => 'VALIDATION_FAILED', 'message' => 'Write proposal is invalid.']], 422);
        } catch (Throwable $error) { return $this->denied(); }
    }

    private static function presentValue($value, string $type)
    {
        if ($value === null) { return null; }
        if ($type === 'datetime' && $value instanceof \DateTimeInterface) { return $value->format(DATE_ATOM); }
        if ($type === 'datetime' && is_string($value)) { return \Illuminate\Support\Carbon::parse($value)->format(DATE_ATOM); }
        if ($type === 'boolean' && in_array($value, [true, false, 1, 0, '1', '0'], true)) { return (bool) $value; }
        if ($type === 'integer' && filter_var($value, FILTER_VALIDATE_INT) !== false && $value !== null) { return (int) $value; }
        if ($type === 'number' && is_numeric($value) && is_finite((float) $value)) { return (float) $value; }
        if (str_starts_with($type, 'string') && (is_scalar($value) || $value === null)) { return (string) ($value ?? ''); }
        throw new \RuntimeException('AI resource field value is invalid.');
    }
}
