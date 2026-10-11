<aside id="default-sidebar"
    class="dark:text-white w-24 col-span-1 left-0 z-30 fixed overflow-y-auto bg-white dark:bg-gray-800"
    aria-label="Sidenav">
    <div class="overflow-y-auto py-2 px-1.5 h-full bg-white dark:bg-gray-800 border-r border-gray-100 dark:border-gray-50/[0.06] shadow-sm">
        <ul class="space-y-1 py-0.5">
            @php $config='' @endphp
            @if( Route::currentRouteName() == 'billing' ||
                Route::currentRouteName() == 'billing.index' ||
                Route::currentRouteName() == 'billing.show' ||
                Route::currentRouteName() == 'order.show' ||
                Route::currentRouteName() == 'quotation.show' ||
                Route::currentRouteName() == 'quotation' )
                @php $config='menu.list.side.user.billing' @endphp
            @elseif(Route::currentRouteName() == 'setting'||
                Route::currentRouteName() == 'department'||
                Route::currentRouteName() == 'notification'||
                Route::currentRouteName() == 'department.edit'||
                Route::currentRouteName() == 'general'||
                Route::currentRouteName() == 'commerce')
                @php $config='menu.list.side.user.setting' @endphp
            @elseif(Route::currentRouteName() == 'message')
                @php $config='menu.list.side.user.livechat' @endphp
            @elseif(request()->routeIs('ai.chat', 'ai.chat.show') && \App\Models\AiIntegration::isEnabled())
                @php $config='menu.list.side.user.ai' @endphp
            @elseif(str_contains(Route::currentRouteName(), 'report'))
                @php $config='menu.list.side.user.report' @endphp
            @elseif(Route::currentRouteName() == 'admin.asset')
                @php $config='menu.list.side.admin.user' @endphp
            @elseif(Route::currentRouteName() == 'template' ||
                Route::currentRouteName() == 'show.template' ||
                Route::currentRouteName() == 'show.resource' ||
                Route::currentRouteName() == 'campaign.show.messages' ||
                Route::currentRouteName() == 'campaign.channel' ||
                Route::currentRouteName() == 'campaign' ||
                Route::currentRouteName() == 'contactValidation.index' ||
                Route::currentRouteName() == 'view.template'||
                Route::currentRouteName() == 'campaign.index' ||
                Route::currentRouteName() == 'campaignList' ||
                Route::currentRouteName() == 'campaign.show')
                @php $config='menu.list.side.user.campaign' @endphp
            @elseif(Route::currentRouteName() == 'contact.index' ||
                Route::currentRouteName() == 'audience.index' ||
                Route::currentRouteName() == 'audience.show' ||
                Route::currentRouteName() == 'contact.index' ||
                Route::currentRouteName() == 'contact.show' ||
                Route::currentRouteName() == 'assets' ||
                Route::currentRouteName() == 'resources.index' )
                @php $config='menu.list.side.user.assets' @endphp
            @elseif (Route::currentRouteName() == 'dashboard' ||
                Route::currentRouteName() == 'dashboard.inbound' ||
                Route::currentRouteName() == 'dashboard.balance' ||
                Route::currentRouteName() == 'dashboard.outbound' ||
                Route::currentRouteName() == 'dashboard.validation' ||
                Route::currentRouteName() == 'payment.deposit' ||
                Route::currentRouteName() == 'payment.topup')
                @php $config='menu.list.side.user.dashboard' @endphp
            @endif
            
            @if($config!='')
                @php
                    $segment = request()->segment(3);
                    // Get channel from route param OR query param (untuk list/schedule pages)
                    $currentChannel = request()->route('channel') ?? request()->query('channel') ?? '';
                    $currentRouteName = Route::currentRouteName();
                    
                    // Channel mapping untuk matching
                    $channelMapping = [
                        'sms' => 'sms',
                        'email' => 'email', 
                        'waba' => 'waba',
                        'wa' => 'waba',
                    ];
                    
                    // Route grouping untuk menu active state
                    $routeGroups = [
                        'dashboard/inbound' => ['dashboard.inbound', 'dashboard.outbound', 'dashboard.validation'],
                        'dashboard/balance' => ['dashboard', 'dashboard.balance', 'payment.deposit', 'payment.topup'],
                        'assets/contact' => ['contact.index', 'contact.show', 'contacts.create', 'contacts.edit', 'assets', 'audience.index', 'audience.show'],
                        'assets/resources' => ['resources.index'],
                        'setting/general' => ['setting', 'general'],
                        'setting/user-commerce' => ['commerce'],
                        'setting/department' => ['department', 'department.edit'],
                    ];
                @endphp

                @foreach (config($config) as $menu)
                    @if($menu)
                        @php
                            // Check untuk channel-based URL (campaign/create/sms, campaign/create/email, etc)
                            $menuChannel = '';
                            $menuTitle = strtolower($menu['title']);
                            if (strpos($menu['url'], 'campaign/create/') !== false) {
                                $menuChannel = str_replace('campaign/create/', '', $menu['url']);
                            }
                            
                            // Active state logic
                            $isActive = false;
                            
                            // Exact URL match
                            if (url()->full() == url($menu['url'])) {
                                $isActive = true;
                            }
                            // Route group match (untuk dashboard consumption, dll)
                            elseif (isset($routeGroups[$menu['url']]) && in_array($currentRouteName, $routeGroups[$menu['url']])) {
                                $isActive = true;
                            }
                            // Channel-based match - untuk semua halaman campaign (create, list, schedule)
                            elseif ($currentChannel && $menuChannel) {
                                $normalizedCurrentChannel = $channelMapping[strtolower($currentChannel)] ?? strtolower($currentChannel);
                                $normalizedMenuChannel = $channelMapping[strtolower($menuChannel)] ?? strtolower($menuChannel);
                                if ($normalizedCurrentChannel == $normalizedMenuChannel) {
                                    $isActive = true;
                                }
                            }
                            // Segment match untuk title
                            elseif ($segment && $segment == $menuTitle) {
                                $isActive = true;
                            }
                            // URL contains check (fallback) - hanya untuk non-channel menu
                            elseif (!$menuChannel && strpos(url()->current(), $menu['url']) !== false) {
                                $isActive = true;
                            }
                        @endphp
                        <li class="mb-1">
                            <a href="{{ url($menu['url']) }}" type="button"
                                class="{{ $isActive ? 'bg-blue-50 dark:bg-blue-900/30 border-r-4 border-blue-500' : 'hover:bg-gray-50 dark:hover:bg-gray-700' }} flex flex-col items-center py-3 px-2 w-full text-base font-medium rounded-lg transition-all duration-200 group"
                                aria-controls="dropdown-pages" data-collapse-toggle="dropdown-pages">
                                <div class="flex flex-col items-center space-y-1">
                                    <span class="{{ $isActive ? 'text-blue-600 dark:text-blue-400' : 'text-gray-500 dark:text-gray-400' }} group-hover:text-gray-700 dark:group-hover:text-gray-200 transition-all duration-200">
                                        {!! $menu['icon'] !!}
                                    </span>
                                    <span class="text-center text-xs font-medium leading-tight {{ $isActive ? 'text-blue-600 dark:text-blue-400 font-semibold' : 'text-gray-600 dark:text-gray-400' }} group-hover:text-gray-700 dark:group-hover:text-gray-300 transition-colors">{{ $menu['title'] }}</span>
                                </div>
                            </a>
                        </li>
                    @endif
                @endforeach
            @endif
        </ul>
    </div>

    @include('menu.setting-menu', ['user' => auth()->user()])
</aside>
