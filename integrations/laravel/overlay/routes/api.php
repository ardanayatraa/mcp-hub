<?php

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use App\Http\Controllers\ApiWaController;
use App\Http\Controllers\TestApiController;
use App\Http\Controllers\ApiTeamWaController;
use App\Http\Controllers\ApiBulkSmsController;
use App\Http\Controllers\ApiChatController;
use App\Http\Controllers\ApiOneWayController;
use App\Http\Controllers\ApiSmsController;
use App\Http\Controllers\ApiTwoWayController;
use App\Http\Controllers\ApiRequestController;
use App\Http\Controllers\ApiResourceController;
use App\Http\Controllers\ApiTemplateController;
use App\Http\Controllers\ApiViGuardController;
use App\Http\Controllers\ApiBlastController;
use App\Models\LogChange;
use Illuminate\Support\Facades\Log;
use App\Http\Controllers\AiController;

/*
|--------------------------------------------------------------------------
| API Routes
|--------------------------------------------------------------------------
|
| Here is where you can register API routes for your application. These
| routes are loaded by the RouteServiceProvider within a group which
| is assigned the "api" middleware group. Enjoy building your API!
|
*/

Route::middleware('auth:sanctum')->get('/user', function (Request $request) {
    return $request->user();
});

Route::get('/wa/{messege}',  [ApiWaController::class, 'show']);
Route::post('/wa',  [ApiWaController::class, 'retriveNewMessage']);
Route::post('/webhook/{slug}',  [ApiWaController::class, 'inbounceMessage'])->name('api.client.webhook');
// Route::get('/chat/{phone}',  [TestApiController::class, 'get']);

Route::middleware(['auth:sanctum', 'user'])->group(function () {
    // sample key : kHy717zKGKN9Xwt1GdD14JryEBsLFApJSEiG1Gmy = telixcel
    // sample 1 : QxYBf46DyeSSsuXKf6tWWpd0rZBVT1a8dFeFSOyM = gusin
    Route::get('/test',  [TestApiController::class, 'get']);
    Route::post('/test',  [TestApiController::class, 'post']);
    Route::post('/bulksms',  [ApiBulkSmsController::class, 'post']);

    // API for chat
    Route::get('/getmsg/{id}',  [TestApiController::class, 'get']);
    Route::post('/sendmsg/{id}',  [TestApiController::class, 'post']);

    // API for chat
    Route::get('/chat/{phone}',  [ApiChatController::class, 'show']);
    Route::post('/chat',  [ApiChatController::class, 'post']);
    Route::post('/chat/bulk',  [ApiChatController::class, 'post']);
    // API for sms
    Route::get('/sms',  [ApiSmsController::class, 'index']);
    Route::get('/sms/{phone}',  [ApiSmsController::class, 'show']);
    Route::post('/sms',  [ApiSmsController::class, 'post']);
    Route::post('/sms/bulk',  [ApiSmsController::class, 'sendBulk']);

    //API for 1Way
    Route::get('/one-way',  [ApiOneWayController::class, 'index']);
    Route::post('/one-way',  [ApiOneWayController::class, 'post']);
    Route::post('/one-way/group',  [ApiOneWayController::class, 'sendBulk1']);
    Route::get('/one-way/campaign',  [ApiOneWayController::class, 'show']);
    //API for 2Way
    Route::get('/two-way',  [ApiTwoWayController::class, 'index']);
    Route::post('/two-way',  [ApiTwoWayController::class, 'post']);
    Route::post('/two-way/group',  [ApiTwoWayController::class, 'sendBulk']);
    Route::get('/two-way/campaign',  [ApiTwoWayController::class, 'show']);
    Route::get('resources', [ApiResourceController::class, 'index']);
    Route::post('resources/skiptrace', [ApiResourceController::class, 'skiptrace']);
    Route::post('resources/validation', [ApiResourceController::class, 'validation']);
    //API Template
    Route::get('/templates',  [ApiTemplateController::class, 'index']);
    Route::post('/templates',  [ApiTemplateController::class, 'post']);
    Route::put('/templates/update',  [ApiTemplateController::class, 'update']);
    Route::delete('/templates/delete',  [ApiTemplateController::class, 'delete']);
});

