<?php

use App\Http\Controllers\AdminSmsController;
use App\Http\Controllers\ApiBulkSmsController;
use App\Http\Controllers\ApiViGuardController;
use App\Http\Controllers\PermissionController;
use App\Http\Controllers\UserDepartmentController;
use App\Http\Controllers\UserOrderController;
use App\Http\Controllers\UserQuotationController;
use Illuminate\Support\Facades\Route;
use App\Http\Controllers\DevhookController;
use App\Http\Controllers\WebhookController;
use App\Http\Controllers\ApiWaController;
use App\Http\Controllers\ChatController;
use App\Http\Controllers\AuthController;
use App\Http\Controllers\BillingController;
use App\Http\Controllers\CampaignController;
use App\Http\Controllers\ChannelController;
use App\Http\Controllers\UserController;
use App\Http\Controllers\RoleController;
use App\Http\Controllers\ProjectController;
use App\Http\Controllers\NotificationController;
use App\Http\Controllers\SettingController;
use App\Http\Controllers\UserBillingController;
use App\Http\Controllers\UploadController;
use App\Http\Controllers\CommercialController;
use App\Http\Controllers\CommissionController;
use App\Http\Controllers\CustomerController;
use App\Http\Controllers\ContactController;
use App\Http\Controllers\ContactValidationResultController;
use App\Http\Controllers\FlowController;
use App\Http\Controllers\InvoiceController;
use App\Http\Controllers\OrderController;
use App\Http\Controllers\PaymentController;
use App\Http\Controllers\ReportController;
use App\Http\Controllers\RoleInvitationController;
use App\Http\Controllers\TeamInvitationController;
use App\Http\Controllers\TemplateController;
use App\Http\Controllers\DashboardController;
use App\Http\Controllers\GenerateDataController;
use App\Http\Controllers\ProviderController;
use App\Http\Controllers\ResourceController;
use App\Http\Controllers\ScheduleController;
use App\Http\Controllers\TestResourceController;
use App\Http\Controllers\UserChatController;
use App\Http\Controllers\UserReportController;
use App\Models\LogChange;
use App\Models\Provider;
use App\Models\Notification;
// use App\Models\Campaign;
use Illuminate\Http\Request as HttpRequest;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Response;
use App\Http\Controllers\AiController;

/*
|--------------------------------------------------------------------------
| Web Routes
|--------------------------------------------------------------------------
|
| Here is where you can register web routes for your application. These
| routes are loaded by the RouteServiceProvider within a group which
| contains the "web" middleware group. Now create something great!
|
*/

Route::get('/', function () {
    return view('welcome');
})->name('welcome');

Route::group(['middleware' => 'web'], function () {
    // Route::get('api/documentation', '\L5Swagger\Http\Controllers\SwaggerController@api')->name('l5swagger.api');
});

