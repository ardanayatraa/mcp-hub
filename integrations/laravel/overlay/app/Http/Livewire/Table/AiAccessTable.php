<?php

namespace App\Http\Livewire\Table;

use App\Models\AiIntegration;
use App\Services\AI\AiResourceExecutor;
use App\Services\Mcp\McpResourceRegistry;
use Illuminate\Pagination\LengthAwarePaginator;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Mediconesystems\LivewireDatatables\Column;
use Mediconesystems\LivewireDatatables\Http\Livewire\LivewireDatatable;

class AiAccessTable extends LivewireDatatable
{
    public $model = AiIntegration::class;
    public $name = 'hireach-ai-access';
    public $persistFilters = false;
    public $persistHiddenColumns = false;
    public array $resources = [];

    protected function getListeners(): array
    {
        return array_merge(parent::getListeners(), [
            'refreshAiAccess' => 'loadResources',
        ]);
    }

    public function mount(...$parameters): void
    {
        $this->authorizeAdmin();
        $this->loadResources();
        parent::mount(...$parameters);
    }

    public function hydrate(): void
    {
        $this->authorizeAdmin();
    }

    public function loadResources(): void
    {
        $this->authorizeAdmin();
        $this->resources = static::permissionResources();
        $this->resetPage();
    }

    public function editResource(string $key): void
    {
        $this->authorizeAdmin();
        $this->emitUp('editAiAccessModel', $key);
    }

    public function confirmResourceRemoval(string $key): void
    {
        $this->authorizeAdmin();
        $this->emitUp('removeAiAccessModel', $key);
    }

    public function updatedResources($value, ?string $path): void
    {
        $this->authorizeAdmin();
        $parts = explode('.', (string) $path);
        abort_unless(count($parts) === 2 && in_array($parts[1], ['read', 'create', 'update', 'delete', 'enabled'], true) && is_bool($value), 422);
        [$key, $action] = $parts;

        DB::transaction(function () use ($key, $action, $value) {
            $integration = AiIntegration::query()->latest('id')->lockForUpdate()->first();
            abort_unless($integration, 404);
            $permissions = $integration->permissions ?? [];
            $spec = McpResourceRegistry::resources((array) ($permissions['_resources'] ?? []))[$key] ?? null;
            abort_unless($spec, 404);
            abort_unless(! $value || $action === 'enabled' || McpResourceRegistry::operationEnabled($key, $action, $spec), 422);
            $current = $permissions[$key] ?? [];
            // Patch one flag from the latest row; stale table state must not overwrite other clicks.
            foreach (['read', 'create', 'update', 'delete', 'enabled'] as $flag) {
                $permissions[$key][$flag] = $action === $flag ? $value : (bool) ($current[$flag] ?? false);
            }
            $permissions[$key]['scope'] = 'current_user';
            $integration->update(['permissions' => $permissions]);
        });

        $this->resources = static::permissionResources();
        $this->emit('saved');
    }

    public static function permissionResources(): array
    {
        $stored = AiIntegration::query()->latest('id')->first()?->permissions ?? [];

        $resources = [];

        foreach (AiResourceExecutor::resources() as $key => $config) {
            $permission = $stored[$key] ?? [];

            $resources[$key] = [
                'label' => $config['label'],
                'model' => $config['model'],
                'actions' => $config['actions'],
                'owner_column' => $config['owner_column'] ?? null,
                'default_scope' => $config['default_scope'] ?? 'current_user',

                'read' => (bool) ($permission['read'] ?? false),
                'create' => (bool) ($permission['create'] ?? false),
                'update' => (bool) ($permission['update'] ?? false),
                'delete' => (bool) ($permission['delete'] ?? false),

                'scope' => 'current_user',

                'enabled' => (bool) ($permission['enabled'] ?? false),
            ];
        }
        return $resources;
    }

    public function columns()
    {
        return [
            Column::name('model')->label(__('Model'))->searchable()->defaultSort('asc'),
            Column::name('read')->label(__('Read'))->alignCenter()->unsortable(),
            Column::name('create')->label(__('Create'))->alignCenter()->unsortable(),
            Column::name('update')->label(__('Update'))->alignCenter()->unsortable(),
            Column::name('delete')->label(__('Delete'))->alignCenter()->unsortable(),

            Column::name('enabled')->label(__('Enabled'))->alignCenter()->unsortable(),
            Column::name('actions')->label(__('Actions'))->alignRight()->unsortable(),
        ];
    }

    public function updatedSearch()
    {
        $this->resetPage();
    }

    public function updatedPerPage(): void
    {
        $this->resetPage();
    }

    public function getResultsProperty()
    {
        // Registrations are config/JSON metadata, not rows in the registered business tables.
        $term = Str::lower(trim((string) $this->search));
        $items = collect($this->resources)->filter(function ($item, $key) use ($term) {
            return $term === '' || Str::contains(Str::lower($item['label'].' '.$item['model'].' '.$key), $term);
        })->sortBy(fn ($item) => $item['label'], SORT_NATURAL | SORT_FLAG_CASE, ! $this->direction);
        $perPage = (int) $this->perPage === 99999999 ? max(1, $items->count()) : max(1, min(100, (int) $this->perPage));
        $page = min(max(1, (int) $this->page), max(1, (int) ceil($items->count() / $perPage)));
        $rows = $items->slice(($page - 1) * $perPage, $perPage)->map(function ($item, $key) {
            $row = (object) ['resource_key' => $key,
                'model' => '<div>'.e($item['label']).'</div><div class="text-xs text-gray-500 dark:text-gray-300">'.e(class_basename($item['model'])).'</div>',
                'scope' => e(__('Current User')),
                'actions' => '<button type="button" wire:click="editResource(\''.e($key).'\')" class="px-2 py-1 text-sm text-indigo-700">'.e(__('Edit')).'</button>'
                    .'<button type="button" wire:click="confirmResourceRemoval(\''.e($key).'\')" class="px-2 py-1 text-sm text-red-700">'.e(__('Remove')).'</button>',
            ];
            foreach (['read', 'create', 'update', 'delete', 'enabled'] as $action) {
                $row->$action = $this->permissionCheckbox($key, $item, $action);
            }
            return $row;
        })->values();

        return new LengthAwarePaginator($rows, $items->count(), $perPage, $page, ['path' => request()->url()]);
    }

    protected function permissionCheckbox(string $key, array $item, string $action): string
    {
        $disabled = $action !== 'enabled' && ($action === 'read'
            ? ! array_intersect(['list', 'get', 'count'], array_keys($item['actions'])) : ! isset($item['actions'][$action]));
        $label = $action === 'enabled' ? $item['label'].' '.__('enabled') : __(ucfirst($action)).' '.$item['label'];

        return '<input type="checkbox" class="rounded border-gray-300 text-indigo-600 shadow-sm" aria-label="'.e($label).'"'
            .' wire:key="ai-permission-'.e($key).'-'.$action.'"'
            .' wire:model="resources.'.e($key).'.'.$action.'" wire:loading.attr="disabled" wire:target="resources.'.e($key).'.'.$action.'"'
            .($item[$action] ? ' checked' : '')
            .($disabled ? ' disabled title="'.e(__('Disabled')).'"' : '').'>';
    }

    public function builder()
    {
        // The datatable only displays registration metadata; inherited SQL actions are unavailable.
        abort(403);
    }

    public function delete($id)
    {
        // Model access can only be removed through the existing confirmation flow.
        abort(403);
    }

    private function authorizeAdmin(): void
    {
        abort_unless(optional(optional(auth()->user()?->activeRoles)->role)->role_for === 'admin', 403);
    }
}
