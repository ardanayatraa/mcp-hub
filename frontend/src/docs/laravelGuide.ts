// Laravel integration guide. One source for the page, the Markdown download and the starter kit zip.
// Inline `code` in prose is rendered as code. Code blocks use String.raw so PHP namespaces keep their backslashes.

import { guideMarkdown as renderMarkdown, withMcpUrl, type GuideMeta, type GuideSection } from "@/docs/guide";

export const GUIDE: GuideMeta = {
  badge: "Integration guide",
  title: "Connect a Laravel app to MCP Hub",
  summary: "Publish a small, authenticated JSON API from Laravel so AI clients can read your data and create, update or delete it through MCP Hub, with your app's own permissions on every request and every change confirmed by the user.",
  meta: ["Laravel 11, 12 or 13", "PHP 8.2+", "About 30 minutes"],
};

export const SECTIONS: GuideSection[] = [
  {
    id: "overview",
    title: "How it works",
    body: [
      "Your Laravel app keeps its data and its permissions. MCP Hub never connects to your database: it calls a few routes your app publishes, and only the ones listed in your manifest.",
      "You build these routes, and your own chat window if you want one, so you control every line.",
    ],
    list: [
      "The Hub calls your app with a bearer token: `Authorization: Bearer <token>`. Your middleware checks it on every route.",
      "Your manifest (`/api/ai/v1/capabilities`) lists data sources, readable fields and the exact routes the Hub may call.",
      "For data that belongs to a user, the Hub forwards who is asking in a signed `X-Hub-Assertion` header. Your app verifies it and applies the user's normal permissions.",
      "Create, update and delete are proposals: your route saves the change for the user and returns a receipt with `requires_confirmation`; the user confirms it inside your app, and only then is it applied.",
      "AI clients (Claude, Cursor or your own AI gateway) call the Hub's MCP endpoint with a client key, also as a bearer token. They never see your app's token.",
    ],
    table: {
      head: ["File", "Purpose"],
      rows: [
        ["`.env`", "Keys and URLs, kept out of version control"],
        ["`config/mcp_hub.php`", "Reads the settings once, for config caching"],
        ["`app/Http/Middleware/VerifyHubToken.php`", "Rejects any request without the Hub's bearer token"],
        ["`app/Support/HubToken.php`", "Signs and verifies user context tokens"],
        ["`database/migrations/…_create_hub_proposals_table.php`, `app/Models/HubProposal.php`", "Changes the AI prepared, waiting for the user"],
        ["`app/Http/Controllers/Api/HubController.php`", "Health, manifest, list, get, and prepare create, update and delete"],
        ["`routes/api.php`", "The routes the Hub calls, under `/api/ai/v1`"],
        ["`app/Http/Controllers/HubProposalController.php`, `resources/views/hub/proposals.blade.php`", "The user confirms or cancels each change"],
        ["`app/Services/McpHubClient.php`", "Optional: lets your app call AI tools for the signed-in user"],
        ["`app/Http/Controllers/AiChatController.php`", "Optional: streams the Hub's AI chat to a chat window you design"],
        ["`tests/Feature/HubContractTest.php`", "Checks reads, every write and the confirmation in CI"],
      ],
    },
  },
  {
    id: "requirements",
    title: "Before you start",
    body: ["You need:"],
    list: [
      "A Laravel 11, 12 or 13 app reachable from the Hub over HTTPS (plain HTTP works only on a development Hub), with signed-in users.",
      "An MCP Hub account with the App admin or Super admin role.",
      "An API routes file: run `php artisan install:api` if `routes/api.php` does not exist yet.",
      "The examples use an `Order` model that belongs to a `User`, with `number`, `status`, `total` and `note`. Swap in your own model and fields; to try the guide in a fresh app, add the two files below and run `php artisan migrate`.",
    ],
    files: [
      {
        path: "database/migrations/2026_10_11_000001_create_orders_table.php",
        lang: "php",
        kind: "snippet",
        caption: "Only to try the guide in a fresh app",
        code: String.raw`<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('orders', function (Blueprint $table) {
            $table->id();
            $table->foreignId('user_id')->constrained()->cascadeOnDelete();
            $table->string('number', 32);
            $table->string('status', 12)->default('open');
            $table->decimal('total', 12, 2)->default(0);
            $table->string('note', 200)->nullable();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('orders');
    }
};`,
      },
      {
        path: "app/Models/Order.php",
        lang: "php",
        kind: "snippet",
        caption: "Only to try the guide in a fresh app",
        code: String.raw`<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class Order extends Model
{
    protected $fillable = ['user_id', 'number', 'status', 'total', 'note'];

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }
}`,
      },
    ],
  },
  {
    id: "configure",
    title: "Add the settings",
    step: 1,
    body: [
      "Add these lines with empty values. There is nothing to generate: when you connect the app in step 7, the Hub fills in every value and shows them as one block to paste over these lines.",
    ],
    files: [
      {
        path: ".env",
        lang: "dotenv",
        kind: "snippet",
        caption: "Add to your .env (never commit it); step 7 gives you the values",
        code: String.raw`# MCP Hub: the Hub calls this app
MCP_HUB_APP_KEY=your_app
# Exactly the Base URL you enter in the Hub: scheme, host and port, no trailing slash
MCP_HUB_BASE_URL=https://app.example.com
MCP_HUB_APP_TOKEN=
MCP_HUB_DELEGATION_SECRET=

# Optional: this app calls AI tools through the Hub
MCP_HUB_URL=https://hub.example.com/mcp
MCP_HUB_CLIENT_KEY=`,
      },
      {
        path: "config/mcp_hub.php",
        lang: "php",
        kind: "file",
        code: String.raw`<?php

return [
    // Must equal the app key entered in MCP Hub and the manifest's "application".
    'app_key' => env('MCP_HUB_APP_KEY', 'your_app'),

    // Must equal the Base URL entered in MCP Hub. User assertions are signed for this audience.
    'base_url' => rtrim((string) env('MCP_HUB_BASE_URL', env('APP_URL')), '/'),

    // Sent by the Hub as "Authorization: Bearer <token>" on every request.
    'app_token' => env('MCP_HUB_APP_TOKEN'),

    // Shared with the Hub to sign which user is asking.
    'delegation_secret' => env('MCP_HUB_DELEGATION_SECRET'),

    // Refuse Hub calls over plain HTTP. On by default in production; behind a proxy, configure TrustProxies.
    'require_https' => (bool) env('MCP_HUB_REQUIRE_HTTPS', env('APP_ENV') === 'production'),

    // Optional: calling the Hub's MCP endpoint from this app.
    'mcp_url' => env('MCP_HUB_URL'),
    'client_key' => env('MCP_HUB_CLIENT_KEY'),
];`,
      },
    ],
  },
  {
    id: "authenticate",
    title: "Check the Hub's bearer token",
    step: 2,
    body: [
      "Every Hub request carries `Authorization: Bearer <token>`. Laravel's `bearerToken()` reads it; compare it in constant time and answer with the contract's error shape when it is missing or wrong.",
      "The same middleware refuses plain HTTP in production and marks every answer `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`, so user data is never cached or content-sniffed (OWASP ASVS V8 and V9).",
    ],
    files: [
      {
        path: "app/Http/Middleware/VerifyHubToken.php",
        lang: "php",
        kind: "file",
        code: String.raw`<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class VerifyHubToken
{
    public function handle(Request $request, Closure $next): Response
    {
        $expected = (string) config('mcp_hub.app_token');
        $given = (string) $request->bearerToken();
        $secure = $request->isSecure() || ! config('mcp_hub.require_https');

        $response = $secure && strlen($expected) >= 8 && hash_equals($expected, $given)
            ? $next($request)
            : response()->json([
                'success' => false,
                'error' => ['code' => 'PERMISSION_DENIED', 'message' => $secure ? 'Invalid service credential' : 'HTTPS is required'],
            ], 401);

        // Answers hold user data: never cached, never content-sniffed.
        $response->headers->set('Cache-Control', 'no-store');
        $response->headers->set('X-Content-Type-Options', 'nosniff');

        return $response;
    }
}`,
      },
      {
        path: "bootstrap/app.php",
        lang: "php",
        kind: "snippet",
        caption: "Laravel 11 and 12: register the alias. On Laravel 10, add it to $middlewareAliases in app/Http/Kernel.php.",
        code: String.raw`->withMiddleware(function (Middleware $middleware) {
    $middleware->alias([
        'hub.token' => \App\Http\Middleware\VerifyHubToken::class,
    ]);
})`,
      },
    ],
  },
  {
    id: "user-context",
    title: "Verify who is asking",
    step: 3,
    body: [
      "User-scoped routes receive `X-Hub-Assertion`: `base64url(JSON) + \".\" + base64url(HMAC-SHA256)`, signed with the delegation secret. It names the user (`user_ref`) and the account that owns the data (`tenant_id`), has `aud` set to your base URL and expires within 60 seconds.",
      "Each assertion carries a random `jti` and is accepted once: `Cache::add` records it until it expires, so a captured header cannot be replayed. Use a shared cache (Redis, database or file) when several servers run the app.",
      "The same class signs `X-Hub-Delegation` when your app calls the Hub (step 8). Adjust `subject()` once if your data belongs to teams rather than users.",
    ],
    files: [
      {
        path: "app/Support/HubToken.php",
        lang: "php",
        kind: "file",
        code: String.raw`<?php

namespace App\Support;

use App\Models\User;
use Illuminate\Support\Facades\Cache;
use RuntimeException;

/**
 * Tokens shared with MCP Hub: base64url(JSON) . "." . base64url(HMAC-SHA256 of that JSON).
 * X-Hub-Delegation (this app -> Hub) and X-Hub-Assertion (Hub -> this app) use this format.
 */
final class HubToken
{
    /** How this app names a user and the account that owns their data. Change it here only. */
    public static function subject(User $user): array
    {
        return ['tenant_id' => 'user_'.$user->id, 'user_ref' => 'user_'.$user->id];
    }

    public static function sign(array $claims, int $ttlSeconds = 120): string
    {
        $claims['exp'] = time() + min($ttlSeconds, 120);
        $claims['jti'] = self::encode(random_bytes(18));
        $raw = json_encode($claims, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);

        return self::encode($raw).'.'.self::encode(hash_hmac('sha256', $raw, self::secret(), true));
    }

    /** @return array<string, mixed> The verified claims. */
    public static function verify(?string $token, string $audience): array
    {
        [$body, $signature] = array_pad(explode('.', (string) $token, 2), 2, '');
        $raw = self::decode($body);

        if ($raw === '' || ! hash_equals(hash_hmac('sha256', $raw, self::secret(), true), self::decode($signature))) {
            throw new RuntimeException('The Hub signature is not valid.');
        }

        $claims = json_decode($raw, true);
        $now = time();

        if (! is_array($claims) || ! is_int($claims['exp'] ?? null) || $claims['exp'] <= $now || $claims['exp'] > $now + 150) {
            throw new RuntimeException('The Hub token has expired.');
        }
        if (($claims['aud'] ?? null) !== $audience || ($claims['app_key'] ?? null) !== config('mcp_hub.app_key')) {
            throw new RuntimeException('The Hub token was issued for another application.');
        }
        if (! is_string($claims['jti'] ?? null) || ! preg_match('/^[A-Za-z0-9_-]{16,64}$/D', $claims['jti'])
            || ! Cache::add('mcp_hub.jti.'.hash('sha256', $claims['jti']), true, $claims['exp'] - $now + 5)) {
            throw new RuntimeException('The Hub token was already used.');
        }

        return $claims;
    }

    private static function secret(): string
    {
        $secret = (string) config('mcp_hub.delegation_secret');

        if (strlen($secret) < 8) {
            throw new RuntimeException('MCP_HUB_DELEGATION_SECRET is not configured.');
        }

        return $secret;
    }

    private static function encode(string $value): string
    {
        return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
    }

    private static function decode(string $value): string
    {
        return (string) base64_decode(strtr($value, '-_', '+/'), true);
    }
}`,
      },
    ],
  },
  {
    id: "proposals",
    title: "Store changes until the user confirms",
    step: 4,
    body: [
      "The AI never changes data directly. A create, update or delete request becomes a proposal: a row saved for the signed-in user, with a short summary. Nothing in your orders changes until that user confirms it in your app (step 6). Proposals expire after 15 minutes.",
      "The Hub sends an `Idempotency-Key` with every write request, so a repeated request returns the same proposal instead of a second one.",
    ],
    files: [
      {
        path: "database/migrations/2026_10_11_000000_create_hub_proposals_table.php",
        lang: "php",
        kind: "file",
        code: String.raw`<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('hub_proposals', function (Blueprint $table) {
            $table->id();
            $table->string('ref', 40)->unique();
            $table->foreignId('user_id')->constrained()->cascadeOnDelete();
            $table->string('operation', 10);           // create, update or delete
            $table->string('subject_type', 40);        // the module, for example orders
            $table->unsignedBigInteger('subject_id')->nullable();
            $table->json('payload');
            $table->string('summary', 300);
            $table->string('idempotency_key', 100)->nullable();
            $table->string('status', 12)->default('pending'); // pending, applied or cancelled
            $table->timestamp('expires_at');
            $table->timestamp('decided_at')->nullable();
            $table->timestamps();
            $table->unique(['user_id', 'idempotency_key']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('hub_proposals');
    }
};`,
      },
      {
        path: "app/Models/HubProposal.php",
        lang: "php",
        kind: "file",
        code: String.raw`<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Str;

/** A change the AI prepared for one user. It is applied only when that user confirms it. */
class HubProposal extends Model
{
    protected $guarded = [];

    protected $casts = ['payload' => 'array', 'expires_at' => 'datetime', 'decided_at' => 'datetime'];

    public static function prepare(User $user, string $operation, string $subject, ?int $subjectId, array $payload,
                                   string $summary, ?string $idempotencyKey): self
    {
        $key = $idempotencyKey ? Str::limit($idempotencyKey, 100, '') : null;

        if ($key && $existing = self::query()->where('user_id', $user->id)->where('idempotency_key', $key)->first()) {
            return $existing;
        }

        return self::create([
            'ref' => 'prop_'.Str::lower(Str::random(24)),
            'user_id' => $user->id,
            'operation' => $operation,
            'subject_type' => $subject,
            'subject_id' => $subjectId,
            'payload' => $payload,
            'summary' => Str::limit($summary, 290),
            'idempotency_key' => $key,
            'status' => 'pending',
            'expires_at' => now()->addMinutes(15),
        ]);
    }

    public function scopePendingFor(Builder $query, User $user): Builder
    {
        return $query->where('user_id', $user->id)->where('status', 'pending')->where('expires_at', '>', now());
    }
}`,
      },
    ],
    after: ["Run `php artisan migrate`."],
  },
  {
    id: "routes",
    title: "Publish the manifest and the CRUD routes",
    step: 5,
    body: [
      "One controller serves everything the Hub calls: the health check, the manifest, two read routes (a page of orders, and one order by its `ref`) and three write routes that prepare a create, update or delete. Totals and breakdowns need no extra route: the Hub's `run_report` reads the list route page by page.",
      "Every route takes the user from the verified assertion, never from arguments, reads only that user's orders, returns declared fields only and answers in the contract's envelope. Change `manifest_version` whenever a field or route changes: the Hub then asks an admin to review the module again.",
    ],
    files: [
      {
        path: "routes/api.php",
        lang: "php",
        kind: "snippet",
        caption: "Add to routes/api.php, which already imports Route. Laravel prefixes these with /api.",
        code: String.raw`use App\Http\Controllers\Api\HubController;

Route::prefix('ai/v1')->middleware(['hub.token', 'throttle:120,1'])->group(function () {
    Route::get('health', [HubController::class, 'health']);
    Route::get('capabilities', [HubController::class, 'manifest']);
    Route::get('orders/list', [HubController::class, 'index']);
    Route::post('orders/propose-create', [HubController::class, 'proposeCreate']);
    Route::get('orders/{ref}', [HubController::class, 'show'])->where('ref', 'ord_[0-9]+');
    Route::post('orders/{ref}/propose-update', [HubController::class, 'proposeUpdate'])->where('ref', 'ord_[0-9]+');
    Route::post('orders/{ref}/propose-delete', [HubController::class, 'proposeDelete'])->where('ref', 'ord_[0-9]+');
});`,
      },
      {
        path: "app/Http/Controllers/Api/HubController.php",
        lang: "php",
        kind: "file",
        code: String.raw`<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\HubProposal;
use App\Models\Order;
use App\Models\User;
use App\Support\HubToken;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Validator;
use Illuminate\Support\Str;
use Illuminate\Validation\Rule;
use Throwable;

/**
 * The routes MCP Hub calls. Reads return the signed-in user's own orders. Writes only prepare
 * a proposal; the user applies it in this app (HubProposalController).
 */
class HubController extends Controller
{
    public const STATUSES = ['open', 'paid', 'void'];

    public function health(): JsonResponse
    {
        return response()->json(['status' => 'ok']);
    }

    public function manifest(): JsonResponse
    {
        $ref = ['type' => 'string', 'maxLength' => 40];
        $order = [
            'ref' => $ref,
            'number' => ['type' => 'string', 'maxLength' => 32],
            'status' => ['type' => 'string', 'enum' => self::STATUSES],
            'total' => ['type' => 'number'],
            'note' => ['type' => ['string', 'null'], 'maxLength' => 200],
            'created_at' => ['type' => 'string', 'maxLength' => 64],
        ];
        $editable = [
            'status' => ['type' => 'string', 'enum' => self::STATUSES],
            'total' => ['type' => 'number', 'minimum' => 0, 'maximum' => 100000000],
            'note' => ['type' => 'string', 'maxLength' => 200],
        ];
        $receipt = $this->rows(1, [
            'proposal_ref' => ['type' => 'string', 'maxLength' => 40],
            'summary' => ['type' => 'string', 'maxLength' => 300],
        ]);

        return response()->json([
            'contract_version' => '1.0',
            'application' => config('mcp_hub.app_key'),
            'manifest_version' => '2026-10-11.2',
            'modules' => [[
                'key' => 'orders',
                'name' => 'Orders',
                'description' => 'Orders that belong to the signed-in user',
                'schema_version' => '1.0',
                'supported_operations' => ['read', 'create', 'update', 'delete'],
                'readable_fields' => array_keys($order),
                'writable_fields' => ['number', 'status', 'total', 'note'],
                'max_page_size' => 50,
                'read_endpoints' => [
                    $this->route('GET', '/api/ai/v1/orders/list', 'List the user\'s orders, newest first.', [
                        'status' => ['type' => 'string', 'enum' => self::STATUSES],
                        'limit' => ['type' => 'integer', 'minimum' => 1, 'maximum' => 50],
                        'cursor' => ['type' => 'string', 'maxLength' => 32],
                    ], [], $this->rows(50, $order)),
                    $this->route('GET', '/api/ai/v1/orders/{ref}', 'Get one of the user\'s orders by its ref.',
                        ['ref' => $ref], ['ref'], $this->rows(1, $order)),
                ],
                'write_endpoints' => [
                    ['operation' => 'create'] + $this->route('POST', '/api/ai/v1/orders/propose-create',
                        'Prepare a new order. Nothing is saved until the user confirms it.',
                        ['number' => ['type' => 'string', 'minLength' => 1, 'maxLength' => 32]] + $editable, ['number', 'total'], $receipt),
                    ['operation' => 'update'] + $this->route('POST', '/api/ai/v1/orders/{ref}/propose-update',
                        'Prepare a change to an order. Nothing changes until the user confirms it.',
                        ['ref' => $ref] + $editable, ['ref'], $receipt),
                    ['operation' => 'delete'] + $this->route('POST', '/api/ai/v1/orders/{ref}/propose-delete',
                        'Prepare deleting an order. Nothing is deleted until the user confirms it.',
                        ['ref' => $ref], ['ref'], $receipt),
                ],
            ]],
        ]);
    }

    public function index(Request $request): JsonResponse
    {
        $user = $this->actingUser($request, 'orders.read');
        $input = $this->validated($request->query(), [
            'status' => ['sometimes', Rule::in(self::STATUSES)],
            'limit' => ['sometimes', 'integer', 'min:1', 'max:50'],
            'cursor' => ['sometimes', 'regex:/^page_\d{1,6}$/'],
        ]);
        $offset = (int) substr($input['cursor'] ?? 'page_0', 5);
        $query = Order::query()->whereBelongsTo($user)
            ->when($input['status'] ?? null, fn ($query, $status) => $query->where('status', $status));
        $total = (clone $query)->count();
        $rows = $query->orderByDesc('id')->skip($offset)->take((int) ($input['limit'] ?? 50))->get()
            ->map(fn (Order $order) => $this->present($order, $user))->all();
        $more = $offset + count($rows) < $total;

        return $this->ok($rows, [
            'coverage' => $more ? 'partial' : 'complete',
            'total_count' => $total,
            'has_more' => $more,
            'next_cursor' => $more ? 'page_'.($offset + count($rows)) : null,
        ]);
    }

    public function show(Request $request, string $ref): JsonResponse
    {
        $user = $this->actingUser($request, 'orders.read');

        return $this->ok([$this->present($this->ownOrder($user, $ref), $user)]);
    }

    public function proposeCreate(Request $request): JsonResponse
    {
        $user = $this->actingUser($request, 'orders.create');
        $input = $this->validated($request->json()->all(), self::rules('create'));
        $summary = "Create order {$input['number']}: total ".number_format((float) $input['total'], 2)
            .', status '.($input['status'] ?? 'open').(isset($input['note']) ? ', with a note' : '').'.';

        return $this->propose($request, $user, 'create', null, $input, $summary);
    }

    public function proposeUpdate(Request $request, string $ref): JsonResponse
    {
        $user = $this->actingUser($request, 'orders.update');
        $order = $this->ownOrder($user, $ref);
        $input = $this->validated($request->json()->all(), self::rules('update'));

        if ($input === []) {
            abort($this->fail('VALIDATION_FAILED', 'Say what to change: status, total or note', 422));
        }
        $changes = collect($input)->map(fn ($value, $field) => $field === 'note' ? 'note updated'
            : "{$field} {$order->{$field}} → {$value}")->implode(', ');

        return $this->propose($request, $user, 'update', $order, $input, "Change order {$order->number}: {$changes}.");
    }

    public function proposeDelete(Request $request, string $ref): JsonResponse
    {
        $user = $this->actingUser($request, 'orders.delete');
        $order = $this->ownOrder($user, $ref);
        $this->validated($request->json()->all(), []);
        $summary = "Delete order {$order->number} (total ".number_format((float) $order->total, 2).", {$order->status}).";

        return $this->propose($request, $user, 'delete', $order, [], $summary);
    }

    /** The rules a change must pass, used again when the user confirms it. */
    public static function rules(string $operation): array
    {
        $fields = [
            'status' => ['sometimes', Rule::in(self::STATUSES)],
            'total' => ['sometimes', 'numeric', 'min:0', 'max:100000000'],
            'note' => ['sometimes', 'nullable', 'string', 'max:200'],
        ];

        return match ($operation) {
            'create' => ['number' => ['required', 'string', 'max:32'], 'total' => ['required', 'numeric', 'min:0', 'max:100000000']] + $fields,
            'update' => $fields,
            default => [],
        };
    }

    /** Replace with your own check: a Gate, a policy or a permissions package. */
    public static function allowed(User $user, string $ability): bool
    {
        return true;
    }

    private function propose(Request $request, User $user, string $operation, ?Order $order, array $payload, string $summary): JsonResponse
    {
        $proposal = HubProposal::prepare($user, $operation, 'orders', $order?->id, $payload, $summary,
            $request->header('Idempotency-Key'));

        return $this->ok([[
            'proposal_ref' => $proposal->ref,
            'summary' => $proposal->summary,
            'tenant_id' => HubToken::subject($user)['tenant_id'],
        ]], ['requires_confirmation' => true]);
    }

    private function present(Order $order, User $user): array
    {
        return [
            'ref' => 'ord_'.$order->id,
            'number' => $order->number,
            'status' => $order->status,
            'total' => (float) $order->total,
            'note' => $order->note,
            'created_at' => $order->created_at->toAtomString(),
            'tenant_id' => HubToken::subject($user)['tenant_id'],
        ];
    }

    private function ownOrder(User $user, string $ref): Order
    {
        $order = Order::query()->whereBelongsTo($user)->find((int) Str::after($ref, 'ord_'));

        return $order ?? abort($this->fail('NOT_FOUND', 'No such order for this user', 404));
    }

    /** Known arguments only, each valid; anything else is refused. */
    private function validated(array $data, array $rules): array
    {
        $validator = Validator::make($data, $rules);

        if (array_diff(array_keys($data), array_keys($rules)) || $validator->fails()) {
            abort($this->fail('VALIDATION_FAILED', 'The arguments are not valid', 422));
        }

        return $validator->validated();
    }

    /** The user comes from the signed assertion only, never from tool arguments. */
    private function actingUser(Request $request, string $ability): User
    {
        try {
            $claims = HubToken::verify($request->header('X-Hub-Assertion'), config('mcp_hub.base_url'));
        } catch (Throwable) {
            abort($this->fail('PERMISSION_DENIED', 'The user context is not valid', 403));
        }

        $user = User::find((int) Str::after((string) ($claims['user_ref'] ?? ''), 'user_'));
        $subject = $user ? HubToken::subject($user) : null;

        if (! $subject || $subject['user_ref'] !== ($claims['user_ref'] ?? null) || $subject['tenant_id'] !== ($claims['tenant_id'] ?? null)) {
            abort($this->fail('PERMISSION_DENIED', 'The user context is not valid', 403));
        }
        if (! self::allowed($user, $ability)) {
            abort($this->fail('PERMISSION_DENIED', 'Operation is not permitted', 403));
        }

        return $user;
    }

    private function route(string $method, string $path, string $description, array $inputs, array $required, array $output): array
    {
        return [
            'method' => $method,
            'path_template' => $path,
            'description' => $description,
            'requires_user_context' => true,
            'tenant_field' => 'tenant_id',
            'input_schema' => ['type' => 'object', 'additionalProperties' => false,
                'properties' => $inputs ?: new \stdClass(), 'required' => $required],
            'output_schema' => $output,
        ];
    }

    private function rows(int $max, array $properties): array
    {
        return ['type' => 'array', 'maxItems' => $max, 'items' => [
            'type' => 'object', 'additionalProperties' => false,
            'required' => array_keys($properties), 'properties' => $properties,
        ]];
    }

    private function ok(array $data, array $meta = []): JsonResponse
    {
        return response()->json(['success' => true, 'data' => $data, 'meta' => array_merge([
            'as_of' => now()->toAtomString(),
            'timezone' => config('app.timezone'),
            'scope' => 'authorized_records',
            'coverage' => 'complete',
        ], $meta)]);
    }

    private function fail(string $code, string $message, int $status): JsonResponse
    {
        return response()->json(['success' => false, 'error' => ['code' => $code, 'message' => $message]], $status);
    }
}`,
      },
    ],
    table: {
      head: ["Route", "What the AI can do"],
      rows: [
        ["`GET /api/ai/v1/orders/list`", "List orders (filter by status, 50 per page). `run_report` uses it for totals, counts and trends."],
        ["`GET /api/ai/v1/orders/{ref}`", "Get one order"],
        ["`POST /api/ai/v1/orders/propose-create`", "Prepare a new order"],
        ["`POST /api/ai/v1/orders/{ref}/propose-update`", "Prepare a change to status, total or note"],
        ["`POST /api/ai/v1/orders/{ref}/propose-delete`", "Prepare deleting an order"],
      ],
    },
    after: [
      "Error codes the Hub passes on to the AI: `PERMISSION_DENIED`, `VALIDATION_FAILED`, `NOT_FOUND`, `RATE_LIMITED` and `SCHEMA_MISMATCH`. Anything else becomes `UPSTREAM_ERROR`. Never put personal data in `meta`, cursors, summaries or error messages.",
      "To keep a field out of lists but allow totals, add `'field_policies' => ['total' => 'aggregate_only']` to the module. Field names that look personal (email, phone, token, `user_id`, …) are always hidden by the Hub.",
    ],
  },
  {
    id: "confirm",
    title: "Let the user confirm or cancel",
    step: 6,
    body: [
      "These routes run inside your app with the user's normal session. A page lists what the AI prepared, and the same routes answer JSON for your own chat window (step 9). Confirming checks the rules again, applies the change in a transaction and marks the proposal applied, so a second click does nothing.",
    ],
    files: [
      {
        path: "routes/web.php",
        lang: "php",
        kind: "snippet",
        caption: "Add to routes/web.php",
        code: String.raw`use App\Http\Controllers\HubProposalController;

Route::middleware('auth')->prefix('hub/proposals')->name('hub.proposals.')->group(function () {
    Route::get('/', [HubProposalController::class, 'index'])->name('index');
    Route::post('{ref}/confirm', [HubProposalController::class, 'confirm'])->name('confirm');
    Route::delete('{ref}', [HubProposalController::class, 'cancel'])->name('cancel');
});`,
      },
      {
        path: "app/Http/Controllers/HubProposalController.php",
        lang: "php",
        kind: "file",
        code: String.raw`<?php

namespace App\Http\Controllers;

use App\Http\Controllers\Api\HubController;
use App\Models\HubProposal;
use App\Models\Order;
use App\Models\User;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Validator;

/** The signed-in user applies or cancels changes the AI prepared. */
class HubProposalController extends Controller
{
    public function index(Request $request)
    {
        $proposals = HubProposal::query()->pendingFor($request->user())->latest()->get();

        if ($request->wantsJson()) {
            return response()->json(['success' => true, 'data' => $proposals->map->only(['ref', 'operation', 'summary', 'expires_at'])]);
        }

        return view('hub.proposals', ['proposals' => $proposals]);
    }

    public function confirm(Request $request, string $ref)
    {
        $message = DB::transaction(function () use ($request, $ref) {
            $proposal = HubProposal::query()->pendingFor($request->user())->where('ref', $ref)->lockForUpdate()->first();
            abort_unless($proposal, 404, 'This request expired or was already handled. Ask the assistant again.');
            $message = $this->apply($proposal, $request->user());
            $proposal->update(['status' => 'applied', 'decided_at' => now()]);

            return $message;
        });

        return $request->wantsJson()
            ? response()->json(['success' => true, 'data' => ['message' => $message]])
            : back()->with('status', $message);
    }

    public function cancel(Request $request, string $ref)
    {
        HubProposal::query()->pendingFor($request->user())->where('ref', $ref)
            ->update(['status' => 'cancelled', 'decided_at' => now()]);

        return $request->wantsJson()
            ? response()->json(['success' => true, 'data' => ['message' => 'Cancelled.']])
            : back()->with('status', 'Cancelled.');
    }

    private function apply(HubProposal $proposal, User $user): string
    {
        abort_unless(HubController::allowed($user, "orders.{$proposal->operation}"), 403);
        // Checked again now: the order or your rules may have changed since the AI asked.
        Validator::make($proposal->payload, HubController::rules($proposal->operation))->validate();

        if ($proposal->operation === 'create') {
            $order = Order::create($proposal->payload + ['status' => 'open', 'user_id' => $user->id]);

            return "Order {$order->number} created.";
        }

        $order = Order::query()->whereBelongsTo($user)->find($proposal->subject_id);
        abort_unless($order, 404, 'That order no longer exists.');

        if ($proposal->operation === 'update') {
            $order->update($proposal->payload);

            return "Order {$order->number} updated.";
        }

        $order->delete();

        return "Order {$order->number} deleted.";
    }
}`,
      },
      {
        path: "resources/views/hub/proposals.blade.php",
        lang: "html",
        kind: "file",
        caption: "A plain page; wrap it in your layout (@extends or <x-app-layout>)",
        code: String.raw`<div style="max-width: 720px; margin: 2rem auto; font-family: system-ui, sans-serif">
    <h1>Changes waiting for you</h1>
    <p>Your AI assistant prepared these. Nothing changes until you confirm.</p>

    @if (session('status'))
        <p role="status" style="padding: 8px 12px; background: #ecfdf5; border-radius: 8px">{{ session('status') }}</p>
    @endif
    @if ($errors->any())
        <p role="alert" style="padding: 8px 12px; background: #fef2f2; border-radius: 8px">{{ $errors->first() }}</p>
    @endif

    @forelse ($proposals as $proposal)
        <div style="border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; margin: 12px 0">
            <p style="margin: 0 0 4px; font-size: 12px; color: #6b7280">
                {{ ucfirst($proposal->operation) }} · expires {{ $proposal->expires_at->diffForHumans() }}</p>
            <p style="margin: 0 0 12px">{{ $proposal->summary }}</p>
            <form method="POST" action="{{ route('hub.proposals.confirm', $proposal->ref) }}" style="display: inline">
                @csrf
                <button type="submit">Confirm</button>
            </form>
            <form method="POST" action="{{ route('hub.proposals.cancel', $proposal->ref) }}" style="display: inline">
                @csrf
                @method('DELETE')
                <button type="submit">Cancel</button>
            </form>
        </div>
    @empty
        <p>Nothing is waiting for you.</p>
    @endforelse
</div>`,
      },
    ],
    after: [
      "Link to `/hub/proposals` from your menu. When an AI client such as Claude prepares a change, it tells the user to confirm it in your app; in your own chat window you can show Confirm and Cancel right under the answer instead.",
    ],
  },
  {
    id: "connect",
    title: "Connect the app in MCP Hub",
    step: 7,
    body: ["Open Apps → Connect app and fill in three fields:"],
    table: {
      head: ["Hub field", "Value"],
      rows: [
        ["App name", "Your app's display name"],
        ["App key", "`your_app` (it becomes `MCP_HUB_APP_KEY`)"],
        ["Base URL", "The app's address, such as `https://app.example.com` (it becomes `MCP_HUB_BASE_URL`)"],
      ],
    },
    steps: [
      "Click **Continue**. The Hub creates the bearer token, the delegation secret and a read-only client key, and shows every `MCP_HUB_` value as one block. It is shown once, so copy it now.",
      "Paste the block into `.env` over the empty `MCP_HUB_` lines, then run `php artisan config:clear`.",
      "Click **Check connection**: the Hub calls your health route and reads the manifest.",
      "On **Data sources**, open Orders and allow **Read**, **Create**, **Update** and **Delete**. Leave out what the AI should never do.",
      "On **Tools**, click **Generate tools**. You get List orders, Get one order and Orders summary (live), and Create an order, Update an order and Delete an order (drafts, so a person reviews every write).",
      "Open each write tool, click **Run test** (sample data, nothing is sent to your app), then **Publish**.",
      "**Activate** the app. The client key in your `.env` is read-only; to let your chat use the write tools, open **API keys**, edit that key and tick **Allow write tools**.",
    ],
    after: [
      "Prefer your app to decide everything? Choose **Follow application permissions automatically** instead, add `'managed_by' => 'application'` to the manifest and a `tool_key` such as `your_app.orders.create` to every route: the Hub then publishes exactly the routes you list, without review.",
      "To replace the bearer token or delegation secret later, update `.env` first, then save the new value on the app's API keys tab; the Hub tests the connection right away.",
    ],
  },
  {
    id: "gateway",
    title: "Call AI tools from Laravel (optional)",
    step: 8,
    body: [
      "If your app has its own AI assistant, call the Hub's MCP endpoint with a client key and sign `X-Hub-Delegation` for the signed-in user on every request. The Hub verifies it and forwards a fresh assertion to your routes.",
    ],
    files: [
      {
        path: "app/Services/McpHubClient.php",
        lang: "php",
        kind: "file",
        code: String.raw`<?php

namespace App\Services;

use App\Models\User;
use App\Support\HubToken;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;
use RuntimeException;

/** Calls MCP Hub tools for the signed-in user. The Hub authorizes every call again. */
class McpHubClient
{
    /** @return array<int, array<string, mixed>> Tools this client key may call. */
    public function tools(User $user): array
    {
        return $this->rpc($user, 'tools/list')['tools'] ?? [];
    }

    /** @return array<string, mixed> The tool's structured result. */
    public function call(User $user, string $tool, array $arguments = []): array
    {
        $result = $this->rpc($user, 'tools/call', ['name' => $tool, 'arguments' => (object) $arguments]);

        if ($result['isError'] ?? false) {
            throw new RuntimeException($result['content'][0]['text'] ?? 'The tool call failed.');
        }

        return $result['structuredContent'] ?? json_decode($result['content'][0]['text'] ?? '[]', true) ?? [];
    }

    /** @return array<int, array<string, mixed>> Skills the Hub offers this user's assistant. */
    public function prompts(User $user): array
    {
        return $this->rpc($user, 'prompts/list')['prompts'] ?? [];
    }

    /** A skill's text with the arguments filled in, ready to send to the model as the user's message. */
    public function prompt(User $user, string $name, array $arguments = []): string
    {
        $result = $this->rpc($user, 'prompts/get', ['name' => $name, 'arguments' => (object) $arguments]);

        return $result['messages'][0]['content']['text'] ?? '';
    }

    private function rpc(User $user, string $method, array $params = []): array
    {
        $delegation = HubToken::sign(['app_key' => config('mcp_hub.app_key'), 'aud' => 'mcp-hub'] + HubToken::subject($user));

        $response = Http::withToken((string) config('mcp_hub.client_key'))
            ->withHeaders(['Accept' => 'application/json, text/event-stream', 'X-Hub-Delegation' => $delegation])
            ->timeout(30)
            ->post((string) config('mcp_hub.mcp_url'), [
                'jsonrpc' => '2.0',
                'id' => (string) Str::uuid(),
                'method' => $method,
                'params' => (object) $params,
            ])
            ->throw()
            ->json();

        if (isset($response['error'])) {
            throw new RuntimeException($response['error']['message'] ?? 'The MCP request failed.');
        }

        return $response['result'] ?? [];
    }
}`,
      },
      {
        path: "usage.php",
        lang: "php",
        kind: "snippet",
        caption: "Example: in a controller or job",
        code: String.raw`$hub = app(\App\Services\McpHubClient::class);

$tools = $hub->tools($request->user());               // what this user's assistant may call
$report = $hub->call($request->user(), 'run_report', [
    'source' => 'orders',                               // a key from list_data_sources
    'group_by' => ['status'],
    'metrics' => [['fn' => 'count']],
]);`,
      },
    ],
    after: [
      "MCP clients such as Claude or Cursor need only the endpoint and the client key. Data that requires a user (most of it) also needs the delegation header, which is why an app gateway is the usual way in.",
      "Skills the Hub admin wrote for your app come from `prompts()` and `prompt()`: show them as commands in your chat, and send the returned text as the user's message. When memory is turned on for the app, the agent also gets `recall_memory`, `save_memory` and `forget_memory`; they work only with the delegation header, so each user keeps their own memory.",
    ],
  },
  {
    id: "chat",
    title: "Add an AI chat with your own UI (optional)",
    step: 9,
    body: [
      "The Hub can run the whole chat for you: the model, your app's tools, the rules and the tool switches. Turn it on in the app's **Chat** tab in the Hub, then design the chat window your way (Blade, Livewire, Vue, React). Your server calls the Hub with the client key and the signed-in user and streams the answer to the browser, so the key never reaches the page.",
      "The Hub stores no conversation. Keep the messages in your page (or your own database) and send the visible history with each new message.",
    ],
    files: [
      {
        path: "app/Http/Controllers/AiChatController.php",
        lang: "php",
        kind: "file",
        code: String.raw`<?php

namespace App\Http\Controllers;

use App\Support\HubToken;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use Symfony\Component\HttpFoundation\StreamedResponse;

/** Streams the Hub's AI chat to a chat window you design. The client key stays on this server. */
class AiChatController extends Controller
{
    /** Welcome message, suggested questions and skills for the chat window. */
    public function config(): JsonResponse
    {
        $response = $this->hub()->timeout(15)->get('/chat/v1/config');

        return response()->json($response->json(), $response->status());
    }

    public function turn(Request $request)
    {
        $body = $request->validate([
            'message' => ['nullable', 'string', 'max:4000'],
            'history' => ['array', 'max:40'],
            'history.*.role' => ['required', 'in:user,assistant'],
            'history.*.text' => ['required', 'string', 'max:8000'],
            'skill' => ['nullable', 'string', 'max:64'],
            'skill_arguments' => ['array', 'max:5'],
        ]);
        $user = HubToken::sign(['app_key' => config('mcp_hub.app_key'), 'aud' => 'mcp-hub'] + HubToken::subject($request->user()));

        $response = $this->hub()
            ->withOptions(['stream' => true])
            ->withHeaders(['Accept' => 'text/event-stream', 'X-Hub-Delegation' => $user])
            ->timeout(120)
            ->post('/chat/v1/turn', [
                'message' => $body['message'] ?? '',
                'history' => $body['history'] ?? [],
                'skill' => $body['skill'] ?? null,
                'skill_arguments' => (object) ($body['skill_arguments'] ?? []),
                'locale' => substr(app()->getLocale(), 0, 2),
            ]);

        if ($response->status() !== 200) {
            // Refused before the answer started: CHAT_DISABLED, PII_DETECTED, RATE_LIMITED, DAILY_LIMIT, ...
            return response()->json($response->json(), $response->status());
        }

        $stream = $response->toPsrResponse()->getBody();

        return new StreamedResponse(function () use ($stream) {
            while (! $stream->eof()) {
                echo $stream->read(2048);
                if (ob_get_level() > 0) {
                    ob_flush();
                }
                flush();
            }
        }, 200, ['Content-Type' => 'text/event-stream', 'Cache-Control' => 'no-cache', 'X-Accel-Buffering' => 'no']);
    }

    private function hub()
    {
        $hub = preg_replace('#/mcp/?$#', '', (string) config('mcp_hub.mcp_url'));

        return Http::baseUrl($hub)->withToken((string) config('mcp_hub.client_key'))->acceptJson();
    }
}`,
      },
      {
        path: "routes/web.php",
        lang: "php",
        kind: "snippet",
        caption: "For signed-in users only",
        code: String.raw`use App\Http\Controllers\AiChatController;

Route::middleware('auth')->group(function () {
    Route::get('/ai/chat/config', [AiChatController::class, 'config']);
    Route::post('/ai/chat', [AiChatController::class, 'turn'])->middleware('throttle:30,1');
});`,
      },
      {
        path: "resources/js/ai-chat.js",
        lang: "js",
        kind: "file",
        caption: "Reads the streamed answer; you decide how it looks",
        code: String.raw`// Sends one message to your own route and hands each streamed event to your UI.
const csrf = () => document.querySelector('meta[name="csrf-token"]').content;

export async function askAssistant({ message, history = [], skill = null, skillArguments = {} }, on = {}) {
  const response = await fetch("/ai/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "X-CSRF-TOKEN": csrf(),
    },
    body: JSON.stringify({ message, history, skill, skill_arguments: skillArguments }),
  });
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    on.error?.(failure.error ?? { code: "HTTP_" + response.status, message: "The assistant could not answer." });
    return;
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = block.match(/^event: (.*)$/m)?.[1];
      const data = block.match(/^data: (.*)$/m)?.[1];
      if (event && data) on[event]?.(JSON.parse(data));
    }
  }
}

// Applies (or cancels) a change the assistant prepared; resolves with the message to show.
export async function decideProposal(ref, confirm = true) {
  const response = await fetch("/hub/proposals/" + encodeURIComponent(ref) + (confirm ? "/confirm" : ""), {
    method: confirm ? "POST" : "DELETE",
    headers: { Accept: "application/json", "X-CSRF-TOKEN": csrf() },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.message ?? body.error?.message ?? "The change could not be applied.");
  return body.data?.message ?? "";
}

// Example:
// askAssistant({ message: "How many orders are pending?", history }, {
//   text: ({ delta }) => { answer += delta; render(answer); },   // Markdown, streamed piece by piece
//   tool: ({ title, status }) => showStep(title, status),       // running, done or error
//   proposal: ({ data }) => showConfirmCard(data[0].summary, {     // Confirm and Cancel buttons:
//     confirm: () => decideProposal(data[0].proposal_ref),          // POST /hub/proposals/{ref}/confirm
//     cancel: () => decideProposal(data[0].proposal_ref, false),    // DELETE /hub/proposals/{ref}
//   }),
//   notice: ({ message }) => showNote(message),
//   error: ({ message }) => showError(message),
// });`,
      },
    ],
    table: {
      head: ["Event", "Data"],
      rows: [
        ["`start`", "`{trace_id}`"],
        ["`text`", "`{delta}`: the next piece of the answer, in Markdown"],
        ["`tool`", "`{id, name, title, status: running | done | error, error?}`"],
        ["`proposal`", "`{tool, title, operation, data: [{proposal_ref, summary}]}`: a change your write route prepared. Show the summary with Confirm and Cancel, and call `decideProposal()`"],
        ["`notice`", "`{code, message}`, for example the step limit was reached"],
        ["`error`", "`{code, message, trace_id}`"],
        ["`done`", "`{trace_id, steps, tools, proposals, notices}`"],
      ],
    },
    after: [
      "`GET /ai/chat/config` returns the welcome message, suggested questions and the skills this key can run: show skills as commands and send their `key` as `skill` (with `skill_arguments`) instead of, or together with, a message.",
      "Messages with personal data are refused before they reach the model (`PII_DETECTED`): tell the user to use your app's forms for that. On Windows, `php artisan serve` handles one request at a time and the chat waits while the Hub calls your routes back; use Herd, Laragon, Valet or Sail, or a second `php artisan serve` as the Hub's Base URL.",
    ],
  },
  {
    id: "test",
    title: "Test it",
    step: 10,
    body: ["Check the routes from your machine before connecting, then keep the whole contract, including every write, under test."],
    files: [
      {
        path: "terminal",
        lang: "bash",
        kind: "snippet",
        caption: "Both should answer JSON, not HTML",
        code: String.raw`curl -s https://app.example.com/api/ai/v1/health -H "Authorization: Bearer $MCP_HUB_APP_TOKEN"
curl -s https://app.example.com/api/ai/v1/capabilities -H "Authorization: Bearer $MCP_HUB_APP_TOKEN"`,
      },
      {
        path: "tests/Feature/HubContractTest.php",
        lang: "php",
        kind: "file",
        code: String.raw`<?php

namespace Tests\Feature;

use App\Models\HubProposal;
use App\Models\Order;
use App\Models\User;
use App\Support\HubToken;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class HubContractTest extends TestCase
{
    use RefreshDatabase;

    private array $token = ['Authorization' => 'Bearer test-app-token'];

    protected function setUp(): void
    {
        parent::setUp();

        config([
            'mcp_hub.app_key' => 'your_app',
            'mcp_hub.base_url' => 'https://app.test',
            'mcp_hub.app_token' => 'test-app-token',
            'mcp_hub.delegation_secret' => 'test-delegation-secret',
        ]);
    }

    /** What the Hub sends for a request on this user's behalf. */
    private function hub(User $user, array $extra = []): array
    {
        $assertion = HubToken::sign(['app_key' => 'your_app', 'aud' => 'https://app.test'] + HubToken::subject($user), 60);

        return $this->token + ['X-Hub-Assertion' => $assertion] + $extra;
    }

    private function order(User $user, array $values = []): Order
    {
        return Order::create($values + ['user_id' => $user->id, 'number' => 'ORD-'.fake()->unique()->numberBetween(1000, 9999),
            'status' => 'open', 'total' => 100]);
    }

    public function test_every_route_requires_the_hub_bearer_token(): void
    {
        $this->getJson('/api/ai/v1/health')->assertStatus(401);
        $this->getJson('/api/ai/v1/health', ['X-API-Key' => 'test-app-token'])->assertStatus(401);
        $this->getJson('/api/ai/v1/health', $this->token)->assertOk()->assertJson(['status' => 'ok'])
            ->assertHeader('X-Content-Type-Options', 'nosniff');
        config(['mcp_hub.require_https' => true]);
        $this->getJson('/api/ai/v1/health', $this->token)->assertStatus(401);
        $this->getJson('https://app.test/api/ai/v1/health', $this->token)->assertOk();
    }

    public function test_a_hub_assertion_works_once(): void
    {
        $ana = User::factory()->create();
        $this->order($ana);
        $headers = $this->hub($ana);

        $this->getJson('/api/ai/v1/orders/list', $headers)->assertOk();
        $this->getJson('/api/ai/v1/orders/list', $headers)->assertStatus(403);
    }

    public function test_the_manifest_declares_read_and_write_routes(): void
    {
        $module = $this->getJson('/api/ai/v1/capabilities', $this->token)->assertOk()
            ->assertJsonPath('application', 'your_app')->json('modules.0');

        $this->assertSame(['read', 'create', 'update', 'delete'], $module['supported_operations']);
        $this->assertSame(['create', 'update', 'delete'], array_column($module['write_endpoints'], 'operation'));
    }

    public function test_reads_return_only_the_users_own_orders(): void
    {
        [$ana, $budi] = User::factory()->count(2)->create();
        $own = $this->order($ana, ['status' => 'paid']);
        $this->order($ana);
        $other = $this->order($budi);

        $this->getJson('/api/ai/v1/orders/list', $this->token)->assertStatus(403);
        $this->getJson('/api/ai/v1/orders/list?status=paid', $this->hub($ana))->assertOk()
            ->assertJsonCount(1, 'data')->assertJsonPath('data.0.ref', 'ord_'.$own->id);
        $this->getJson('/api/ai/v1/orders/list?user_id=2', $this->hub($ana))->assertStatus(422);
        $this->getJson('/api/ai/v1/orders/ord_'.$own->id, $this->hub($ana))->assertOk()->assertJsonPath('data.0.status', 'paid');
        $this->getJson('/api/ai/v1/orders/ord_'.$other->id, $this->hub($ana))->assertStatus(404);
    }

    public function test_creating_waits_for_the_user_to_confirm(): void
    {
        [$ana, $budi] = User::factory()->count(2)->create();
        $body = ['number' => 'ORD-2001', 'total' => 250, 'note' => 'Rush delivery'];

        $first = $this->postJson('/api/ai/v1/orders/propose-create', $body, $this->hub($ana, ['Idempotency-Key' => 'tr_1']))
            ->assertOk()->assertJsonPath('meta.requires_confirmation', true)->json('data.0');
        $again = $this->postJson('/api/ai/v1/orders/propose-create', $body, $this->hub($ana, ['Idempotency-Key' => 'tr_1']))->json('data.0');
        $this->assertSame($first['proposal_ref'], $again['proposal_ref']);
        $this->assertSame(0, Order::count());

        $this->actingAs($budi)->postJson("/hub/proposals/{$first['proposal_ref']}/confirm")->assertStatus(404);
        $this->actingAs($ana)->postJson("/hub/proposals/{$first['proposal_ref']}/confirm")->assertOk()
            ->assertJsonPath('data.message', 'Order ORD-2001 created.');
        $this->assertSame([$ana->id, 'open'], [Order::first()->user_id, Order::first()->status]);
        $this->actingAs($ana)->postJson("/hub/proposals/{$first['proposal_ref']}/confirm")->assertStatus(404);
    }

    public function test_updating_and_deleting_wait_for_the_user_too(): void
    {
        [$ana, $budi] = User::factory()->count(2)->create();
        $order = $this->order($ana);

        $this->postJson("/api/ai/v1/orders/ord_{$order->id}/propose-update", ['status' => 'paid'], $this->hub($budi))->assertStatus(404);
        $update = $this->postJson("/api/ai/v1/orders/ord_{$order->id}/propose-update", ['status' => 'paid'], $this->hub($ana))
            ->assertOk()->json('data.0');
        $this->assertStringContainsString('status open → paid', $update['summary']);
        $this->assertSame('open', $order->fresh()->status);
        $this->actingAs($ana)->postJson("/hub/proposals/{$update['proposal_ref']}/confirm")->assertOk();
        $this->assertSame('paid', $order->fresh()->status);

        $delete = $this->postJson("/api/ai/v1/orders/ord_{$order->id}/propose-delete", [], $this->hub($ana))->json('data.0');
        $this->actingAs($ana)->deleteJson("/hub/proposals/{$delete['proposal_ref']}")->assertOk();
        $this->assertNotNull($order->fresh());
        $delete = $this->postJson("/api/ai/v1/orders/ord_{$order->id}/propose-delete", [], $this->hub($ana))->json('data.0');
        $this->actingAs($ana)->postJson("/hub/proposals/{$delete['proposal_ref']}/confirm")->assertOk();
        $this->assertNull($order->fresh());
        $this->assertSame(['applied', 'cancelled', 'applied'], HubProposal::orderBy('id')->pluck('status')->all());
    }

    public function test_invalid_changes_are_refused(): void
    {
        $ana = User::factory()->create();
        $order = $this->order($ana);

        $this->postJson('/api/ai/v1/orders/propose-create', ['number' => 'ORD-1'], $this->hub($ana))->assertStatus(422);
        $this->postJson('/api/ai/v1/orders/propose-create', ['number' => 'ORD-1', 'total' => 5, 'user_id' => 9], $this->hub($ana))->assertStatus(422);
        $this->postJson("/api/ai/v1/orders/ord_{$order->id}/propose-update", ['status' => 'lost'], $this->hub($ana))->assertStatus(422);
        $this->postJson("/api/ai/v1/orders/ord_{$order->id}/propose-update", [], $this->hub($ana))->assertStatus(422);
    }
}`,
      },
    ],
    after: ["Run `php artisan test --filter=HubContractTest`."],
  },
  {
    id: "troubleshooting",
    title: "Troubleshooting",
    body: ["What the Hub reports, and where to look:"],
    table: {
      head: ["In the Hub", "Usual cause", "Fix"],
      rows: [
        ["The application rejected the bearer token", "The `Authorization: Bearer` token does not match, or a proxy drops the header", "Compare `MCP_HUB_APP_TOKEN` with the token saved on the app's API keys tab, then run `php artisan config:clear`. Behind Apache, make sure the `Authorization` header is passed to PHP."],
        ["Answered, but not with {\"status\": \"ok\"}", "The route returned HTML: a redirect to login or a 404 page", "Run `php artisan route:list --path=ai`. On Laravel 11+, run `php artisan install:api`."],
        ["Contract sync fails on the application key", "`MCP_HUB_APP_KEY` differs from the Hub's app key", "Use the same lowercase key in both places."],
        ["`PERMISSION_DENIED` on user data", "Wrong delegation secret, expired token or audience mismatch", "Make `MCP_HUB_BASE_URL` match the Hub's base URL exactly, and keep server clocks in sync (NTP)."],
        ["`SCHEMA_MISMATCH`", "A response field or type is not in `output_schema`", "Return declared fields only, with the declared types."],
        ["`UPSTREAM_ERROR`", "An error code outside the contract, or an exception page", "Return the `{success: false, error: {code, message}}` envelope."],
      ],
    },
  },
  {
    id: "security",
    title: "Security checklist",
    body: ["Before going to production:"],
    list: [
      "Keep `MCP_HUB_APP_TOKEN` and `MCP_HUB_DELEGATION_SECRET` in `.env` or a secret manager, never in Git. Rotate them from the app's API keys tab.",
      "Take the user from `X-Hub-Assertion` only. Ignore any `user_id`, `tenant_id` or role sent as a tool argument.",
      "Check the user's permissions and record ownership on every request, as your own UI does.",
      "Select declared fields explicitly. Never return `Model::all()` or `toArray()` of a whole model.",
      "Never apply a write on the Hub's request: store a proposal, let the signed-in user confirm it, check the rules again when they do, and honour `Idempotency-Key`.",
      "Confirm and cancel only the current user's pending proposals, inside a transaction, so a proposal is applied at most once.",
      "Serve the routes over HTTPS and keep the `throttle` middleware on them.",
    ],
  },
];

/** Every code block with a real path, for the starter kit. Snippets are kept apart so nothing overwrites a project file. */
export function kitFiles(mcpUrl: string): { path: string; content: string }[] {
  const files: { path: string; content: string }[] = [];
  for (const section of SECTIONS) {
    for (const file of section.files ?? []) {
      if (file.path === "terminal" || file.path === "usage.php") continue;
      const content = withMcpUrl(file.code, mcpUrl) + "\n";
      files.push(file.kind === "file" ? { path: file.path, content }
        : { path: `snippets/${file.path.replace(/^\./, "dot-").replace(/\//g, "__")}${file.path.endsWith(".php") ? "" : ".txt"}`, content });
    }
  }
  files.push({ path: "MCP_HUB_LARAVEL_GUIDE.md", content: guideMarkdown(mcpUrl) });
  return files;
}

export function guideMarkdown(mcpUrl: string): string {
  return renderMarkdown(GUIDE, SECTIONS, mcpUrl);
}
