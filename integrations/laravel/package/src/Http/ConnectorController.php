<?php

namespace McpHub\Laravel\Http;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Validator;
use Illuminate\Validation\ValidationException;
use Illuminate\Validation\Rule;
use McpHub\Laravel\Connection;
use McpHub\Laravel\Registry;
use McpHub\Laravel\Security\Assertions;
use Throwable;

final class ConnectorController
{
    public function __construct(private Connection $connection, private Registry $registry)
    {
    }

    public function health(Request $request)
    {
        return $this->authenticated($request) ? $this->json(['status' => 'ok']) : $this->deny(401);
    }

    public function capabilities(Request $request)
    {
        if (! $this->authenticated($request)) {
            return $this->deny(401);
        }
        try {
            return $this->json($this->registry->manifest($this->connection));
        } catch (Throwable $error) {
            return $this->json(['success' => false, 'error' => ['code' => 'SCHEMA_MISMATCH',
                'message' => 'Resource configuration is invalid.']], 422);
        }
    }

    public function read(Request $request, string $resource, string $action, Assertions $assertions)
    {
        if (! $this->authenticated($request)) {
            return $this->deny(401);
        }
        try {
            $actor = $assertions->verify((string) $request->header('X-Hub-Assertion', ''));
            $definition = $this->registry->resources()[$resource] ?? null;
            if (! $definition || ! in_array($action, ['list', 'count', 'get'], true)
                || ($action === 'get' && ! $definition['lookup'])) {
                return $this->deny();
            }
            $policy = app($definition['policy']);
            if (! $policy->allows($actor, $resource, $action)) {
                return $this->deny();
            }
            $rules = [];
            if ($action === 'list') {
                $rules = ['limit' => 'sometimes|integer|min:1|max:50',
                    'cursor' => ['sometimes', 'string', 'regex:/^page_[0-9]{1,9}$/D']];
            }
            foreach ($definition['filters'] as $field => $values) {
                $rules[$field] = ['sometimes', 'string', Rule::in($values)];
            }
            if ($action === 'get') {
                $rules[$definition['lookup']] = 'required|string|min:1|max:200';
            }
            if (array_diff(array_keys($request->query()), array_keys($rules))) {
                return $this->deny();
            }
            $args = Validator::make($request->query(), $rules)->validate();
            $query = $policy->scope($definition['model']::query(), $actor);
            foreach ($definition['filters'] as $field => $values) {
                if (isset($args[$field])) {
                    $query->where($field, $args[$field]);
                }
            }
            if ($action === 'get') {
                $query->where($definition['lookup'], $args[$definition['lookup']]);
            }
            $total = (clone $query)->count();
            $offset = isset($args['cursor']) ? (int) substr($args['cursor'], 5) : 0;
            $limit = $action === 'list' ? (int) ($args['limit'] ?? 20) : 1;
            if ($action === 'count') {
                $rows = [['count' => $total, 'tenant_id' => $actor->tenant]];
            } else {
                $primary = $query->getModel()->getKeyName();
                $rows = $query->select(array_unique(array_merge([$primary], array_keys($definition['fields']))))
                    ->orderByDesc($primary)->offset($offset)->limit($limit)->get()->map(function ($model) use ($definition, $actor) {
                        $row = ['ref' => 'record_'.$model->getKey(), 'tenant_id' => $actor->tenant];
                        foreach ($definition['fields'] as $field => $type) {
                            $value = $model->getAttribute($field);
                            if ($value !== null) {
                                $value = match ($type) {
                                    'integer' => is_numeric($value) && (int) $value == $value ? (int) $value : throw new \RuntimeException(),
                                    'number' => is_numeric($value) && is_finite((float) $value) ? (float) $value : throw new \RuntimeException(),
                                    'boolean' => in_array($value, [true, false, 0, 1, '0', '1'], true) ? (bool) $value : throw new \RuntimeException(),
                                    'datetime' => \Illuminate\Support\Carbon::parse($value)->toAtomString(),
                                    default => is_scalar($value) && strlen((string) $value) <= 512 ? (string) $value : throw new \RuntimeException(),
                                };
                            }
                            $row[$field] = $value;
                        }
                        return $row;
                    })->all();
            }
            $more = $action === 'list' && $offset + count($rows) < $total;
            return $this->json(['success' => true, 'data' => $rows, 'meta' => [
                'as_of' => now('UTC')->toAtomString(), 'timezone' => 'UTC', 'scope' => 'authorized_records',
                'coverage' => $more || ($action === 'get' && $total > 1) ? 'partial' : 'complete',
                'total_count' => $total, 'has_more' => $more, 'next_cursor' => $more ? 'page_'.($offset + count($rows)) : null]]);
        } catch (ValidationException $error) {
            return $this->json(['success' => false, 'error' => ['code' => 'VALIDATION_FAILED', 'message' => 'Query is invalid.']], 422);
        } catch (Throwable $error) {
            return $this->deny();
        }
    }

    private function authenticated(Request $request): bool
    {
        $key = (string) $this->connection->get('app_token', '');
        return $this->connection->get('enabled') && strlen($key) >= 32
            && (! $this->connection->get('require_https') || $request->isSecure())
            && hash_equals($key, (string) $request->bearerToken());
    }

    private function deny(int $status = 403)
    {
        return $this->json(['success' => false, 'error' => ['code' => 'PERMISSION_DENIED', 'message' => 'Connector access denied.']], $status);
    }

    private function json(array $body, int $status = 200)
    {
        return response()->json($body, $status, ['Cache-Control' => 'no-store', 'X-Content-Type-Options' => 'nosniff']);
    }
}
