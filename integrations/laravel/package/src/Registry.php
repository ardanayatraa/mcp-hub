<?php

namespace McpHub\Laravel;

use Illuminate\Database\Eloquent\Model;
use McpHub\Laravel\Contracts\ResourcePolicy;
use InvalidArgumentException;

class Registry
{
    public function resources(): array
    {
        $out = [];
        foreach ((array) config('mcp-hub.models', []) as $key => $definition) {
            if (($definition['enabled'] ?? false) !== true || ($definition['read'] ?? false) !== true) {
                continue;
            }
            if (! preg_match('/^[a-z][a-z0-9_]{0,47}$/D', $key)
                || ! is_subclass_of($definition['model'] ?? '', Model::class)
                || ! is_subclass_of($definition['policy'] ?? '', ResourcePolicy::class)) {
                throw new InvalidArgumentException('Invalid resource registration.');
            }
            $model = new $definition['model'];
            $fields = $definition['fields'] ?? [];
            if (! is_array($fields) || $fields === [] || count($fields) > 50) {
                throw new InvalidArgumentException('Explicit resource fields are required.');
            }
            foreach ($fields as $field => $type) {
                if (! preg_match('/^[a-zA-Z][a-zA-Z0-9_]{0,62}$/D', $field)
                    || preg_match('/(?:email|phone|password|token|secret|otp|pin|cvv|cvc|card|passport|national|ssn|birth|iban|msisdn|verification|auth_code)/i', $field)
                    || str_ends_with($field, '_id') || in_array($field, ['id', 'ref', 'tenant_id', 'count'], true)
                    || in_array($field, $model->getHidden(), true)
                    || ! in_array($type, ['string', 'integer', 'number', 'boolean', 'datetime'], true)) {
                    throw new InvalidArgumentException('Resource field is not permitted.');
                }
            }
            $lookup = $definition['lookup'] ?? null;
            if ($lookup !== null && ($fields[$lookup] ?? null) !== 'string') {
                throw new InvalidArgumentException('Lookup requires a readable string field.');
            }
            foreach ($definition['filters'] ?? [] as $field => $values) {
                if (($fields[$field] ?? null) !== 'string' || ! is_array($values) || $values === [] || count($values) > 20) {
                    throw new InvalidArgumentException('Invalid resource filter.');
                }
                foreach ($values as $value) {
                    if (! is_string($value) || $value === '' || strlen($value) > 64 || preg_match('/\p{C}/u', $value)) {
                        throw new InvalidArgumentException('Invalid resource filter value.');
                    }
                }
            }
            $out[$key] = $definition + ['lookup' => null, 'filters' => []];
        }
        return $out;
    }

    public function manifest(Connection $connection): array
    {
        $appKey = (string) $connection->get('app_key');
        if (! preg_match('/^[a-z][a-z0-9_]{0,62}$/D', $appKey)) {
            throw new InvalidArgumentException('Invalid application key.');
        }
        $modules = [];
        foreach ($this->resources() as $key => $resource) {
            $outputs = ['ref' => ['type' => 'string', 'maxLength' => 80]];
            foreach ($resource['fields'] as $field => $type) {
                $outputs[$field] = in_array($type, ['string', 'datetime'], true)
                    ? ['type' => ['string', 'null'], 'maxLength' => 512] : ['type' => [$type, 'null']];
            }
            $routes = [];
            foreach (array_merge(['list', 'count'], $resource['lookup'] ? ['get'] : []) as $action) {
                $input = [];
                if ($action === 'list') {
                    $input = ['limit' => ['type' => 'integer', 'minimum' => 1, 'maximum' => 50],
                        'cursor' => ['type' => 'string', 'maxLength' => 20]];
                }
                foreach ($resource['filters'] as $field => $values) {
                    $input[$field] = ['type' => 'string', 'enum' => array_values($values)];
                }
                if ($action === 'get') {
                    $input[$resource['lookup']] = ['type' => 'string', 'minLength' => 1, 'maxLength' => 200];
                }
                $inputSchema = ['type' => 'object', 'additionalProperties' => false, 'properties' => (object) $input];
                if ($action === 'get') {
                    $inputSchema['required'] = [$resource['lookup']];
                }
                $properties = $action === 'count' ? ['count' => ['type' => 'integer']] : $outputs;
                $routes[] = ['tool_key' => $appKey.'.'.$key.'.'.$action,
                    'description' => 'Read permitted '.$key.' records.',
                    'method' => 'GET', 'path_template' => '/'.trim(config('mcp-hub.routes.prefix'), '/').'/'.$key.'/'.$action,
                    'requires_user_context' => true, 'tenant_field' => 'tenant_id', 'input_schema' => $inputSchema,
                    'output_schema' => ['type' => 'array', 'maxItems' => $action === 'list' ? 50 : 1,
                        'items' => ['type' => 'object', 'additionalProperties' => false,
                            'properties' => $properties, 'required' => array_keys($properties)]]];
            }
            $modules[] = ['key' => $key, 'name' => $resource['label'] ?? $key,
                'schema_version' => '1.0', 'supported_operations' => ['read'],
                'readable_fields' => array_merge(array_keys($outputs), ['count']), 'writable_fields' => [],
                'field_policies' => (object) [], 'max_page_size' => 50, 'read_endpoints' => $routes];
        }
        return ['contract_version' => '1.0', 'application' => $appKey, 'managed_by' => 'application',
            'manifest_version' => substr(hash('sha256', json_encode($modules, JSON_THROW_ON_ERROR)), 0, 32),
            'modules' => $modules];
    }
}
