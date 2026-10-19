<?php

namespace App\Services\Mcp;

use App\Models\AiIntegration;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Facades\File;
use Illuminate\Support\Facades\Gate;
use Illuminate\Support\Str;
use InvalidArgumentException;

class McpResourceRegistry
{
    public const BLOCKED_FIELDS = ['id', 'ref', 'tenant_id', 'user_id', 'msisdn', 'message_content',
        'description', 'email', 'phone', 'phone_number', 'password', 'token', 'secret', 'api_key'];

    public static function registrations(): array
    {
        return (array) (AiIntegration::query()->latest('id')->first()?->permissions['_resources'] ?? []);
    }

    public static function modelOptions(bool $userIdOnly = false): array
    {
        $models = [];
        foreach (File::allFiles(app_path('Models')) as $file) {
            if ($file->getExtension() !== 'php') { continue; }
            $relative = str_replace(['/', '\\'], '\\', $file->getRelativePathname());
            $class = 'App\\Models\\'.substr($relative, 0, -4);
            try {
                if (! is_subclass_of($class, Model::class)) { continue; }
                $reflection = new \ReflectionClass($class);
                if ($reflection->isAbstract() || realpath($reflection->getFileName()) !== $file->getRealPath()) { continue; }
                if ($userIdOnly) {
                    $model = new $class;
                    if (! $model->getConnection()->getSchemaBuilder()->hasColumn($model->getTable(), 'user_id')) { continue; }
                }
                $models[$class] = str_replace('App\\Models\\', '', $class);
            } catch (\Throwable $error) {
                // A model with unavailable dependencies or schema is not selectable.
            }
        }
        asort($models, SORT_NATURAL | SORT_FLAG_CASE);
        return $models;
    }

    public static function modelColumns(string $class): array
    {
        if (! isset(self::modelOptions()[$class])) {
            throw new InvalidArgumentException('Choose a Laravel model from the list.');
        }
        $model = new $class;
        $columns = self::columns($model);
        $casts = $model->getCasts();
        $hidden = $model->getHidden();
        $fields = [];
        $owners = [];
        $ownerNames = ['user_id', 'owner_id', 'created_by', 'created_by_id'];
        foreach (self::registrations() as $spec) {
            if (($spec['model'] ?? '') === $class) { $ownerNames[] = $spec['owner'] ?? ''; }
        }
        foreach ($columns as $field => $column) {
            $sqlType = $column['type'];
            $cast = explode(':', $casts[$field] ?? '')[0];
            $integer = preg_match('/^(?:tinyint|smallint|mediumint|int|integer|bigint)\b/', $sqlType) === 1;
            if ($integer && in_array($field, $ownerNames, true) && $field !== $model->getKeyName()) {
                $owners[] = $field;
            }
            if (! self::identifier($field) || self::blocked($field) || in_array($field, $hidden, true)
                || in_array($field, $ownerNames, true) || str_ends_with($field, '_id')
                || in_array($cast, ['array', 'json', 'object', 'collection', 'encrypted', 'hashed'], true)
                || preg_match('/(?:blob|binary|json|geometry)/', $sqlType)) { continue; }
            $fields[$field] = self::columnType($model, $field, $column);
        }
        return ['owners' => $owners, 'fields' => $fields];
    }

    private static function columns(Model $model): array
    {
        $connection = $model->getConnection();
        $table = $connection->getQueryGrammar()->wrapTable($model->getTable());
        $columns = match ($connection->getDriverName()) {
            'mysql' => $connection->select('SHOW COLUMNS FROM '.$table),
            'sqlite' => $connection->select('PRAGMA table_info('.$table.')'),
            default => throw new InvalidArgumentException('Model column discovery requires MySQL or SQLite.'),
        };
        if ($columns === []) { throw new InvalidArgumentException('The selected model has no available table.'); }
        $out = [];
        foreach ($columns as $column) {
            $field = (string) ($column->Field ?? $column->name);
            $out[$field] = [
                'type' => strtolower((string) ($column->Type ?? $column->type)),
                'nullable' => isset($column->Null) ? $column->Null === 'YES' : ! $column->notnull,
                'default' => $column->Default ?? $column->dflt_value ?? null,
                'primary' => isset($column->Key) ? $column->Key === 'PRI' : (bool) $column->pk,
            ];
        }
        return $out;
    }