//Route::get('/test',  [TestApiController::class, 'get']);
Route::get('/testing/{id}',  [TestApiController::class, 'show']);
Route::post('/testing',  [TestApiController::class, 'post']);
Route::get('/send/smsbulk',  [TestApiController::class, 'smsbulk']);
Route::put('/test/{id}',  [TestApiController::class, 'put']);

Route::get('/team-auth',  [ApiTeamWaController::class, 'getAuth']);
Route::post('/post-team-auth',  [ApiTeamWaController::class, 'postTeamAuth'])->name('wa.session');
Route::get('/test/{id}',  [ApiTeamWaController::class, 'getTeam']);
Route::put('/team-auth/{id}',  [ApiTeamWaController::class, 'put']);


//DN URL
Route::get('/receive-request-status',  [ApiRequestController::class, 'status']);
Route::get('/blast-request-status', function (Request $request) {
    return $request->all();
});
Route::get('/sms-update-status',  [ApiBlastController::class, 'status']); 
Route::get('/receive-update-status/{id}',  [ApiRequestController::class, 'status']);
//MO URL
Route::get('/callback-status',  [ApiRequestController::class, 'callBack']);
Route::post('/callback-status',  [ApiRequestController::class, 'callBack']);
Route::get('/callback-status/{model}/{id}',  [ApiRequestController::class, 'callBackStatus']);
Route::post('/callback-status/{model}/{id}',  [ApiRequestController::class, 'callBackStatus']);

//ManualDN
Route::get('/update-status-sms',  [ApiRequestController::class, 'updateManual'])->name('update.sms');

//Route::get('/log-request-status',  [ApiRequestController::class, 'logStatus']);
Route::get('/delivery-notification',  [ApiBulkSmsController::class, 'status']);
Route::post('/delivery-notification',  [ApiBulkSmsController::class, 'status']);
//Route::get('/log-request-status1',  [ApiBulkSmsController::class, 'logStatus']);
//TWO WAY MESSAGE
Route::post('/inbound-messages',  [ApiWaController::class, 'retriveNewMessage']);
Route::post('/inbound-messages/{wabaName}',  [ApiWaController::class, 'retriveNewMessage']);
Route::get('/inbound-messages/{provider}',  [ApiTwoWayController::class, 'retriveNewMessage']);
//ViGuard API access
Route::post('/get/saveAlarm', [ApiViGuardController::class, 'index']);
Route::post('/saveAlarm', [ApiViGuardController::class, 'post']);
Route::post('/getAllMonitoringDeviceList', [ApiViGuardController::class, 'getMonitoringDevice']);
Route::post('/getAllDeptList', [ApiViGuardController::class, 'getDeptList']);
Route::get('/get/listAlarm', [ApiViGuardController::class, 'getListAlert']);

//
// TESTING ROUTE
//
Route::get('/sample/message', function (Request $request) {
    if ($request->has('status')) {
        if ($request->status == 'accepted') {
            return response()->json([
                'message_status' => [
                    'message_id' => '100000000050',
                    'recipient' => '601265',
                    'status' => 'ACCEPTED',
                ]
            ]);
        }
        if ($request->status == 'read') {
            return response()->json([
                'message_status' => [
                    'message_id' => '100000000050',
                    'recipient' => '601265',
                    'status' => 'ACCEPTED',
                ]
            ]);
        }
        if ($request->status == 'delete') {
            return response()->json([
                'message_status' => [
                    'message_id' => '100000000050',
                    'recipient' => '601265',
                    'status' => 'DELETE',
                ]
            ]);
        }
        if ($request->status == 'undelivered') {
            return response()->json([
                'message_status' => [
                    'message_id' => '100000000050',
                    'recipient' => '601265',
                    'status' => 'UNDELIVERED',
                ]
            ]);
        }
        if ($request->status == 'accepted') {
            return response()->json([
                'message_status' => [
                    'message_id' => '100000000050',
                    'recipient' => '601265',
                    'status' => 'DELIVERED',
                ]
            ]);
        }
    }
    return response()->json([
        'Msg' => "Failed",
        'Status' => 400
    ]);
});