Route::middleware(['auth:sanctum', 'verified'])->group(function () {
    /** ------------------------------------------
     * Admin Routes
     * --------------------------------------------
     */
    Route::prefix('admin')->middleware('admin')->group(function () {
        Route::get('/dashboard', [DashboardController::class, 'show'])->name('admin');
        Route::get('/dashboard/active-user', [DashboardController::class, 'activeUser'])->name('dashboard.active.user');
        Route::get('/dashboard/order', [DashboardController::class, 'orderSummary'])->name('dashboard.order');
        Route::get('/dashboard/provider', [DashboardController::class, 'providerSummary'])->name('dashboard.provider');
        Route::get('/dashboard/consumption', [DashboardController::class, 'consumptionSummary'])->name('dashboard.consumption');
        Route::get('/dashboard/monitoring', [DashboardController::class, 'monitoring'])->name('dashboard.monitoring');
        Route::get('/dashboard/revenue/{page?}', [DashboardController::class, 'revenueSummary'])->name('dashboard.revenue');
        //Route::get('logout', 'Backend\AuthController@logout');
        //Route::resource('change-password', 'Backend\ChangePasswordController');
        // Route::resource('users', 'Backend\UserController');
        Route::get('/autor/list', [UserController::class, 'index'])->name('admin.autor');
        Route::get('/autor/roles', [RoleController::class, 'index'])->name('role.index');
        Route::get('/autor/permission', [PermissionController::class, 'index'])->name('permission.index');
        Route::get('/autor/{user}/profile', [UserController::class, 'profile'])->name('autor.show.profile');
        Route::get('/autor/list/{user}', [UserController::class, 'show'])->name('autor.show');
        Route::get('/autor/roles/{role}', [RoleController::class, 'show'])->name('role.show');

        Route::get('/user/list', [UserController::class, 'index'])->name('admin.user');
        Route::get('/user/department', [UserController::class, 'listDepartment'])->name('admin.department');
        Route::get('/user/department/{dept}', [UserController::class, 'listDepartment'])->name('admin.department.profile');
        Route::get('/user/department/{dept}/message', [UserController::class, 'messageDepart'])->name('admin.department.message');
        Route::get('/user/department/{dept}/profile', [UserController::class, 'profileDepart'])->name('user.edit.dept.client');
        Route::get('/user/department/{dept}/log', [UserController::class, 'logDepart'])->name('admin.department.log');

        Route::get('/user/list/{user}/overview', [UserController::class, 'show'])->name('user.show');
        Route::get('/user/list/{user}/balance', [UserController::class, 'balance'])->name('user.show.balance');
        Route::get('/user/list/{user}/profile', [UserController::class, 'profile'])->name('user.show.profile');
        Route::get('/user/list/{user}/provider', [UserController::class, 'provider'])->name('user.show.provider');
        Route::get('/user/list/{user}/quotation', [UserController::class, 'quotation'])->name('user.show.quotation');
        Route::get('/user/list/{user}/campaign', [UserController::class, 'campaign'])->name('user.show.campaign');
        Route::get('/user/list/{user}/order', [UserController::class, 'order'])->name('user.show.order');
        Route::get('/user/list/{user}/client', [UserController::class, 'client'])->name('user.show.client');
        Route::get('/user/list/{user}/client/{client}', [UserController::class, 'clientUser'])->name('client.create.user');
        Route::get('/user/list/{user}/request', [UserController::class, 'request'])->name('user.show.request');
        Route::get('/user/list/{user}/dept', [UserController::class, 'department'])->name('user.show.dept');
        Route::get('/user/list/{user}/dept/{dept}', [UserController::class, 'departmentClient'])->name('user.show.dept.client');

        Route::get('/asset', [UserController::class, 'contact'])->name('admin.asset');
        Route::get('/assets/contact', [UserController::class, 'contact'])->name('admin.contact');
        Route::get('/contact/duplicate', [UserController::class, 'duplicateContact'])->name('admin.contact-duplicate');
        Route::get('/assets/contact/edit/{contact}', [UserController::class, 'contactEdit'])->name('admin.contact-edit');
        Route::get('/get/api/department', [UserController::class, 'getDepartment'])->name('admin.department.get');
        Route::get('/assets/messages', function () {
            return view('assets.message');
        });
        Route::get('/assets/templates', function () {
            return view('assets.templates');
        });
        Route::get('/assets/operators', function () {
            return view('assets.operators');
        })->name('admin.assets.operators');
        Route::get('/assets/operators/{operator}', function ($operator) {
            return view('assets.operator-detail', compact('operator'));
        })->name('admin.assets.operators.detail');
        Route::get('/assets/senders', function () {
            return view('assets.senders');
        })->name('admin.assets.senders');
        Route::get('/assets/template/{uuid}', [TemplateController::class, 'adminShow'])->name('admin.assets.template.show');

        // Sender history route for admin
        Route::get('/senders/{id}/history', function ($id) {
            $sender = App\Models\Sender::find($id);

            if (!$sender) {
                abort(404, 'Sender tidak ditemukan');
            }

            return view('assets.sender-history', ['senderId' => $id]);
        })->name('admin.sender.history');

        // Route::get('/settings/clear-cache', 'Backend\SettingController@clearCache')->name('settings.clear-cache');
        // Route::get('/settings/rebuild-cache', 'Backend\SettingController@rebuildCache')->name('settings.rebuild-cache');
        // Route::resource('settings', 'Backend\SettingController', ['only' => ['index', 'update']]);

        Route::get('/user-billing', [UserBillingController::class, 'index'])->name('user.billing.index');
        Route::get('/user-billing/generate', [UserBillingController::class, 'generate'])->name('user.billing.generate');
        Route::post('/user-billing/invoice', [UserBillingController::class, 'invoice'])->name('user.billing.create.invoice');

        Route::get('/invoice/{billing}', [UserBillingController::class, 'showInvoice'])->name('user.billing.invoice.show');
        Route::put('/invoice/{billing}', [UserBillingController::class, 'updateInvoice'])->name('user.billing.update.invoice');



        Route::get('/setting', [SettingController::class, 'index'])->name('admin.settings');
        Route::get('/setting/notif-center', [SettingController::class, 'notifCenter'])->name('admin.settings.notif');
        Route::get('/setting/log', [SettingController::class, 'logChange'])->name('settings.logChange');
        Route::get('/setting/log/export', [SettingController::class, 'logExport'])->name('settings.log.export');

        Route::get('/providers/', [ProviderController::class, 'index'])->name('admin.settings.provider');
        Route::get('/providers/prepaid', [ProviderController::class, 'index'])->name('admin.settings.provider.prepaid');
        Route::get('/providers/postpaid', [ProviderController::class, 'index'])->name('admin.settings.provider.postpaid');

        Route::get('/setting/{page}', [SettingController::class, 'show'])->name('settings.show');
        Route::get('/providers/{type}/{provider}', [ProviderController::class, 'show'])->name('admin.settings.provider.show');
        Route::get('/setting/product-line/{productLine}', [SettingController::class, 'productLineShow'])->name('settings.productLine.show');
        Route::get('/setting/commerce-item/{commerceItem}', [SettingController::class, 'commerceItemShow'])->name('settings.commerceItem.show');
        Route::get('/setting/company', [SettingController::class, 'company'])->name('settings.company');
        Route::get('/setting/company/{company}', [SettingController::class, 'companyShow'])->name('settings.company.show');

        Route::get('/flow/{model}', [FlowController::class, 'show'])->name('flow.show');

        Route::get('/order', [OrderController::class, 'index'])->name('admin.order');
        Route::get('/order/prepaid', [OrderController::class, 'prepaid'])->name('admin.order.filter.prepaid');
        Route::get('/order/postpaid', [OrderController::class, 'postpaid'])->name('admin.order.filter.postpaid');
        Route::get('/order', [OrderController::class, 'index'])->name('admin.order');
        Route::get('/order/quotation', [OrderController::class, 'quotation'])->name('admin.quotation');
        Route::get('/order/quotation/{quotation}', [OrderController::class, 'showQuotation'])->name('show.quotation');
        Route::get('/order/{type}/{order}', [OrderController::class, 'show'])->name('show.order');

        Route::get('/invoice', [InvoiceController::class, 'index'])->name('admin.invoice');
        Route::get('/order/postpaid/invoice-order/{invoice}', [InvoiceController::class, 'show'])->name('show.invoice');

        Route::get('/commission', [CommissionController::class, 'index'])->name('admin.commission');
        Route::get('/commission/{commission}', [CommissionController::class, 'show'])->name('show.commission');

        // Route::resource('reportings', 'Backend\ReportingController');
        // Route::resource('logs', 'Backend\LogController');

        Route::get('/project', [ProjectController::class, 'index'])->name('project');
        Route::get('/project/{project}', [ProjectController::class, 'show'])->name('project.show');

        Route::get('report', [ReportController::class, 'index'])->name('admin.report');
        Route::get('report/{key}', [ReportController::class, 'show'])->name('report.show');

        Route::get('/commercial', [CommercialController::class, 'index'])->name('commercial');
        Route::get('/commercial/{key}', [CommercialController::class, 'show'])->name('commercial.show');
        Route::get('/commercial/{key}/{id}', [CommercialController::class, 'template'])->name('invoice');
        Route::get('/commercial/{key}/{id}', [CommercialController::class, 'edit'])->name('commercial.edit.show');
        Route::get('/commercial/{id}/{type}/print', [CommercialController::class, 'template'])->name('commercial.print');

        Route::get('/product/commercial/syn', [CommercialController::class, 'sync'])->name('commercial.sync');
        Route::post('/product/commercial/syn', [CommercialController::class, 'syncPost'])->name('commercial.sync.post');
        Route::get('/settings/ai', [AiController::class, 'settings'])->name('admin.settings.ai');

        Route::get('/campaign', [CampaignController::class, 'adminIndex'])->name('admin.campaign');
        Route::get('/campaign/{campaign:uuid}', [CampaignController::class, 'adminShow'])->name('admin.campaign.show');
    });

    Route::middleware('admin')->group(function () {
        Route::get('/update-sms/{id}/{status}', [AdminSmsController::class, 'updateStatus'])->name('admin.update.sms.status');
        Route::get('/manual-update-sms/{id}/{status}', [AdminSmsController::class, 'manualUpdateStatus'])->name('admin.manual.sms.status');
        Route::get('/import/sms-status', [AdminSmsController::class, 'formImportStatus'])->name('admin.form.import.status');
        Route::post('/import/sms-status', [AdminSmsController::class, 'importStatus'])->name('admin.post.import.status');
    });

    /** ------------------------------------------
     * User Routes
     * --------------------------------------------
     */
    Route::middleware('user')->group(function () {
    Route::get('/dashboard', [DashboardController::class, 'index'])->name('dashboard');
    Route::get('/dashboard/balance', [DashboardController::class, 'index'])->name('dashboard.balance');

    Route::get('/ai', function () {
        return view('ai.chat');
    })->name('ai.chat');
    Route::post('/ai/stream', [AiController::class, 'stream'])->name('ai.stream');
    Route::get('/ai/report/{token}', [AiController::class, 'downloadReport'])
        ->where('token', '[a-f0-9]{32}')
        ->name('ai.report.download');
    Route::get('/ai/report/{token}/preview', [AiController::class, 'previewReport'])
        ->where('token', '[a-f0-9]{32}')
        ->name('ai.report.preview');
    Route::get('/ai/{uuid}', function (string $uuid) {
        return view('ai.chat', ['uuid' => $uuid]);
    })->whereUuid('uuid')->name('ai.chat.show');

    Route::get('/campaign/schedule', [CampaignController::class, 'index'])->name('campaign.index');
    Route::get('/campaign/{campaign}/show-msg', [CampaignController::class, 'showMessage'])->name('campaign.show.messages');
    Route::get('/campaign/{campaign}/show', [CampaignController::class, 'show'])->name('campaign.show');


    Route::get('assets/resources', [ResourceController::class, 'index'])->name('resources.index');
    Route::get('/campaign/create', [ResourceController::class, 'show'])->name('campaign');
    Route::get('/campaign/create/{channel}', [ResourceController::class, 'showByChannel'])->name('campaign.channel');

    Route::get('/contents', function () {
        return view('contents');
    })->name('contents');

    Route::get('/message', [UserChatController::class, 'index'])->name('message');
    Route::get('/client', [CustomerController::class, 'index'])->name('client');

    Route::get('/campaign/template', [TemplateController::class, 'index'])->name('template');
    Route::get('/campaign/template/helper/index', [TemplateController::class, 'templateHelper'])->name('template.helper');
    Route::get('/campaign/template/create', function () {
        return redirect()->route('template', ['page' => 'one way', 'resource' => 1]);
    })->name('create.template');
    Route::get('/campaign/template/tree/view', [TemplateController::class, 'view'])->name('view.template');
    Route::get('/campaign/template/{uuid}', [TemplateController::class, 'show'])->name('show.template');
    Route::get('/campaign/template/{template}/edit', [TemplateController::class, 'edit'])->name('edit.template');

    Route::get('/mybilling', [BillingController::class, 'index'])->name('billing.index');
    Route::get('/billing/payment', [BillingController::class, 'billing'])->name('billing');
    Route::get('/billing/payment/{billing}', [BillingController::class, 'billingShow'])->name('billing.show');
    Route::get('/billing/quotation', [UserQuotationController::class, 'quotation'])->name('quotation');
    Route::get('/billing/quotation/{quotation}', [UserQuotationController::class, 'quotationShow'])->name('quotation.show');

    Route::get('/notif-center', [NotificationController::class, 'index'])->name('notification');
    Route::get('/notif-center/{notification}', [NotificationController::class, 'show'])->name('notification.read');
    Route::get('/notif-center/read/all', [NotificationController::class, 'readAll'])->name('notification.read.all');
    
     Route::get('/notification', [NotificationController::class, 'alert'])->name('notification.alert');

    Route::get('assets/audience', [ContactController::class, 'audience'])->name('audience.index');
    Route::get('assets/audience/{audience}', [ContactController::class, 'audienceShow'])->name('audience.show');

    Route::get('/channel', [ChannelController::class, 'index'])->name('channel');
    Route::get('/channel/{channel}', [ChannelController::class, 'show'])->name('channel.show');
    //Route::get('/channel/{channel}/{resource}', [ChannelController::class, 'view'])->name('channel.view');

    Route::get('/assistant', function () {
        return view('assistant.index');
    })->name('assistant');

    Route::get('/report', [UserReportController::class,'index'])->name('report');
    Route::get('/report/export_log', [\App\Http\Controllers\ExportLogController::class,'index'])->name('report.export_log');
    Route::get('/setting/department', [UserDepartmentController::class,'userDepartment'])->name('department');

    Route::get('/setting/general', function () {
        return view('user.user-general');
    })->name('general');
    Route::get('/setting/user-commerce', function () {
        return view('user.user-commerce');
    })->name('commerce');
    Route::get('/setting', function () {
        return view('user.user-general');
    })->name('setting');
    Route::get('/setting/department/{department}', [UserDepartmentController::class,'userDepartmentshow'])->name('department.edit');
    Route::get('/campaign/list', function () {
        return view('resource.campaign-list');
    })->name('campaignList');

    Route::get('/dashboard/deposit', [PaymentController::class, 'index'])->name('payment.deposit');
    Route::get('/dashboard/topup', [PaymentController::class, 'topup'])->name('payment.topup');
    Route::get('/order', [UserOrderController::class, 'orderUser'])->name('user.order');
    Route::get('/billing/order/payment/{order}', [UserOrderController::class, 'showUserOrder'])->name('order.show');
    Route::get('/order/prepaid/{order}', [UserOrderController::class, 'showUserOrder'])->name('order.show.prepaid');
    Route::get('/order/postpaid/{order}', [UserOrderController::class, 'showUserOrder'])->name('order.show.postpaid');

    Route::get('/payment/invoice/{id}', [PaymentController::class, 'invoice'])->name('invoice.topup');
    Route::get('/payment/billing/{id}', [PaymentController::class, 'billing'])->name('payment.billing');

    Route::get('/profile-user', [App\Http\Controllers\ProfileController::class, 'index'])->name('profile');

    Route::get('/teams', function () {
        return view('teams.index');
    })->name('teams');

    Route::get('/campaign/contact/validation', [ContactController::class, 'contactValidation'])->name('contactValidation.index');
    Route::get('assets/index', [ContactController::class, 'index'])->name('assets');
    Route::get('assets/contact', [ContactController::class, 'index'])->name('contact.index');
    Route::get('assets/contact/create', [ContactController::class, 'create'])->name('contacts.create');
    Route::post('/contact', [ContactController::class, 'store'])->name('contacts.store');
    Route::get('assets/contact/{client}', [ContactController::class, 'show'])->name('contact.show');
    Route::get('/contact/request/exports', [ContactController::class, 'export'])->name('contact.export');
    Route::get('/contact/request/import', [ContactController::class, 'showFormImport'])->name('contacts.showFormImport');
    Route::post('/contact/import', [ContactController::class, 'import'])->name('contact.import');
    Route::get('assets/contact/{uuid}', [ContactController::class, 'edit'])->name('contacts.edit');
    Route::put('/contact/{uuid}', [ContactController::class, 'update'])->name('contacts.update');
    Route::delete('/contact/{uuid}', [ContactController::class, 'destroy'])->name('contacts.destroy');

    Route::get('/dashboard/inbound', [DashboardController::class, 'getInBound'])->name('dashboard.inbound');
    Route::get('/dashboard/outbound', [DashboardController::class, 'getOutBound'])->name('dashboard.outbound');
    Route::get('/dashboard/validation', [DashboardController::class, 'getValidation'])->name('dashboard.validation');

    // Sender history route for regular users
    Route::get('/senders/{id}/history', function ($id) {
        $sender = App\Models\Sender::find($id);

        if (!$sender) {
            abort(404, 'Sender tidak ditemukan');
        }

        return view('assets.sender-history', ['senderId' => $id]);
    })->name('sender.history');

    });

});