    private static function columnType(Model $model, string $field, array $column): string
    {
        $sqlType = $column['type'];
        $cast = explode(':', $model->getCasts()[$field] ?? '')[0];
        if (in_array($cast, ['bool', 'boolean'], true) || str_contains($sqlType, 'bool') || $sqlType === 'tinyint(1)') { return 'boolean'; }
        if (in_array($cast, ['date', 'datetime', 'immutable_date', 'immutable_datetime'], true)
            || in_array($field, $model->getDates(), true) || preg_match('/^(?:date|datetime|timestamp)\b/', $sqlType)) { return 'datetime'; }
        if (preg_match('/^(?:tinyint|smallint|mediumint|int|integer|bigint)\b/', $sqlType)
            || in_array($cast, ['int', 'integer'], true)) { return 'integer'; }
        if (preg_match('/^(?:float|double|decimal|numeric|real)\b/', $sqlType)
            || in_array($cast, ['float', 'double', 'real', 'decimal'], true)) { return 'number'; }
        $length = preg_match('/(?:var)?char\((\d+)\)/', $sqlType, $match) ? min(2000, (int) $match[1]) : 200;
        return 'string:'.$length;
    }

    public static function resources(?array $registrations = null): array
    {
        $out = [];
        foreach ($registrations ?? self::registrations() as $key => $config) {
            // Ignore removal markers saved by earlier versions.
            if ($config === null) { continue; }
            $model = $config['model'] ?? '';
            $owner = $config['owner'] ?? '';
            $fields = $config['fields'] ?? [];
            if (! self::identifier($key) || ! is_subclass_of($model, Model::class)
                || ! self::identifier($owner) || ! is_array($fields) || $fields === []) {
                throw new InvalidArgumentException('AI resource registration is invalid.');
            }
            foreach ($fields as $field => $type) {
                if (! self::identifier($field) || $field === $owner || self::blocked($field)) {
                    throw new InvalidArgumentException('AI resource field is not approved.');
                }
                self::fieldSchema($type);
            }
            $lookup = $config['lookup'] ?? null;
            if ($lookup !== null && (in_array($lookup, ['limit', 'cursor'], true)
                || ! isset($fields[$lookup]) || ! str_starts_with($fields[$lookup], 'string'))) {
                throw new InvalidArgumentException('AI lookup must use an approved string field.');
            }
            $filters = $config['filters'] ?? [];
            foreach ($filters as $field => $values) {
                if (in_array($field, ['limit', 'cursor'], true) || ! isset($fields[$field]) || ! str_starts_with($fields[$field], 'string')
                    || ! is_array($values) || $values === [] || count($values) > 50
                    || count(array_filter($values, fn ($v) => is_string($v) && $v !== '' && strlen($v) <= 200)) !== count($values)) {
                    throw new InvalidArgumentException('AI filters require approved string enums.');
                }
            }
            $prefix = $config['ref_prefix'] ?? $key.'_';
            if (! is_string($prefix) || ! preg_match('/^[a-z][a-z0-9_]{0,23}$/D', $prefix)) {
                throw new InvalidArgumentException('AI reference prefix is invalid.');
            }
            $keywords = $config['keywords'] ?? [str_replace('_', ' ', $key), $config['label'] ?? Str::title(str_replace('_', ' ', $key))];
            if ($key === 'blast_messages') { $keywords[] = 'blast'; }
            $out[$key] = array_merge($config, ['owner' => $owner, 'fields' => $fields, 'lookup' => $lookup,
                'filters' => $filters, 'ref_prefix' => $prefix,
                'label' => $config['label'] ?? Str::title(str_replace('_', ' ', $key)),
                'keywords' => array_values(array_unique($keywords))]);
        }
        return $out;
    }

    private static function identifier($value): bool
    {
        return is_string($value) && preg_match('/^[a-z][a-z0-9_]{0,47}$/D', $value) === 1;
    }

    /** One-time and account codes: MCP Hub refuses them as write inputs, so AI writes never offer them. */
    private static function writeBlocked(string $field): bool
    {
        $words = explode('_', strtolower($field));
        $pairs = array_map(fn ($i) => $words[$i].'_'.$words[$i + 1], array_keys(array_slice($words, 0, -1)));
        return (bool) array_intersect([...$words, ...$pairs], ['otp', 'pin', 'cvv', 'cvc', 'passport', 'iban', 'dob', 'ssn',
            'verification_code', 'auth_code', 'security_code', 'card_number', 'credit_card', 'account_number', 'national_id']);
    }

