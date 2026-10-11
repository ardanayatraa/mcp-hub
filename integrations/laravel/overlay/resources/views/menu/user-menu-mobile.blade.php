<div>
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
        Route::currentRouteName() == 'campaign' ||
        Route::currentRouteName() == 'campaign.channel' ||
        Route::currentRouteName() == 'contactValidation.index' ||
        Route::currentRouteName() == 'view.template'||
        Route::currentRouteName() == 'campaign.index' ||
        Route::currentRouteName() == 'campaignList' ||
        Route::currentRouteName() == 'campaign.show' ||
        Route::currentRouteName() == 'campaign.show.messages')
        @php $config='menu.list.side.user.campaign' @endphp
    @elseif(Route::currentRouteName() == 'contact.index' ||
        Route::currentRouteName() == 'audience.index' ||
        Route::currentRouteName() == 'audience.show' ||
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

    @if($config != '')
        @php
            $segment = request()->segment(3);
            $currentChannel = request()->route('channel') ?? request()->query('channel') ?? '';
            $currentRouteName = Route::currentRouteName();
            
            // Channel mapping
            $channelMapping = [
                'sms' => 'sms',
                'email' => 'email', 
                'waba' => 'waba',
                'wa' => 'waba',
            ];
        @endphp

        @foreach (config($config) as $menu)
            @if($menu)
                @php
                    // Check untuk channel-based URL
                    $menuChannel = '';
                    if (strpos($menu['url'], 'campaign/create/') !== false) {
                        $menuChannel = str_replace('campaign/create/', '', $menu['url']);
                    }
                    
                    // Active state logic
                    $isActive = false;
                    if (url()->full() == url($menu['url'])) {
                        $isActive = true;
                    } elseif ($currentChannel && $menuChannel) {
                        $normalizedCurrentChannel = $channelMapping[strtolower($currentChannel)] ?? strtolower($currentChannel);
                        $normalizedMenuChannel = $channelMapping[strtolower($menuChannel)] ?? strtolower($menuChannel);
                        if ($normalizedCurrentChannel == $normalizedMenuChannel) {
                            $isActive = true;
                        }
                    } elseif ($segment && $segment == strtolower($menu['title'])) {
                        $isActive = true;
                    } elseif (!$menuChannel && strpos(url()->full(), $menu['url']) !== false) {
                        $isActive = true;
                    }
                @endphp
                <x-jet-responsive-nav-link href="{{ url($menu['url']) }}" :active="$isActive">
                    {{ $menu['title'] }}
                </x-jet-responsive-nav-link>
            @endif
        @endforeach
    @endif
</div>