Route::get('/role-invitations/{invitation}', [RoleInvitationController::class, 'accept'])->middleware(['signed'])->name('role-invitations.accept');
Route::get('/team/invitations/{invitation}', [TeamInvitationController::class, 'accept'])->middleware(['signed'])->name('team.invitations.accept');

Route::get('/devhook', [DevhookController::class, 'index']);
Route::post('/webhook/{slug}', [ApiWaController::class, 'inbounceMessage'])->name('webhook.client');
Route::get('/endpoint', [ApiWaController::class, 'checkEndpoint'])->name('endpoint.check');

Route::get('/chat/{slug}', function ($slug) {
    return view('chat.show', ['slug' => $slug]);
});

Route::get('/chating/{slug}', [ChatController::class, 'show'])->name('chat.slug');
Route::get('/chat-me', [ChatController::class, 'chatme'])->name('chatme');
Route::get('/upload', [UploadController::class, 'index']);
Route::get('/logout', [AuthController::class, 'destroy'])->name('logout');
Route::post('/logout', [AuthController::class, 'destroy'])->name('logout');

Route::get('/security-alert', function () {
    return view('alert');
})->name('security.alert');

Route::get('/security-alert/{id}', function ($id) {
    $clean_id = rtrim($id, ')'); 
    $notif = Notification::where('notifiable_id', $clean_id)->first();
    return view('alert', ['alert' => $notif]);
})->name('security.alert');

