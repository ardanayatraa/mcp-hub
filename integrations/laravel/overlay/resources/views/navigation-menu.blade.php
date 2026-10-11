@php
    $aiEnabled = \App\Models\AiIntegration::isEnabled();
@endphp
<nav x-data="{ open: false }"
    class="w-full bg-gray-100 lg:bg-white dark:text-white border-b border-gray-100 dark:border-gray-50/[0.06] supports-backdrop-blur:bg-gray-100/60 dark:bg-gray-800 fixed top-0 left-0 right-0 z-50">
    <!-- Primary Navigation Menu -->
    <div class="mx-auto px-4 sm:px-6 lg:px-4">
        <div class="flex justify-between h-16">
            <div class="flex">
                <!-- Logo -->
                <div class="flex-shrink-0 flex items-center">
                    <a class="navbar-brand" href="/">
                        <img class="hidden" src="{{url('/frontend/images/logo-trans.png')}}"
                            title="{{ env('APP_NAME') }}" style="width: 150px;" />
                        <img style="height:50px;" src="{{url('/assets/img/logos/logo2.svg')}}" />
                    </a>
                </div>

                <!-- Navigation Links -->
                <div class="hidden space-x-8 lg:-my-px lg:ml-10 lg:flex">
                    @php
                        $seg2=request()->segment(2);
                    @endphp

                    @if (Auth::user()->activeRole && str_contains(auth()->user()->activeRole->role->name, 'Admin'))
                        @foreach (config('menu.list.navigation.admin') as $menu)
                            <x-jet-nav-link
                                href="{{ route($menu['url']) }}"
                                :active="Str::contains(url()->current(), route($menu['url'])) || (request()->segment(2) === $menu['key'])"
                            >
                                {{ __($menu['title']) }}
                            </x-jet-nav-link>
                        @endforeach
                    @else
                        @php
                            // Route groups untuk navbar active state
                            $navRouteGroups = [
                                'dashboard.balance' => ['dashboard', 'dashboard.balance', 'dashboard.inbound', 'dashboard.outbound', 'dashboard.validation', 'payment.deposit', 'payment.topup'],
                                'campaign' => ['campaign', 'campaign.channel', 'campaign.index', 'campaign.show', 'campaign.show.messages', 'campaignList', 'template', 'show.template', 'view.template', 'contactValidation.index'],
                                'assets' => ['assets', 'contact.index', 'contact.show', 'audience.index', 'audience.show', 'resources.index'],
                                'setting' => ['setting', 'general', 'department', 'department.edit', 'notification', 'commerce'],
                                'report' => ['report'],
                                'message' => ['message'],
                                'ai.chat' => ['ai.chat'],
                                'billing' => ['billing', 'billing.index', 'billing.show', 'quotation', 'quotation.show', 'order.show', 'user.order'],
                            ];
                        @endphp
                        @foreach (config('menu.list.navigation.user') as $menu)
                            @continue($menu['url'] === 'ai.chat' && ! $aiEnabled)
                            @php
                                $isNavActive = false;
                                $currentRoute = Route::currentRouteName();
                                
                                // Check route group
                                if (isset($navRouteGroups[$menu['url']]) && in_array($currentRoute, $navRouteGroups[$menu['url']])) {
                                    $isNavActive = true;
                                }
                                // Fallback: check routeIs or URL contains
                                elseif (request()->routeIs($menu['url']) || strpos(url()->current(), $menu['url']) !== false) {
                                    $isNavActive = true;
                                }
                            @endphp
                            <x-jet-nav-link
                                href="{{ route($menu['url']) . ($menu['url'] === 'billing' ? '?sub=profile' : '') }}"
                                :active="$isNavActive">
                                {{ __($menu['title']) }}
                            </x-jet-nav-link>
                        @endforeach

                        @if (request()->routeIs('assistant') ||
                                request()->routeIs('project') ||
                                request()->routeIs('commercial') ||
                                request()->routeIs('order') ||
                                request()->routeIs('commercial.show'))
                            <x-jet-nav-link href="{{ route('project') }}" :active="request()->routeIs('project')">
                                {{ __('Project') }}
                            </x-jet-nav-link>
                            <x-jet-nav-link href="{{ route('commercial') }}" :active="request()->routeIs('commercial')">
                                {{ __('Commercial') }}
                            </x-jet-nav-link>
                            <x-jet-nav-link href="{{ route('order') }}" :active="request()->routeIs('order')">
                                {{ __('Order') }}
                            </x-jet-nav-link>
                        @elseif(false)
                            @if (@Auth::user()->role || Auth::user()->super->first())
                                @if (Auth::user()->activeRole && str_contains(auth()->user()->activeRole->role->name, 'Admin'))
                                    <x-jet-nav-link href="{{ route('admin.user') }}" :active="request()->routeIs('admin.user')">
                                        {{ __('Users') }}
                                    </x-jet-nav-link>
                                    <!--<x-jet-nav-link href="{{ route('user.billing.index') }}" :active="request()->routeIs('user.billing.index')">-->
                                    <!--    {{ __('Master Billing') }}-->
                                    <!--</x-jet-nav-link>-->
                                    <x-jet-nav-link href="{{ route('billing') }}" :active="request()->routeIs('billing')">
                                        {{ __('Billing') }}
                                    </x-jet-nav-link>
                                @endif
                            @endif

                            @if (Auth::user()->activeRole)
                                <x-jet-nav-link href="{{ route('assistant') }}" :active="request()->routeIs('assistant')">
                                    {{ __('Assistant') }}
                                </x-jet-nav-link>
                            @else
                                <x-jet-nav-link href="{{ route('client') }}" :active="request()->routeIs('client')">
                                    {{ __('Customers') }}
                                </x-jet-nav-link>
                                <x-jet-nav-link href="{{ route('template') }}" :active="request()->routeIs('template')">
                                    {{ __('Templates') }}
                                </x-jet-nav-link>
                                @if (Auth::user()->currentTeam && Auth::user()->currentTeam->user_id == Auth::user()->id)
                                    <x-jet-nav-link href="{{ route('billing') }}" :active="request()->routeIs('billing')">
                                        {{ __('Report') }}
                                    </x-jet-nav-link>
                                @endif
                            @endif

                            @if (Auth::user()->activeRole && str_contains(Auth::user()->activeRole->role->name, 'Super Admin'))
                                <x-jet-nav-link href="{{ route('settings') }}" :active="request()->routeIs('settings')">
                                    {{ __('Settings') }}
                                </x-jet-nav-link>
                            @endif
                        @endif
                    @endif
                </div>
            </div>

            <div class="hidden sm:flex sm:items-center sm:ml-6 flex-auto justify-end space-x-1 mr-6">
                <!-- Global Search -->
                @if (auth()->user()->currentTeam && auth()->user()->currentTeam->id == env('IN_HOUSE_TEAM_ID'))
                    @livewire('search.all')
                @endif

                <!-- Teams Dropdown -->
                @if (!empty(auth()->user()->listTeams) && false)
                    <div class="ml-3 relative">
                        <x-jet-dropdown align="right" width="60">
                            <x-slot name="trigger">
                                <span class="inline-flex rounded-sm">
                                    <button type="button"
                                        class="inline-flex items-center px-3 py-2 border rounded-sm text-sm leading-4 font-medium text-gray-500 dark:text-gray-300 bg-white supports-backdrop-blur:bg-white/60 dark:bg-gray-800 hover:bg-gray-50 hover:text-gray-700 focus:outline-none focus:bg-gray-50 active:bg-gray-50 transition">
                                        Team: {{ Auth::user()->currentTeam ? Auth::user()->currentTeam->name : '' }}

                                        <svg class="ml-2 -mr-0.5 h-4 w-4" xmlns="http://www.w3.org/2000/svg"
                                            viewBox="0 0 20 20" fill="currentColor">
                                            <path fill-rule="evenodd"
                                                d="M10 3a1 1 0 01.707.293l3 3a1 1 0 01-1.414 1.414L10 5.414 7.707 7.707a1 1 0 01-1.414-1.414l3-3A1 1 0 0110 3zm-3.707 9.293a1 1 0 011.414 0L10 14.586l2.293-2.293a1 1 0 011.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z"
                                                clip-rule="evenodd" />
                                        </svg>
                                    </button>
                                </span>
                            </x-slot>

                            <x-slot name="content">
                                <div class="w-60">
                                    <!-- Team Management -->
                                    <div class="block px-4 py-2 text-xs text-gray-400">
                                        {{ __('Manage Team') }}
                                    </div>

                                    @if (Auth::user()->currentTeam && Auth::user()->currentTeam->id !== 1)
                                        <!-- Team Settings -->
                                        <x-jet-dropdown-link
                                            href="{{ route('teams.show', Auth::user()->currentTeam->id) }}">
                                            {{ __('Team Settings') }}
                                        </x-jet-dropdown-link>
                                    @endif

                                    @if (@Auth::user()->isSuper->role == 'superadmin')
                                        @can('create', Laravel\Jetstream\Jetstream::newTeamModel())
                                            <x-jet-dropdown-link href="{{ route('teams.create') }}">
                                                {{ __('Create New Team') }}
                                            </x-jet-dropdown-link>
                                        @endcan
                                    @else
                                        @can('create', Laravel\Jetstream\Jetstream::newTeamModel())
                                            <x-jet-dropdown-link class="hidden" href="{{ route('teams.create') }}">
                                                {{ __('Create New Team') }}
                                            </x-jet-dropdown-link>
                                        @endcan
                                    @endif

                                    <div class="border-t border-gray-100"></div>

                                    @livewire('switch-team', ['totalTeam' => empty(auth()->user()->listTeams)])
                                </div>
                            </x-slot>
                        </x-jet-dropdown>
                    </div>
                @endif

                <!-- Notifications -->
                @livewire('notification-app', ['client_id' => Auth::user()->id], key('notification-' . Auth::user()->id))

                <!-- Dark Mode Toggle -->
                <div class="ml-3 relative">
                    <button onclick="toggleDarkMode()" 
                            class="inline-flex items-center justify-center p-2 rounded-lg bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors duration-200"
                            title="Toggle Dark Mode"
                            id="darkModeToggle">
                        <!-- Icon Moon (Dark Mode Off) -->
                        <svg id="moonIcon" xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-gray-600 dark:text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                        </svg>
                        <!-- Icon Sun (Dark Mode On) -->
                        <svg id="sunIcon" xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-yellow-500 hidden" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                        </svg>
                    </button>
                </div>

                <!-- Settings Dropdown -->
                <div class="ml-0 mr-10 relative">
                    <x-jet-dropdown align="right" width="48">
                        <x-slot name="trigger">
                            @if (Laravel\Jetstream\Jetstream::managesProfilePhotos())
                                <button
                                    class="flex text-sm border-2 border-gray-200 dark:border-gray-600 rounded-sm focus:outline-none focus:border-gray-300 dark:bg-gray-700 dark:text-white transition">
                                    <img class="h-8 w-8 rounded-sm object-cover"
                                        src="{{ Auth::user()->profile_photo_url }}" title="{{ Auth::user()->name }}" alt="{{ Auth::user()->name }}" />
                                        <small class="text-xs my-auto mx-2">{{ Auth::user()->name }}</small>
                                    @if (Auth::user()->activeRole)
                                        <span class="m-2 text-xs">{{ Auth::user()->activeRole->role->name }}</span>
                                    @endif
                                </button>
                            @else
                                <span class="inline-flex rounded-md">
                                    <button type="button"
                                        class="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-gray-500 dark:text-gray-300 bg-white dark:bg-gray-800 hover:text-gray-700 focus:outline-none transition">
                                        {{ Auth::user()->name }}

                                        <svg class="ml-2 -mr-0.5 h-4 w-4" xmlns="http://www.w3.org/2000/svg"
                                            viewBox="0 0 20 20" fill="currentColor">
                                            <path fill-rule="evenodd"
                                                d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
                                                clip-rule="evenodd" />
                                        </svg>
                                    </button>
                                </span>
                            @endif
                        </x-slot>

                        <x-slot name="content">
                            @livewire('switch-role')

                            <!-- Account Management -->
                            <div class="block px-4 py-2 text-xs text-gray-400">
                                {{ __('Manage Account') }}
                            </div>

                            <x-jet-dropdown-link href="{{ route('profile.show') }}">
                                {{ __('Profile') }}
                            </x-jet-dropdown-link>

                            @if (balance(auth()->user()) > 0 && false)
                                <x-jet-dropdown-link class="hidden" href="{{ route('payment.deposit') }}"
                                    class="flex justify-between">
                                    <span>{{ __('Balance') }}</span> <small>Rp
                                        {{ number_format(balance(auth()->user())) }}</small>
                                </x-jet-dropdown-link>
                            @endif

                            @if (false)
                                @if (auth()->user()->currentTeam &&
                                        Laravel\Jetstream\Jetstream::hasApiFeatures() &&
                                        auth()->user()->currentTeam->id != 1)
                                    <x-jet-dropdown-link href="{{ route('api-tokens.index') }}">
                                        {{ __('API Tokens') }}
                                    </x-jet-dropdown-link>
                                @endif
                            @endif

                            <div class="border-t border-gray-100"></div>

                            <!-- Authentication -->
                            <form method="POST" action="{{ route('logout') }}">
                                @csrf

                                <x-jet-dropdown-link href="{{ route('logout') }}"
                                    onclick="event.preventDefault();
                                                this.closest('form').submit();">
                                    {{ __('Log Out') }}
                                </x-jet-dropdown-link>
                            </form>
                        </x-slot>
                    </x-jet-dropdown>
                </div>

                <!-- Status Dropdown -->
                <div class="ml-3 relative">
                    @livewire('agent-status')
                </div>
            </div>

            <!-- Hamburger -->
            <div class="mr-12 lg:-mr-2 flex items-center lg:hidden">
                <button @click="open = ! open"
                    class="inline-flex items-center justify-center p-2 rounded-md text-gray-400 hover:text-gray-500 hover:bg-gray-100 focus:outline-none focus:bg-gray-100 focus:text-gray-500 transition">
                    <svg class="h-6 w-6" stroke="currentColor" fill="none" viewBox="0 0 24 24">
                        <path :class="{ 'hidden': open, 'inline-flex': !open }" class="inline-flex"
                            stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M4 6h16M4 12h16M4 18h16" />
                        <path :class="{ 'hidden': !open, 'inline-flex': open }" class="hidden" stroke-linecap="round"
                            stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>
        </div>
    </div>

    <!-- Responsive Navigation Menu -->
    <div :class="{ 'block': open, 'hidden': !open }" class="hidden lg:hidden bg-gray-200 dark:bg-gray-800">
        <div class="pt-2 pb-3 space-y-1 bg-gray-300 lg:bg-white dark:bg-gray-800">
            <div class="block px-4 py-2 text-xs text-gray-400">
                {{ __('Main Menu') }}
            </div>
            @if (Auth::user()->activeRole && str_contains(auth()->user()->activeRole->role->name, 'Admin'))
                @foreach (config('menu.list.navigation.admin') as $menu)
                    <x-jet-responsive-nav-link
                        href="{{ route($menu['url']) }}"
                        :active="Str::contains(url()->current(), route($menu['url'])) || (request()->segment(2) === $menu['key'])"
                    >
                        {{ __($menu['title']) }}
                        </x-jet-responsive-nav-link>
                @endforeach
            @else
                @foreach (config('menu.list.navigation.user') as $menu)
                    @continue($menu['url'] === 'ai.chat' && ! $aiEnabled)
                    @php
                        $isNavActiveResp = false;
                        $currentRouteResp = Route::currentRouteName();
                        
                        // Check route group (reuse $navRouteGroups from above)
                        $navRouteGroupsResp = [
                            'dashboard.balance' => ['dashboard', 'dashboard.balance', 'dashboard.inbound', 'dashboard.outbound', 'dashboard.validation', 'payment.deposit', 'payment.topup'],
                            'campaign' => ['campaign', 'campaign.channel', 'campaign.index', 'campaign.show', 'campaign.show.messages', 'campaignList', 'template', 'show.template', 'view.template', 'contactValidation.index'],
                            'assets' => ['assets', 'contact.index', 'contact.show', 'audience.index', 'audience.show', 'resources.index'],
                            'setting' => ['setting', 'general', 'department', 'department.edit', 'notification', 'commerce'],
                            'report' => ['report'],
                            'message' => ['message'],
                            'ai.chat' => ['ai.chat'],
                            'billing' => ['billing', 'billing.index', 'billing.show', 'quotation', 'quotation.show', 'order.show', 'user.order'],
                        ];
                        
                        if (isset($navRouteGroupsResp[$menu['url']]) && in_array($currentRouteResp, $navRouteGroupsResp[$menu['url']])) {
                            $isNavActiveResp = true;
                        } elseif (request()->routeIs($menu['url']) || strpos(url()->current(), $menu['url']) !== false) {
                            $isNavActiveResp = true;
                        }
                    @endphp
                    <x-jet-responsive-nav-link
                        href="{{ route($menu['url']) . ($menu['url'] === 'billing' ? '?sub=profile' : '') }}"
                        :active="$isNavActiveResp">
                        {{ __($menu['title']) }}
                    </x-jet-responsive-nav-link>
                @endforeach
            @endif
        </div>

        <!-- Responsive Settings Options -->
        <div class="pt-1 pb-1 border-t border-gray-200 dark:border-gray-700">
            <div class="bg-gray-300 lg:bg-white dark:bg-gray-800">
                @if (Auth::user()->currentTeam)
                    <div class="hidden">
                        <!-- Team Management -->
                        <div class="block px-4 py-2 text-xs text-gray-400">
                            {{ __('Manage Team') }}
                        </div>

                        <!-- Team Settings -->
                        <x-jet-responsive-nav-link href="{{ route('teams.show', Auth::user()->currentTeam->id) }}"
                            :active="request()->routeIs('teams.show')">
                            {{ __('Team Settings') }}
                        </x-jet-responsive-nav-link>

                        @if (auth()->user()->super->first() && auth()->user()->super->first()->role == 'member')
                            @can('create', Laravel\Jetstream\Jetstream::newTeamModel())
                                <x-jet-responsive-nav-link href="{{ route('teams.create') }}" :active="request()->routeIs('teams.create')">
                                    {{ __('Create New Team') }}
                                </x-jet-responsive-nav-link>
                            @endcan
                        @endif

                        <div class="border-t border-gray-200"></div>

                        <!-- Team Switcher -->
                        <div class="block px-4 py-2 text-xs text-gray-400">
                            {{ __('Switch Teams') }}
                        </div>

                        @foreach (Auth::user()->allTeams() as $team)
                            <x-jet-switchable-team :team="$team" component="jet-responsive-nav-link" />
                        @endforeach
                    </div>
                @endif


                <!-- Side Menu Responsive -->
                <div class="block px-4 py-2 text-xs text-gray-400">
                    {{ __('Side Menu') }}
                </div>
                @if (Auth::user()->activeRole && str_contains(auth()->user()->activeRole->role->name, 'Admin'))
                    @includeWhen(auth()->user(), 'menu.admin-menu-mobile')
                @else
                    @includeWhen(auth()->user(), 'menu.user-menu-mobile')
                @endif

                <div class="border-t border-gray-200 my-4"></div>

                <div class="hidden lg:flex items-center px-4">
                    @if (Laravel\Jetstream\Jetstream::managesProfilePhotos())
                        <div class="flex-shrink-0 mr-3">
                            <img class="h-10 w-10 rounded-full object-cover"
                                src="{{ Auth::user()->profile_photo_url }}" alt="{{ Auth::user()->name }}" />
                        </div>
                    @endif

                    <div>
                        <div class="font-medium text-base text-gray-800 dark:text-white">{{ Auth::user()->name }}</div>
                        <div class="font-medium text-sm text-gray-500 dark:text-gray-300">{{ Auth::user()->email }}</div>
                    </div>
                </div>
                
                <!-- Dark Mode Toggle for Mobile -->
                <div class="px-4 py-2">
                    <button onclick="toggleDarkMode()" 
                            class="flex items-center w-full px-3 py-2 rounded-lg bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors duration-200">
                        <!-- Icon Moon (Dark Mode Off) -->
                        <svg id="moonIconMobile" xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-gray-600 dark:text-gray-300 mr-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                        </svg>
                        <!-- Icon Sun (Dark Mode On) -->
                        <svg id="sunIconMobile" xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-yellow-500 mr-3 hidden" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                        </svg>
                        <span class="text-sm font-medium text-gray-700 dark:text-gray-300" id="darkModeTextMobile">
                            Enable Dark Mode
                        </span>
                    </button>
                </div>

                <!-- Account Management -->
                <x-jet-responsive-nav-link href="{{ route('profile.show') }}" :active="request()->routeIs('profile.show')">
                    {{ __('Profile') }}
                </x-jet-responsive-nav-link>

                <!-- Authentication -->
                <form method="POST" action="{{ route('logout') }}">
                    @csrf
                    <x-jet-responsive-nav-link href="{{ route('logout') }}"
                        onclick="event.preventDefault();
                                    this.closest('form').submit();">
                        {{ __('Log Out') }}
                    </x-jet-responsive-nav-link>
                </form>
            </div>
        </div>
    </div>

</nav>