    private static function blocked(string $field): bool
    {
        if (in_array($field, self::BLOCKED_FIELDS, true)) { return true; }
        foreach (['password', 'token', 'secret', 'api_key', 'authorization', 'email', 'phone', 'msisdn',
            'no_ktp', 'nik', 'npwp', 'birth', 'address', 'private_'] as $part) {
            if (str_contains($field, $part)) { return true; }
        }
        return false;
    }

    public static function fieldSchema(string $type): array
    {
        return match ($type) {
            'boolean' => ['type' => 'boolean'],
            'integer' => ['type' => 'integer'],
            'number' => ['type' => 'number'],
            'datetime' => ['type' => 'string', 'maxLength' => 64],
            'string' => ['type' => 'string', 'maxLength' => 200],
            default => self::boundedString($type),
        };
    }

    public static function writePolicy(string $key, ?array $spec = null): array
    {
        $spec ??= self::resources()[$key] ?? null;
        if (! $spec) { return []; }
        if (! array_filter(['create', 'update', 'delete'], fn ($action) => config('ai.crud.'.$action, false) === true)) { return []; }
        $policy = config('ai.crud.models.'.$spec['model'], []);
        if (! is_array($policy)) { throw new InvalidArgumentException('Write policy is invalid.'); }
        if (isset($policy['operations']) && ! is_array($policy['operations'])) { throw new InvalidArgumentException('Write operations are invalid.'); }
        if (isset($policy['authorize']) && (! is_array($policy['authorize']) || count($policy['authorize']) !== 2
            || ! method_exists(...array_values($policy['authorize'])))) { throw new InvalidArgumentException('Write authorization rule is invalid.'); }
        $model = new $spec['model'];
        // Registered fields bound access; fillable and the actual schema bound writes.
        // Optional overrides add business rules; no per-model config is required.
        $columns = self::columns($model);
        $inferred = [];
        $inputSchemas = [];
        $managed = [$model->getKeyName(), $spec['owner'], $model->getCreatedAtColumn(), $model->getUpdatedAtColumn(), 'deleted_at'];
        foreach (array_keys($spec['fields']) as $field) {
            if (! isset($columns[$field]) || in_array($field, $managed, true) || self::blocked($field) || self::writeBlocked($field)
                || in_array($field, $model->getHidden(), true) || ! $model->isFillable($field)) { continue; }
            $column = $columns[$field];
            $schema = self::fieldSchema(self::columnType($model, $field, $column));
            if (isset($schema['maxLength'])) {
                $schema['maxLength'] = min(200, $schema['maxLength'], self::fieldSchema($spec['fields'][$field])['maxLength'] ?? 200);
            }
            $required = ! $column['nullable'] && $column['default'] === null
                && ! array_key_exists($field, $model->getAttributes())
                && ! array_key_exists($field, $policy['defaults'] ?? []) && ! isset($policy['generated'][$field]);
            $rules = [$required ? 'required' : 'sometimes'];
            if ($column['nullable']) { $rules[] = 'nullable'; }
            $rules[] = match ($schema['type']) {
                'boolean' => 'boolean', 'integer' => 'integer', 'number' => 'numeric',
                default => self::columnType($model, $field, $column) === 'datetime' ? 'date' : 'string',
            };
            if (isset($schema['maxLength']) && ! in_array('date', $rules, true)) { $rules[] = 'max:'.$schema['maxLength']; }
            if (str_contains($column['type'], 'unsigned') && in_array($schema['type'], ['integer', 'number'], true)) { $rules[] = 'min:0'; }
            if ($column['nullable']) { $schema['type'] = [$schema['type'], 'null']; }
            $inferred[$field] = $rules;
            $inputSchemas[$field] = $schema;
        }
        $fields = $policy['fields'] ?? $inferred;
        if (! is_array($fields) || count($fields) > 29 || array_diff(array_keys($fields), array_keys($spec['fields']))) {
            throw new InvalidArgumentException('Write fields must be approved readable fields.');
        }
        foreach ($fields as $field => $rules) {
            if (! isset($inferred[$field]) || (! is_string($rules) && ! is_array($rules))) {
                throw new InvalidArgumentException('Write fields require fillable attributes and validation rules.');
            }
        }
        $operations = array_values(array_filter(['create', 'update', 'delete'], fn ($action) =>
            config('ai.crud.'.$action, false) === true && in_array($action, $policy['operations'] ?? ['create', 'update', 'delete'], true)
            && ($action === 'delete' || $fields !== [])));
        // Deny by default (least privilege): no write without an explicit authorize rule or a Laravel policy.
        if (! isset($policy['authorize']) && ! Gate::getPolicyFor($model)) { $operations = []; }
        if (in_array('delete', $operations, true) && ! in_array(\Illuminate\Database\Eloquent\SoftDeletes::class, class_uses_recursive($model))
            && ($policy['allow_hard_delete'] ?? config('ai.crud.allow_hard_delete', false)) !== true) {
            $operations = array_values(array_diff($operations, ['delete']));
        }
        // Explicit legacy field rules keep their existing schemas; inferred schemas include nullable types.
        return array_merge($policy, ['fields' => $fields, 'operations' => $operations,
            'input_schemas' => isset($policy['fields']) ? [] : $inputSchemas,
            'schema_hash' => hash('sha256', json_encode([$columns, $model->getFillable(), $model->getCasts(), $model->getAttributes()]))]);
    }