Route::get('/download-image/{id}', function ($id) {
    $notif = Notification::where('notifiable_id', $id)->first();
    $path = $notif->data['imgUrl']; // Path to your image
    $name = $id.'.jpg'; // Downloaded file name

    $response = Http::get($path);

    return response($response->body(), 200)
        ->header('Content-Type', $response->header('Content-Type'))
        ->header('Content-Disposition', 'attachment; filename="' . $name . '"');
})->name('download.image');

// ==================================
// HELPER URL
// ==================================
Route::get('cache/{id}', function ($id) {
    if ($id == "clear") {
        \Artisan::call('cache:clear');
    }
    if ($id == "view-clear") {
        \Artisan::call('view:clear');
    }
    dd("Job is done");
})->middleware(['auth:sanctum', 'verified', 'admin']);
// ===============================


// ==================================
// CRON JOB URL
// ==================================
Route::get('queue/{id}', function ($id) {
    if ($id == "work") {
        \Artisan::call('queue:work --tries=1 --stop-when-empty --timeout=30');
    } elseif ($id == "restart") {
        \Artisan::call('queue:restart');
    }
    dd("Job is done");
})->middleware(['auth:sanctum', 'verified', 'admin']);

Route::get('/restart-service/{id}/{time}', function ($id,$time) {
    
    $contact = App\Models\Contact::where('phone_number', $id)->where('updated_at', '>=', now()->subHour($time))->first();
    if($contact){
        return $contact;
    }
    //return $msg = App\Models\BlastMessage::where('price', 0)->where('code', 200)->limit(5)->get();
    return 'success';
});