Route::middleware(['auth:sanctum', 'user'])->post('/sent/sample', function (Request $request) {
    if ($request->channel) {
        $result = '';

        if (app()->environment('production')) {
            $curl = curl_init();
            curl_setopt($curl, CURLOPT_RETURNTRANSFER, 1);
            curl_setopt($curl, CURLOPT_POST, 1);
            curl_setopt($curl, CURLOPT_HTTPHEADER, array(
                "Content-Type: application/json"
            ));
            curl_setopt(
                $curl,
                CURLOPT_URL,
                "https://api.smtp2go.com/v3/email/send"
            );
            curl_setopt($curl, CURLOPT_POSTFIELDS, json_encode(array(
                "api_key" => (string) env('SMTP2GO_API_KEY'),
                "sender" => (string) $request->input('sender'),
                "to" => [(string) $request->input('to')],
                "subject" => "testing api email hi",
                "html_body" => (string) $request->input('body'),
                "text_body" => (string) strip_tags($request->input('body'))
            )));
            $result = curl_exec($curl);
            curl_close($curl);
        } else {
            $result = json_encode([
                "request_id" => "7d2fb8ea-9849-11ef-979e-f23c9216bfca",
                "data" => [
                    "succeeded" => 1,
                    "failed" => 0,
                    "failures" => [],
                    "email_id" => "1t6qOV-4o5NDgrqg9Q-n4fA"
                ]
            ]);
        }

        LogChange::create([
            'model' => 'Provider',
            'model_id' => 1,
            'before' => $result,
            'remark' => 'TESTING',
            'user_id' => auth()->user()->id
        ]);

        return $result;
    } else {
        return 'Coming soon, we add ' . $request->channel;
    }
});

Route::post('/get/saveAlarm', [ApiViGuardController::class, 'index']);
Route::post('/saveAlarm', [ApiViGuardController::class, 'post']);

Route::get('/dummy-json', function () {
    return response()->json([
        "request_id" => "75cfd9e2-12a0-11ef-b9d5-f23c9216ceac",
        "data" => [
            "succeeded" => 1,
            "failed" => 0,
            "failures" => [],
            "email_id" => "1s7BGm-4o5NDgrqRFC-t8WB"
        ]
    ]);
});

Route::get("/dummy-array", function () {
    $resData = [
        'code' => 200,
        'message' => 'Success',
        'data' => true,
    ];

    return response()->json($resData);
});

Route::get("/dummy-array2", function () {
    $resData = [
        'code' => 200,
        'message' => 'Success',
        'response' => [
            [
                'id' => 1,
                'name' => 'John Doe',
                'email' => 'john.doe@example.com',
                'roles' => ['admin', 'editor']
            ],
            [
                'id' => 2,
                'name' => 'Jane Smith',
                'email' => 'jane.smith@example.com',
                'roles' => ['user']
            ]
        ],
        'data' => [
            'warna' => 'kuning',
        ]
    ];

    return response()->json($resData);
});

Route::get("/dummy-string", function (Request $request) {
    if($request->to){
        return $request->to.',118888000,200,IDR,350';
    }
    return '6281339668556,118888000,200,IDR,350|6281999222185,118888001,200,IDR,350';
});

Route::get("/dummy-string-error", function () {
    return '400';
});

Route::get("/sample/server-viguard/getAllDeptList", function () {
    $arrayVar = [
        "msg" => "Success",
        "code" => 0,
        "data" => [
            [
                "deptId" => "1",
                "parentId" => "230",
                "ancestors" => "0,100",
                "deptName" => "Indonesia",
            ],
            [
                "deptId" => "2",
                "parentId" => "230",
                "ancestors" => "0,100,230",
                "deptName" => "Local Test",
            ],
            [
                "deptId" => "3",
                "parentId" => "230",
                "ancestors" => "0,100,230",
                "deptName" => rand(3,5),
            ],
        ],
    ];

    return response()->json($arrayVar);
});

