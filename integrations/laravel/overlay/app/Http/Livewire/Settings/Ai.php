<?php

namespace App\Http\Livewire\Settings;

use App\Http\Livewire\Table\AiAccessTable;
use App\Models\AiIntegration;
use App\Services\AI\AiProviderClient;
use App\Services\Mcp\McpClient;
use App\Services\Mcp\McpResourceRegistry;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Illuminate\Validation\Rule;
use Illuminate\Validation\ValidationException;
use Livewire\Component;

class Ai extends Component
{
    protected $listeners = [
        'editAiAccessModel' => 'editResource',
        'removeAiAccessModel' => 'confirmResourceRemoval',
    ];

    public array $integration = [
        'name' => 'Hireach AI',
        'api_url' => '',
        'enabled' => true,
        'last_used_at' => null,
    ];

    public array $resources = [];

    public array $connectionStatus = [];

    public bool $showResourceForm = false;
    public bool $confirmingResourceRemoval = false;
    public string $resourceToRemove = '';
    public string $editingResource = '';
    public array $resourceDraft = ['key' => '', 'model' => '', 'label' => '', 'owner' => '', 'lookup' => '', 'fields' => []];
    public array $modelColumns = ['owners' => [], 'fields' => []];

    public function getModelOptionsProperty(): array
    {
        return McpResourceRegistry::modelOptions(userIdOnly: true);
    }

    public function createResource(): void
    {
        $this->authorizeAdmin();
        $this->resetValidation();
        $this->reset(['confirmingResourceRemoval', 'resourceToRemove']);
        $this->editingResource = '';
        $this->resourceDraft = ['key' => '', 'model' => '', 'label' => '', 'owner' => '', 'lookup' => '', 'fields' => []];
        $this->modelColumns = ['owners' => [], 'fields' => []];
        $this->showResourceForm = true;
    }

    public function cancelResource(): void
    {
        $this->authorizeAdmin();
        $this->showResourceForm = false;
        $this->resetValidation();
    }

    public function updatedResourceDraftModel(): void
    {
        $this->authorizeAdmin();
        $this->resetValidation();
        $this->resourceDraft['fields'] = [];
        $this->resourceDraft['lookup'] = '';
        $this->resourceDraft['owner'] = '';
        $this->modelColumns = ['owners' => [], 'fields' => []];
        if ($this->resourceDraft['model'] === '') { return; }
        try {
            $this->modelColumns = McpResourceRegistry::modelColumns($this->resourceDraft['model']);
            $this->resourceDraft['owner'] = in_array('user_id', $this->modelColumns['owners'], true) ? 'user_id' : '';
            if ($this->editingResource === '') {
                $this->resourceDraft['key'] = Str::snake(Str::pluralStudly(class_basename($this->resourceDraft['model'])));
                $this->resourceDraft['label'] = Str::title(str_replace('_', ' ', $this->resourceDraft['key']));
            }
        } catch (\Throwable $error) {
            $this->addError('resourceDraft.model', 'This model is unavailable or its table cannot be inspected.');
        }
    }

    public function editResource(string $key): void
    {
        $this->authorizeAdmin();
        $spec = McpResourceRegistry::resources()[$key] ?? null;
        abort_unless($spec, 404);
        $this->createResource();
        $this->editingResource = $key;
        $this->resourceDraft = ['key' => $key, 'model' => $spec['model'], 'label' => $spec['label'],
            'owner' => $spec['owner'], 'lookup' => $spec['lookup'] ?? '', 'fields' => array_keys($spec['fields'])];
        try {
            $this->modelColumns = McpResourceRegistry::modelColumns($spec['model']);
        } catch (\Throwable $error) {
            $this->addError('resourceDraft.model', 'This model is unavailable or its table cannot be inspected.');
        }
    }

