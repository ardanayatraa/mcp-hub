# Chat, settings, and the server SDK

The package provides `/mcp-hub` for settings and `/mcp-hub/chat` for chat. Access follows the host application's identity and permissions.

## Application Gates

| Configuration | Default Gate | Purpose |
|---|---|---|
| `web.manage_gate` | `mcp-hub.manage` | Connections and grants |
| `web.chat_gate` | `mcp-hub.chat` | Chat pages and actions |
| `web.export_gate` | `mcp-hub.export` | Private downloads |

Define these Gates using your application's permission system. Missing Gates deny access. Do not treat every signed-in user as an administrator. `web.guard` can follow the host's selected guard.

Routes use sessions, CSRF and origin checks, bounded input, local assets, and a Content Security Policy. Browsers never receive Hub or provider keys.

## Gateway SDK

Run this example inside an authenticated controller or route with a correctly implemented host resolver:

```php
use McpHub\Laravel\Gateway;

$user = auth()->user();
$gateway = app(Gateway::class);
$models = $gateway->models($user);
$config = $gateway->chatConfig($user);
$answer = $gateway->turn($user, [
    'message' => 'Summarize the orders I am allowed to access.',
    'history' => [],
    'locale' => 'en',
]);
```

`turn()` returns non-streaming JSON answer data. For application-managed orchestration, `complete($user, $input)` accepts an allowed model and validated messages. Hub allowlists and budgets still apply.

## MCP SDK

```php
use McpHub\Laravel\HubClient;
use McpHub\Laravel\Security\Assertions;

$catalog = app(HubClient::class)->rpc('tools/list');
$delegation = app(Assertions::class)->delegate(auth()->user());
// Read tool names and argument schemas from the catalog.
```

For `tools/call`, send `X-Hub-Delegation` through the `rpc` headers parameter. The client bounds response size and time, validates response IDs, and supports Hub JSON and SSE. It is not a general-purpose client for every MCP server.

## Proposal and report UI

Present proposals as awaiting user approval. The widget constructs same-origin download links from validated structured export references; never extract download links from model prose.

[Configure Hub models](../hub/chat.md) · [Gateway interface](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.1/src/Gateway.php)
