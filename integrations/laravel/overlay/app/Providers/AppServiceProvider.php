<?php

namespace App\Providers;

use App\Models\Audience;
use App\Models\BlastMessage;
use App\Models\Campaign;
use App\Models\CommerceItem;
use App\Models\Company;
use App\Models\CompanyPayment;
use App\Models\Notice;
use App\Models\Permission;
use App\Models\ProductLine;
use App\Models\Provider;
use App\Models\ProviderUser;
use App\Models\RoleInvitation;
use App\Models\Setting;
use App\Models\SettingProvider;
use App\Models\User;
use App\Models\Contact;
use App\Models\ClientValidation;
use App\Models\Department;
use App\Models\Role;
use App\Models\Notification;
use App\Models\QueueMessage;
use App\Observers\CommerceItemObserver;
use App\Observers\CompanyObserver;
use App\Observers\CompanyPaymentObserver;
use App\Observers\ProductLineObserver;
use App\Observers\ProviderUserObserver;
use App\Observers\AudienceObserver;
use App\Observers\NoticeObserver;
use App\Observers\PermissionObserver;
use App\Observers\ProviderObserver;
use App\Observers\RoleObserver;
use App\Observers\SettingObserver;
use App\Observers\SettingProviderObserver;
use App\Observers\UserObserver;
use App\Http\Livewire\AI\Chat as AiChat;
use Illuminate\Support\ServiceProvider;
use Livewire\Livewire;
use App\Observers\RoleInvitationObserver;
use App\Observers\BlastObserver;
use App\Observers\CampaignObserver;
use App\Observers\ContactObserver;
use App\Observers\ClientValidationObserver;
use App\Observers\DepartmentObserver;
use App\Observers\QueueMessagesObserver;
use App\Observers\NotificationObserver;

class AppServiceProvider extends ServiceProvider
{
    /**
     * Register any application services.
     *
     * @return void
     */
    public function register()
    {
        $this->app->bind(\McpHub\Laravel\Registry::class, \App\Services\Mcp\HubPackageRegistry::class);
        $this->app->bind(\McpHub\Laravel\Connection::class, function ($app) {
            $options = array_replace($app['config']->get('mcp-hub', []), [
                'app_key' => 'hireach',
                'enabled' => $app['config']->get('ai.mcp.hub.enabled'),
                'url' => $app['config']->get('ai.mcp.hub.url'),
                'client_key' => $app['config']->get('ai.mcp.hub.token'),
                'source_url' => $app['config']->get('ai.mcp.hub.source_url'),
                'app_token' => $app['config']->get('ai.mcp.hub.source_key'),
                'delegation_secret' => $app['config']->get('ai.mcp.hub.delegation_secret'),
                'timeout' => $app['config']->get('ai.mcp.hub.timeout', 12),
            ]);
            return new \McpHub\Laravel\Connection(
                new \Illuminate\Config\Repository(['mcp-hub' => $options]),
                $app->make(\Illuminate\Contracts\Encryption\Encrypter::class)
            );
        });
    }

    /**
     * Bootstrap any application services.
     *
     * @return void
     */
    public function boot()
    {
        Audience::observe(AudienceObserver::class);
        Role::observe(RoleObserver::class);
        Permission::observe(PermissionObserver::class);
        Notice::observe(NoticeObserver::class);
        Provider::observe(ProviderObserver::class);
        ProviderUser::observe(ProviderUserObserver::class);
        SettingProvider::observe(SettingProviderObserver::class);
        Company::observe(CompanyObserver::class);
        CompanyPayment::observe(CompanyPaymentObserver::class);
        ProductLine::observe(ProductLineObserver::class);
        CommerceItem::observe(CommerceItemObserver::class);
        Setting::observe(SettingObserver::class);
        User::observe(UserObserver::class);
        RoleInvitation::observe(RoleInvitationObserver::class);
        Contact::observe(ContactObserver::class);
        ClientValidation::observe(ClientValidationObserver::class);
        Department::observe(DepartmentObserver::class);
        BlastMessage::observe(BlastObserver::class);
        Campaign::observe(CampaignObserver::class);
        Notification::observe(NotificationObserver::class);
        QueueMessage::observe(QueueMessagesObserver::class);
        Livewire::component('ai.chat', AiChat::class);
    }
}