    public static function operationEnabled(string $key, string $action, ?array $spec = null): bool
    {
        if (in_array($action, ['read', 'list', 'get', 'count'], true)) { return config('ai.crud.read', true) === true; }
        return in_array($action, self::writePolicy($key, $spec)['operations'] ?? [], true);
    }

    private static function boundedString(string $type): array
    {
        if (! preg_match('/^string:([1-9][0-9]{0,3})$/D', $type, $match) || (int) $match[1] > 2000) {
            throw new InvalidArgumentException('AI field type is invalid.');
        }
        return ['type' => 'string', 'maxLength' => (int) $match[1]];
    }

    public static function tools(?array $registrations = null): array
    {
        $tools = [];
        foreach (self::resources($registrations) as $resource => $config) {
            $output = ['ref' => self::fieldSchema('string:64')];
            $columns = self::columns(new $config['model']);
            foreach ($config['fields'] as $field => $type) {
                $output[$field] = self::fieldSchema($type);
                if ($columns[$field]['nullable'] ?? false) { $output[$field]['type'] = [$output[$field]['type'], 'null']; }
            }
            foreach ($config['lookup'] === null ? ['list', 'count'] : ['list', 'get', 'count'] as $action) {
                if (! self::operationEnabled($resource, 'read', $config)) { continue; }
                $name = $action.'_'.($action === 'get' ? Str::singular($resource) : $resource);
                $properties = [];
                $required = [];
                if ($action !== 'get') {
                    foreach ($config['filters'] as $field => $values) {
                        $properties[$field] = ['type' => 'string', 'enum' => array_values($values)];
                    }
                }
                if ($action === 'list') {
                    $properties['limit'] = ['type' => 'integer', 'minimum' => 1, 'maximum' => 50];
                    $properties['cursor'] = self::fieldSchema('string:64');
                } elseif ($action === 'get') {
                    $properties[$config['lookup']] = self::fieldSchema($config['fields'][$config['lookup']]);
                    $required = [$config['lookup']];
                }
                $selected = $action === 'count'
                    ? ['count' => ['type' => 'integer', 'minimum' => 0, 'maximum' => 1000000000]] : $output;
                if (isset($tools[$name])) { throw new InvalidArgumentException('AI tool names must be unique.'); }
                $tools[$name] = [
                    'resource' => $resource, 'action' => $action, 'label' => $config['label'],
                    'tool_key' => 'hireach.'.$resource.'.'.$action,
                    'mcp_name' => 'hireach__'.$resource.'__'.$action,
                    'description' => ucfirst($action).' authorized '.$resource.' for the signed-in user.',
                    'path_template' => '/api/ai/v1/'.$resource.'/'.$action,
                    'input_schema' => ['type' => 'object', 'additionalProperties' => false,
                        'properties' => $properties ?: new \stdClass(), 'required' => $required],
                    'output_schema' => ['type' => 'array', 'maxItems' => $action === 'list' ? 50 : 1,
                        'items' => ['type' => 'object', 'additionalProperties' => false,
                            'properties' => $selected, 'required' => array_keys($selected)]],
                ];
            }
            $policy = self::writePolicy($resource, $config);
            foreach ($policy['operations'] ?? [] as $action) {
                $properties = [];
                $required = [];
                if ($action !== 'create') { $properties['ref'] = self::fieldSchema('string:64'); $required[] = 'ref'; }
                foreach ($action === 'delete' ? [] : $policy['fields'] as $field => $rules) {
                    $properties[$field] = $policy['input_schemas'][$field] ?? self::fieldSchema($config['fields'][$field]);
                    if (isset($properties[$field]['maxLength'])) { $properties[$field]['maxLength'] = min(200, $properties[$field]['maxLength']); }
                    $rules = is_array($rules) ? $rules : explode('|', $rules);
                    if ($action === 'create' && in_array('required', $rules, true)) { $required[] = $field; }
                }
                $name = $action.'_'.$resource;
                $tools[$name] = [
                    'resource' => $resource, 'action' => $action, 'phase' => 'prepare', 'label' => $config['label'],
                    'tool_key' => 'hireach.'.$resource.'.prepare_'.$action,
                    'mcp_name' => 'hireach__'.$resource.'__prepare_'.$action,
                    'description' => 'Prepare '.$action.' for authorized '.$resource.'. No business data changes until the user confirms in Hireach.',
                    'method' => 'POST', 'safe_query' => false,
                    'path_template' => '/api/ai/v1/'.$resource.'/prepare_'.$action,
                    'input_schema' => ['type' => 'object', 'additionalProperties' => false, 'properties' => $properties ?: new \stdClass(), 'required' => $required],
                    'output_schema' => ['type' => 'array', 'maxItems' => 1, 'items' => ['type' => 'object', 'additionalProperties' => false,
                        'properties' => ['proposal_ref' => self::fieldSchema('string:64'), 'summary' => self::fieldSchema('string:2000'),
                            'requires_confirmation' => ['type' => 'boolean']], 'required' => ['proposal_ref', 'summary', 'requires_confirmation']]],
                ];
            }
        }
        return $tools;
    }

