<div>
    <style>
        [data-ai-switch] { position: relative; display: inline-flex; width: 42px; height: 24px; padding: 3px; border: 0; border-radius: 999px; background: #d1d5db; cursor: pointer; transition: background .15s; vertical-align: middle; }
        [data-ai-switch][aria-checked="true"] { background: #4f46e5; }
        [data-ai-switch] > span { width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px #0002; transition: transform .15s; }
        [data-ai-switch][aria-checked="true"] > span { transform: translateX(18px); }
        [data-ai-switch]:focus-visible { outline: 2px solid #6366f1; outline-offset: 3px; }
        [data-ai-switch]:disabled { opacity: .5; cursor: not-allowed; }
    </style>
    <x-jet-action-section>
        <x-slot name="title">
            {{ __('AI Access') }}
        </x-slot>

        <x-slot name="description">
            {{ __('Access to each user’s records.') }}
        </x-slot>

        <x-slot name="content">
            <div class="grid grid-cols-6 gap-4">
                <div class="col-span-6">
                    <div class="flex items-center justify-between gap-3">
                        <div class="flex items-center gap-3">
                            <span class="text-sm text-gray-700 dark:text-gray-300">{{ __('Enable AI') }}</span>
                            <button id="ai-enabled" type="button" role="switch" data-ai-switch
                                aria-label="{{ __('Enable AI') }}" aria-checked="{{ $integration['enabled'] ? 'true' : 'false' }}"
                                wire:click="toggleIntegration" wire:loading.attr="disabled" wire:target="toggleIntegration">
                                <span aria-hidden="true"></span>
                            </button>
                            <span class="text-xs text-gray-500">{{ $integration['enabled'] ? __('On') : __('Off') }}</span>
                        </div>
                        <span role="status" class="rounded-full px-3 py-1 text-xs font-medium {{ $integration['enabled'] ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-600' }}">
                            {{ $integration['enabled'] ? __('Enabled') : __('Disabled') }}
                        </span>
                    </div>
                    <x-jet-input-error for="integration.enabled" class="mt-2" />

                    @if (array_key_exists('models', $connectionStatus))
                        <p role="status" class="mt-2 text-sm {{ $connectionStatus['models'] ? 'text-green-700' : 'text-red-700' }}">
                            {{ $connectionStatus['models'] ? __('Models: connected.') : __('Models: unavailable.') }}
                        </p>
                    @endif
                    @if (array_key_exists('data', $connectionStatus))
                        <p role="status" class="mt-1 text-sm {{ $connectionStatus['data'] ? 'text-green-700' : 'text-red-700' }}">
                            {{ $connectionStatus['data'] ? __('Data: connected.') : __('Data: unavailable.') }}
                        </p>
                    @endif
                </div>

                <div class="col-span-6">
                    <div class="flex items-center justify-between gap-3">
                        <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ __('Models') }}</h3>
                        <x-jet-button type="button" wire:click="createResource" wire:loading.attr="disabled">
                            {{ __('Add Model') }}
                        </x-jet-button>
                    </div>
                    @if (session()->has('resource_success'))
                        <p role="status" class="mt-3 rounded-md bg-green-50 p-3 text-sm text-green-800">{{ session('resource_success') }}</p>
                    @endif
                </div>

                <div class="col-span-6">
                    <livewire:table.ai-access-table />
                </div>
            </div>

            <div class="mt-6 flex items-center justify-end border-t border-gray-200 pt-4 dark:border-gray-600">
                <x-jet-action-message class="mr-3" on="saved">
                    {{ __('Saved.') }}
                </x-jet-action-message>
                <x-jet-action-message class="mr-3" on="tested">
                    {{ __('Connected.') }}
                </x-jet-action-message>
                <x-jet-action-message class="mr-3 text-red-600" on="failed">
                    {{ session('error') }}
                </x-jet-action-message>

                <x-jet-secondary-button type="button" wire:click="testConnection" wire:loading.attr="disabled">
                    {{ __('Test Connection') }}
                </x-jet-secondary-button>
            </div>
        </x-slot>
    </x-jet-action-section>

    <x-jet-dialog-modal wire:model="showResourceForm" maxWidth="3xl">
        <x-slot name="title">
            <div class="flex items-center justify-between gap-3">
                <h3 class="font-medium text-gray-900 dark:text-gray-100">{{ $editingResource ? __('Edit Model') : __('Add Model') }}</h3>
                <button type="button" wire:click="cancelResource" aria-label="{{ __('Close') }}" class="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
            </div>
        </x-slot>

        <x-slot name="content">
            @if ($showResourceForm)
                <div class="grid grid-cols-1 gap-4 sm:grid-cols-2"
                    wire:key="ai-resource-form-{{ $editingResource ?: 'new' }}-{{ $resourceDraft['model'] }}"
                    x-data="{
                        fields: @js($resourceDraft['fields']), lookup: @js($resourceDraft['lookup'])
                    }">
                    <div>
                        <x-jet-label for="resource-model" value="{{ __('Model') }}" />
                        <div class="relative mt-1" wire:key="ai-model-picker-{{ $editingResource ?: 'new' }}"
                            x-data="{
                                open: false, query: '', active: 0,
                                selected: @js($resourceDraft['model']), options: {{ \Illuminate\Support\Js::from($this->modelOptions) }},
                                matches() {
                                    let term = this.query.trim().toLowerCase();
                                    return Object.entries(this.options).filter(option => (option[1] + ' ' + option[0]).toLowerCase().includes(term));
                                },
                                showOptions() {
                                    this.open = true; this.query = ''; this.active = 0;
                                    this.$nextTick(() => this.$refs.search.focus());
                                },
                                choose(value, wire) {
                                    this.selected = value; this.open = false; this.query = ''; this.$refs.trigger.focus();
                                    wire.set('resourceDraft.model', value);
                                },
                                move(step) {
                                    this.active = Math.max(0, Math.min(this.matches().length - 1, this.active + step));
                                    this.$nextTick(() => this.$refs.list.querySelectorAll('[role=option]')[this.active]?.scrollIntoView({ block: 'nearest' }));
                                }
                            }" x-on:click.away="open = false">
                            <button id="resource-model" x-ref="trigger" type="button" role="combobox" aria-label="{{ __('Model') }}"
                                aria-haspopup="listbox" aria-controls="resource-model-options" aria-expanded="false" x-bind:aria-expanded="open.toString()"
                                x-on:click="open ? open = false : showOptions()" x-on:keydown.arrow-down.prevent="showOptions()"
                                class="flex w-full items-center justify-between rounded-md border border-gray-300 bg-white px-3 py-2 text-left text-sm shadow-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200">
                                <span x-text="options[selected] || @js(__('Choose a model'))">{{ $this->modelOptions[$resourceDraft['model']] ?? __('Choose a model') }}</span>
                                <x-icons.chevron-down class="h-4 w-4 text-gray-500" />
                            </button>
                            <div x-show="open" style="display: none;" class="absolute z-50 mt-1 w-full rounded-md border border-gray-300 bg-white shadow-lg dark:border-gray-600 dark:bg-gray-700">
                                <div class="p-2">
                                    <input x-ref="search" type="search" x-model="query" x-on:input="active = 0" aria-label="{{ __('Search models') }}"
                                        placeholder="{{ __('Search models') }}" aria-controls="resource-model-options"
                                        x-on:keydown.arrow-down.prevent="move(1)" x-on:keydown.arrow-up.prevent="move(-1)"
                                        x-on:keydown.enter.prevent="if (matches()[active]) choose(matches()[active][0], $wire)"
                                        x-on:keydown.escape.stop.prevent="open = false; $refs.trigger.focus()"
                                        class="block w-full rounded-md border-gray-300 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200">
                                </div>
                                <div id="resource-model-options" x-ref="list" role="listbox" aria-label="{{ __('Models') }}" style="max-height: 14rem; overflow-y: auto;">
                                    <template x-for="(option, index) in matches()" x-bind:key="option[0]">
                                        <button type="button" role="option" tabindex="-1" x-bind:aria-selected="(selected === option[0]).toString()"
                                            x-on:click="choose(option[0], $wire)" x-on:mouseenter="active = index"
                                            x-bind:class="{ 'bg-indigo-50 dark:bg-gray-800': active === index }"
                                            class="block w-full px-3 py-2 text-left text-sm hover:bg-indigo-50 dark:text-gray-200 dark:hover:bg-gray-800"
                                            x-text="option[1]"></button>
                                    </template>
                                </div>
                                <p x-show="matches().length === 0" class="px-3 py-2 text-sm text-gray-500">{{ __('No models found.') }}</p>
                            </div>
                        </div>
                        <x-jet-input-error for="resourceDraft.model" class="mt-2" />
                    </div>
                    <div>
                        <x-jet-label for="resource-label" value="{{ __('Display name') }}" />
                        <x-jet-input id="resource-label" type="text" class="mt-1 block w-full" wire:model.defer="resourceDraft.label" />
                        <x-jet-input-error for="resourceDraft.label" class="mt-2" />
                    </div>
                    <div>
                        <x-jet-label for="resource-key" value="{{ __('Resource key') }}" />
                        <x-jet-input id="resource-key" type="text" class="mt-1 block w-full" placeholder="projects" wire:model.defer="resourceDraft.key" :readonly="$editingResource !== ''" />
                        <x-jet-input-error for="resourceDraft.key" class="mt-2" />
                    </div>
                    <div>
                        <x-jet-label for="resource-owner" value="{{ __('User ownership column') }}" />
                        <select id="resource-owner" wire:model.defer="resourceDraft.owner" class="mt-1 block w-full rounded-md border-gray-300 dark:bg-gray-700">
                            <option value="">{{ __('Choose a column') }}</option>
                            @foreach ($modelColumns['owners'] as $field)
                                <option value="{{ $field }}">{{ $field }}</option>
                            @endforeach
                        </select>
                        <x-jet-input-error for="resourceDraft.owner" class="mt-2" />
                    </div>
                    <div class="sm:col-span-2">
                        <x-jet-label value="{{ __('Readable fields') }}" />
                        <div class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                            @foreach ($modelColumns['fields'] as $field => $type)
                                <label wire:key="ai-readable-field-{{ $resourceDraft['model'] }}-{{ $field }}" class="flex items-center gap-2 rounded-md border border-gray-200 bg-white p-2 text-sm dark:border-gray-600 dark:bg-gray-700">
                                    <input type="checkbox" value="{{ $field }}" wire:model.defer="resourceDraft.fields" x-model="fields"
                                        x-on:change="if (!$event.target.checked) { if (lookup === $event.target.value) { lookup = ''; $wire.set('resourceDraft.lookup', '', true); } $wire.set('resourceDraft.filters.' + $event.target.value, '', true); }"
                                        class="rounded border-gray-300 text-indigo-600">
                                    <span>{{ $field }}</span>
                                </label>
                            @endforeach
                        </div>
                        @if ($resourceDraft['model'] && $modelColumns['owners'] === [])
                            <p class="mt-2 text-sm text-red-700">{{ __('No supported user ownership column.') }}</p>
                        @endif
                        <x-jet-input-error for="resourceDraft.fields" class="mt-2" />
                        @foreach ($errors->get('resourceDraft.fields.*') as $messages)
                            @foreach ($messages as $message)<p class="mt-1 text-sm text-red-600">{{ $message }}</p>@endforeach
                        @endforeach
                    </div>
                    <div>
                        <x-jet-label for="resource-lookup" value="{{ __('Lookup field (optional)') }}" />
                        <select id="resource-lookup" wire:key="ai-resource-lookup-{{ $resourceDraft['model'] }}" wire:ignore x-model="lookup"
                            x-on:change="$wire.set('resourceDraft.lookup', $event.target.value, true)"
                            class="mt-1 block w-full rounded-md border-gray-300 dark:bg-gray-700">
                            <option value="">{{ __('List and count only') }}</option>
                            @foreach ($modelColumns['fields'] as $field => $type)
                                @if (str_starts_with($type, 'string'))
                                    <option value="{{ $field }}" x-bind:hidden="!fields.includes(@js($field))"
                                        x-bind:disabled="!fields.includes(@js($field))">{{ $field }}</option>
                                @endif
                            @endforeach
                        </select>
                        <x-jet-input-error for="resourceDraft.lookup" class="mt-2" />
                    </div>
                    <div class="sm:col-span-2">
                        <x-jet-label value="{{ __('Exact-match filters (optional)') }}" />
                        <p class="mt-1 text-xs text-gray-500">{{ __('For each selected text field, enter the values AI may filter by, separated by commas. Example: SUCCESS, FAILED.') }}</p>
                        <div class="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                            @foreach ($modelColumns['fields'] as $field => $type)
                                @if (str_starts_with($type, 'string'))
                                    <div wire:key="ai-filter-{{ $resourceDraft['model'] }}-{{ $field }}" x-show="fields.includes(@js($field))" style="display: none;">
                                        <x-jet-label for="resource-filter-{{ $field }}" value="{{ $field }}" />
                                        <x-jet-input id="resource-filter-{{ $field }}" type="text" class="mt-1 block w-full"
                                            wire:model.defer="resourceDraft.filters.{{ $field }}" placeholder="SUCCESS, FAILED" />
                                        <x-jet-input-error for="resourceDraft.filters.{{ $field }}" class="mt-2" />
                                    </div>
                                @endif
                            @endforeach
                        </div>
                        <x-jet-input-error for="resourceDraft.filters" class="mt-2" />
                    </div>
                </div>
                <p class="mt-4 text-xs text-gray-500">{{ __('Access starts disabled. Publish tool changes in MCP Hub.') }}</p>
            @endif
        </x-slot>

        <x-slot name="footer">
            <x-jet-secondary-button type="button" wire:click="cancelResource">{{ __('Cancel') }}</x-jet-secondary-button>
            <x-jet-button type="button" class="ml-2" wire:click="saveResource" wire:loading.attr="disabled">{{ __('Save Model') }}</x-jet-button>
        </x-slot>
    </x-jet-dialog-modal>

    <x-jet-confirmation-modal wire:model="confirmingResourceRemoval" maxWidth="lg">
        <x-slot name="title">{{ __('Remove Model') }}</x-slot>

        <x-slot name="content">
            <p class="text-sm text-gray-600 dark:text-gray-300">
                {{ __('Remove AI access to') }} <strong>{{ $resources[$resourceToRemove]['label'] ?? '' }}</strong>?
                {{ __('Data will be kept.') }}
            </p>
        </x-slot>

        <x-slot name="footer">
            <x-jet-secondary-button type="button" wire:click="cancelResourceRemoval">{{ __('Cancel') }}</x-jet-secondary-button>
            <x-jet-danger-button type="button" class="ml-2" wire:click="deleteResource" wire:loading.attr="disabled" wire:target="deleteResource">
                {{ __('Remove') }}
            </x-jet-danger-button>
        </x-slot>
    </x-jet-confirmation-modal>
</div>