    public function saveResource(): void
    {
        $this->authorizeAdmin();
        $this->validate([
            'resourceDraft.key' => ['required', 'string', 'regex:/^[a-z][a-z0-9_]{0,47}$/D'],
            'resourceDraft.model' => ['required', Rule::in(array_keys(McpResourceRegistry::modelOptions()))],
            'resourceDraft.label' => ['required', 'string', 'max:80'],
            'resourceDraft.fields' => ['required', 'array', 'min:1', 'max:40'],
            'resourceDraft.fields.*' => ['required', 'string', 'distinct'],
        ]);
        try {
            // Rebuild from trusted model/schema metadata, never from browser-supplied choices or types.
            $columns = McpResourceRegistry::modelColumns($this->resourceDraft['model']);
        } catch (\Throwable $error) {
            throw ValidationException::withMessages(['resourceDraft.model' => 'The model table is unavailable.']);
        }
        $selected = $this->resourceDraft['fields'];
        $lookups = array_keys(array_filter($columns['fields'], fn ($type, $field) => str_starts_with($type, 'string')
            && in_array($field, $selected, true), ARRAY_FILTER_USE_BOTH));
        $this->validate([
            'resourceDraft.owner' => ['required', Rule::in($columns['owners'])],
            'resourceDraft.fields.*' => [Rule::in(array_keys($columns['fields']))],
            'resourceDraft.lookup' => ['nullable', Rule::in($lookups)],
        ]);
        $key = $this->resourceDraft['key'];
        DB::transaction(function () use ($key, $columns, $selected) {
            $integration = AiIntegration::query()->latest('id')->lockForUpdate()->first();
            if (! $integration) {
                $integration = AiIntegration::create(['name' => 'Hireach AI', 'api_url' => 'mcp://telixcell',
                    'enabled' => true, 'permissions' => []]);
            }
            $permissions = $integration->permissions ?? [];
            $registrations = (array) ($permissions['_resources'] ?? []);
            $existing = McpResourceRegistry::resources($registrations);
            if (($this->editingResource !== '' && ($this->editingResource !== $key || ! isset($existing[$key])))
                || ($this->editingResource === '' && isset($existing[$key]))) {
                throw ValidationException::withMessages(['resourceDraft.key' => 'Use Edit for an existing resource. Resource keys cannot be renamed.']);
            }
            $previous = $existing[$key] ?? [];
            $sameModel = ($previous['model'] ?? '') === $this->resourceDraft['model'];
            $fields = [];
            foreach ($selected as $field) {
                $fields[$field] = $sameModel ? ($previous['fields'][$field] ?? $columns['fields'][$field]) : $columns['fields'][$field];
            }
            $spec = ['model' => $this->resourceDraft['model'], 'label' => $this->resourceDraft['label'],
                'owner' => $this->resourceDraft['owner'], 'lookup' => $this->resourceDraft['lookup'] ?: null,
                'fields' => $fields, 'ref_prefix' => $previous['ref_prefix'] ?? substr($key, 0, 23).'_',
                'filters' => $sameModel ? array_intersect_key($previous['filters'] ?? [], $fields) : []];
            if ($sameModel && isset($previous['keywords'])) { $spec['keywords'] = $previous['keywords']; }
            $registrations[$key] = $spec;
            try { McpResourceRegistry::tools($registrations); }
            catch (\InvalidArgumentException $error) {
                throw ValidationException::withMessages(['resourceDraft.key' => $error->getMessage()]);
            }
            $permissions['_resources'] = $registrations;
            $permissions[$key] = ['enabled' => false, 'read' => false, 'create' => false, 'update' => false,
                'delete' => false, 'scope' => 'current_user'];
            $integration->update(['permissions' => $permissions]);
        });
        $this->showResourceForm = false;
        $this->loadIntegration();
        $this->loadResources();
        session()->flash('resource_success', 'Model saved. Access disabled.');
    }

    public function confirmResourceRemoval(string $key): void
    {
        $this->authorizeAdmin();
        abort_unless(isset(McpResourceRegistry::resources()[$key]), 404);
        $this->showResourceForm = false;
        $this->resourceToRemove = $key;
        $this->confirmingResourceRemoval = true;
    }

    public function cancelResourceRemoval(): void
    {
        $this->authorizeAdmin();
        $this->reset(['confirmingResourceRemoval', 'resourceToRemove']);
    }