    public static function manifest(): array
    {
        $modules = [];
        $integration = AiIntegration::query()->latest('id')->first();
        $registrations = (array) ($integration?->permissions['_resources'] ?? []);
        foreach (self::tools($registrations) as $tool) {
            // One saved snapshot defines this manifest; runtime rechecks access for every call.
            $permission = $integration?->permission($tool['resource']) ?? [];
            if (! $integration?->enabled || ! self::operationEnabled($tool['resource'], 'read')
                || empty($permission['enabled']) || empty($permission['read'])
                || (isset($tool['phase']) && empty($permission[$tool['action']]))) { continue; }
            $key = $tool['resource'];
            if (! isset($modules[$key])) {
                $modules[$key] = ['key' => $key, 'name' => $tool['label'], 'schema_version' => '1.0',
                    'supported_operations' => [], 'readable_fields' => [], 'max_page_size' => 50,
                    'field_policies' => array_fill_keys(array_diff(self::BLOCKED_FIELDS, ['ref', 'tenant_id']), 'blocked'),
                    'read_endpoints' => []];
            }
            $write = isset($tool['phase']);
            $operation = $write ? $tool['action'] : 'read';
            $modules[$key]['supported_operations'] = array_values(array_unique(array_merge($modules[$key]['supported_operations'], [$operation])));
            if ($write) {
                $modules[$key]['writable_fields'] = array_values(array_unique(array_merge(
                    $modules[$key]['writable_fields'] ?? [], array_keys((array) $tool['input_schema']['properties']))));
            } else {
                $modules[$key]['readable_fields'] = array_values(array_unique(array_merge(
                    $modules[$key]['readable_fields'], array_keys($tool['output_schema']['items']['properties']))));
            }
            $endpoint = ['tool_key' => $tool['tool_key'], 'description' => $tool['description'],
                'method' => $tool['method'] ?? 'GET', 'safe_query' => $tool['safe_query'] ?? false, 'path_template' => $tool['path_template'],
                'requires_user_context' => true, 'tenant_field' => 'tenant_id',
                'input_schema' => $tool['input_schema'], 'output_schema' => $tool['output_schema']];
            if ($write) { $endpoint['operation'] = $operation; }
            $modules[$key][$write ? 'write_endpoints' : 'read_endpoints'][] = $endpoint;
        }
        return ['contract_version' => '1.0', 'application' => 'hireach', 'managed_by' => 'application',
            'manifest_version' => substr(hash('sha256', json_encode($modules)), 0, 16), 'modules' => array_values($modules)];
    }
}