Route::get('/aiscp/{code}', function ($code) {
    $curl = curl_init();
    //$code = 'enviguard';
    $server = config('viguard.server.' . $code);
    $auth = 'Authorization: ' . $server["auth"];
    $url = $server['url']; //http://218.3.11.19:8091/
    curl_setopt_array($curl, array(
        CURLOPT_URL => $url. '/getAllDeptList',
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_ENCODING => '',
        CURLOPT_MAXREDIRS => 10,
        CURLOPT_TIMEOUT => 0,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_HTTP_VERSION => CURL_HTTP_VERSION_1_1,
        CURLOPT_CUSTOMREQUEST => 'GET',
        CURLOPT_HTTPHEADER => array(
            'Authorization: ' . $auth,
            'User-Agent: Apifox/1.0.0 (https://apifox.com)'
        ),
    ));

    $response = curl_exec($curl);

    curl_close($curl);
    dd($response);
    return 'success';
});

Route::get('campaign-schedule', [ScheduleController::class, 'index'])->middleware(['auth:sanctum', 'verified', 'admin'])->name('schedule.start');
Route::get('campaign-schedule-reset', [ScheduleController::class, 'reset'])->middleware(['auth:sanctum', 'verified', 'admin'])->name('schedule.reset');
Route::get('/import-validation', [ContactValidationResultController::class, 'importUpdateValidation'])->middleware(['auth:sanctum', 'verified', 'admin'])->name('contacts.importFromPath');
Route::get('/generate/billing', [GenerateDataController::class, 'generateBilling'])->middleware(['auth:sanctum', 'verified', 'admin']);
Route::get('/generate/data/{provider}', [GenerateDataController::class, 'view'])->middleware(['auth:sanctum', 'verified', 'admin'])->name('generate.data.api');
// ===============================