    public function deleteResource(): void
    {
        $this->authorizeAdmin();
        abort_unless($this->confirmingResourceRemoval && $this->resourceToRemove !== '', 404);
        $key = $this->resourceToRemove;
        DB::transaction(function () use ($key) {
            $integration = AiIntegration::query()->latest('id')->lockForUpdate()->first();
            abort_unless($integration, 404);
            $permissions = $integration->permissions ?? [];
            abort_unless(isset(McpResourceRegistry::resources((array) ($permissions['_resources'] ?? []))[$key]), 404);
            unset($permissions['_resources'][$key]);
            unset($permissions[$key]);
            $integration->update(['permissions' => $permissions]);
        });
        $this->reset(['confirmingResourceRemoval', 'resourceToRemove']);
        $this->showResourceForm = false;
        $this->loadResources();
        session()->flash('resource_success', 'AI access removed. Data kept.');
    }

    public function mount(): void
    {
        $this->authorizeAdmin();
        $this->loadIntegration();
        $this->loadResources();
    }

    public function hydrate(): void
    {
        $this->authorizeAdmin();
    }

    public function loadIntegration(): void
    {
        $integration = $this->currentIntegration();

        if (!$integration) {
            return;
        }

        $this->integration = [
            'name' => $integration->name,
            'api_url' => 'mcp://telixcell',
            'enabled' => (bool) $integration->enabled,
            'last_used_at' => $integration->last_used_at?->format('Y-m-d H:i:s'),
        ];
    }

    public function loadResources(): void
    {
        $this->resources = AiAccessTable::permissionResources();
        $this->emitTo('table.ai-access-table', 'refreshAiAccess');
    }

    public function toggleIntegration(): void
    {
        $this->authorizeAdmin();
        $this->resetValidation('integration.enabled');
        $this->connectionStatus = [];

        DB::transaction(function () {
            $integration = AiIntegration::query()->latest('id')->lockForUpdate()->first();
            $enabled = ! ($integration?->enabled ?? true);
            if ($enabled && config('ai.mcp.ai_provider') !== 'telixcell') {
                throw ValidationException::withMessages(['integration.enabled' => 'MCP AI provider is not configured.']);
            }
            if ($integration) {
                $integration->update(['enabled' => $enabled]);
            } else {
                AiIntegration::create(['name' => 'Hireach AI', 'api_url' => 'mcp://telixcell',
                    'enabled' => $enabled, 'permissions' => []]);
            }
        });

        $this->loadIntegration();
        app(AiProviderClient::class)->forgetCatalog();
    }

    public function testConnection(): void
    {
        $this->authorizeAdmin();
        $this->connectionStatus = [];
        $integration = $this->currentIntegration();

        if (!$integration) {
            session()->flash('error', 'AI integration is not configured.');
            $this->emit('failed');

            return;
        }

        if (!$integration->enabled) {
            session()->flash('error', 'AI integration is disabled.');
            $this->emit('failed');

            return;
        }

        try {
            if ($integration->api_url !== 'mcp://telixcell' || config('ai.mcp.ai_provider') !== 'telixcell') {
                throw new \RuntimeException('MCP AI provider is not configured.');
            }
            $this->connectionStatus = app(McpClient::class)->connectionStatus(auth()->user());
            if (in_array(false, $this->connectionStatus, true)) {
                throw new \RuntimeException('MCP connection check failed.');
            }
            $integration->update(['last_used_at' => now()]);
            $this->loadIntegration();
            app(AiProviderClient::class)->forgetCatalog();
            session()->flash('success', 'AI and data connections are working.');
            $this->emit('tested');
        } catch (\Throwable $e) {
            session()->flash(
                'error',
                'Unable to connect to AI or permitted data tools.'
            );
            $this->emit('failed');
        }
    }

    public function render()
    {
        return view('livewire.settings.ai');
    }

    private function currentIntegration(): ?AiIntegration
    {
        return AiIntegration::query()->latest('id')->first();
    }

    private function authorizeAdmin(): void
    {
        abort_unless(optional(optional(auth()->user()?->activeRoles)->role)->role_for === 'admin', 403);
    }

}