Route::get("/sample/gemini", function(){
    $sample = [
        "candidates"=> [
            [
                "content"=> [
                    "parts"=> [
                        [
                            "text"=> "Subject=> ⚡️ Never Miss a Beat=> Get Instant Blast Notifications with [Product Name]!\n\nHi [Customer Name],\n\nAre you tired of missing important updates? Do you wish you could be instantly alerted to critical information affecting your business/life?\n\nIntroducing [Product Name]'s revolutionary Blast Notifications! Stop checking emails and refreshing dashboards – get real-time alerts delivered directly to your [Device/Platform - e.g., phone, computer, email].\n\n[Product Name] keeps you in the loop with=>\n\n* **Instant Alerts=>** Receive immediate notifications for critical events, important updates, and time-sensitive information.\n* **Customizable Settings=>** Tailor your notifications to receive only the alerts that matter most to you. Filter by urgency, category, and more!\n* **Increased Efficiency=>** Save valuable time and resources by knowing exactly what's happening, when it's happening.\n* **[Add a key benefit specific to your product/service, e.g., Improved Response Times, Reduced Downtime, Enhanced Security].**\n\n\nFor a limited time, enjoy [Promotion – e.g., a discount, free trial, premium features]=>\n\n* **[Specific Offer, e.g., 20% off your first month, a free 30-day trial, upgrade to Pro for free].**\n* **Use code [Discount Code] at checkout.**\n\nDon't miss out on this opportunity to stay ahead of the curve. Activate Blast Notifications today!\n\n[Link to Product Page/Sign-Up]\n\nSincerely,\n\nThe [Your Company Name] Team\n\n\nP.S. See Blast Notifications in action with this short video=> [Link to Video (optional)]\n"
                        ]
                    ],
                    "role"=> "model"
                ],
                "finishReason"=> "STOP",
                "avgLogprobs"=> -0.29737101720032078
            ]
        ],
        "usageMetadata"=> [ "promptTokenCount"=> 8, "candidatesTokenCount"=> 358, "totalTokenCount"=> 366 ],
        "modelVersion"=> "gemini-1.5-flash-002" ];
    return response()->json($sample);
});

Route::get("/sample/waba-mk", function () {
    $word = "Terima kasih sudah terhubung dengan FirmApps AI. Saat ini kami sedang memproses permintaan Anda untuk produk {{1}} dengan Nomor: {{2}}. Untuk informasi lebih lanjut hubungi: FirmApps AI Email: hireach@firmapps.ai";
    $txt = replaceBrackets2Text($word, [
        '0' => 'AI',
        '1' => '1234567890'
    ]);
    $resData = [
        'message_id' => 4000030549360,
        'text' => $txt
    ];

    return response()->json($resData);
});

Route::post("/sample/waba-mk", function () {
    $resData = [
        'message_id' => rand(10000000, 99999999),
    ];

    return response()->json($resData);
});

Route::middleware(['auth:sanctum', 'user'])->group(function () {
    Route::post('/ai/chat', [AiController::class, 'chat'])->name('api.ai.chat');
    Route::get('/internal/ai/tools', [AiController::class, 'tools'])->name('ai.internal.tools');
    Route::post('/ai/export', [AiController::class, 'export'])->name('api.ai.export');
    Route::post('/internal/ai/query', [AiController::class, 'query'])->name('ai.internal.query');
    Route::post('/internal/ai/confirm', [AiController::class, 'confirm'])->name('ai.internal.confirm');
});

// Hub reads and prepares proposals; authenticated Hireach users confirm commits separately.
Route::prefix('ai/v1')->middleware('throttle:60,1')->group(function () {
    Route::get('/health', [\App\Http\Controllers\McpConnectorController::class, 'health']);
    Route::get('/capabilities', [\App\Http\Controllers\McpConnectorController::class, 'capabilities']);
    Route::post('/{resource}/prepare_{action}', [\App\Http\Controllers\McpConnectorController::class, 'prepare'])
        ->where('resource', '[a-z][a-z0-9_]{0,47}')->where('action', 'create|update|delete');
    Route::get('/{resource}/{action}', [\App\Http\Controllers\McpConnectorController::class, 'read'])
        ->where('resource', '[a-z][a-z0-9_]{0,47}')->where('action', 'list|get|count');
});