// Route::get('/saveAlarm', [ApiViGuardController::class, 'index']);
Route::post('/saveAlarm', [ApiViGuardController::class, 'post']);
Route::post('/getAllMonitoringDeviceList', [ApiViGuardController::class, 'getMonitoringDevice']);
Route::post('/getAllDeptList', [ApiViGuardController::class, 'getDeptList']);
Route::middleware(['auth:sanctum', 'user'])->post('/sent/sample', [TestResourceController::class, 'post']);

//Emergency Route
//Route::get('/setup/contact-status-history', function (HttpRequest $request) {
//    $all = App\Models\Contact::get();
//    foreach($all as $a){
//        $history = new App\Models\ContactStatusHistory;
//        $history->contact_id = $a->id;
//        $history->status_no = $a->status_no;
//        $history->status_wa = $a->status_wa;
//        $history->file_name = $a->file_name;
//        $history->save();
//    }
//});
/*Route::get('/saldo/update-bug-2025/{id}', function (HttpRequest $request, $id) {
    $all = App\Models\SaldoUser::where('user_id', $id)->where('mutation', 'debit')->get();
    $last = App\Models\SaldoUser::where('user_id', $id)->orderBy('id', 'desc')->first();
    $sms = 0;
    foreach($all as $key => $a){
        if($sms==$a->model_id){
            echo $a->amount.'<br>';
            $last->balance = $last->balance+$a->amount;
            $last->save();
            App\Models\SaldoUser::find($a->id)->delete();
        }else{
            $sms = $a->model_id;
        }
    }
    return $last;
});*/
/*
Route::get('/saldo/update/{id}', function (HttpRequest $request,$id) {
    // $all = App\Models\Contact::find($id);
    // //$all->jstatus
    // $updated = 0;
    
    // if (!$all) return;

    // Safely parse null, string JSON, or existing array
    // $channels = is_string($all->jstatus) 
    //     ? json_decode($all->jstatus, true) 
    //     : ($all->jstatus ?? []);
    // if($channels){
    //     if($channels['wa']){
    //         echo "wa active";
    //     }
    //     if($channels['sms']){
    //         echo "sms active";
    //     }
    //     if($channels['telegram']){
    //         echo "telegram active";
    //     }
    // }else{
    //     echo 'pass';
    // }
    for ($i = 0; $i < 2; $i++) {
        $campaign = Campaign::create([
            'title'         => "test duplicate",
            'channel'       => 'HR-WABA',
            'provider'      => 'PROVIDER3',
            'provider_id'   => 8,
            'from'          => 'FirmApps',
            'to'            => 'Audience:1',
            'audience_id'   => 1,
            'text'          => 0,
            'is_otp'        => 0,
            'request_type'  => 'api',
            'status'        => 'starting',
            'way_type'      => 1,
            'type'          => 0,
            'template_id'   => 5,
            'user_id'       => 1,
            'uuid'          => Str::uuid()
        ]);
    }
    
    return $campaign;
    // foreach ($all as $billingUser) {
    //     $last = App\Models\SaldoUser::where('user_id', $billingUser->user_id)
    //         ->where(function($query) {
    //             $query->whereNull('model')
    //                   ->orWhere('model', '!=', 'Provider');
    //         })
    //         ->orderBy('id', 'desc')
    //         ->first();
    //     if ($last !== null) {
    //         App\Models\BillingUser::where('id', $billingUser->id)->update([
    //             'current_balance' => $last->balance,
    //         ]);
    //         $updated++;
    //     }
    // }
    return response()->json([
        'message' => 'Balance synced from saldo_users to billing_users.',
        'updated' => $updated,
        'total' => $all->count(),
    ]);
});
*/
/**
 * Sync balance from saldo_users (audit log) to billing_users.current_balance.
 * Run once after migration that adds current_balance/credit_limit to billing_users.
 * Example: GET {APP_URL}/saldo/update
 */
Route::get('/saldo/update', function () {
    $all = App\Models\BillingUser::all();
    $updated = 0;

    foreach ($all as $billingUser) {
        $last = App\Models\SaldoUser::where('user_id', $billingUser->user_id)
            ->where(function ($query) {
                $query->whereNull('model')->orWhere('model', '!=', 'Provider');
            })
            ->orderBy('id', 'desc')
            ->first();

        if ($last) {
            $billingUser->update(['current_balance' => $last->balance]);
            $updated++;
        }
    }

    return response()->json([
        'message' => 'Balance synced from saldo_users to billing_users.',
        'updated' => $updated,
        'total' => $all->count(),
    ]);
})->middleware(['auth:sanctum', 'verified', 'admin']);
//
//
// BELOW IS ROUTE FOR TESTING
// PLEASE CLEAR ALL ROUTE IN BELOW IF APP DEPOLY IN PRODUCTION SERVER
//
//
if(env('APP_ENV')=='local') {
    include 'test.php';
}


