# Chat, settings, dan SDK server

Package menyediakan `/mcp-hub` untuk settings dan `/mcp-hub/chat` untuk chat. Akses mengikuti permission dan identitas aplikasi host.

## Gate aplikasi

| Config | Gate default | Tujuan |
|---|---|---|
| `web.manage_gate` | `mcp-hub.manage` | Koneksi dan grants |
| `web.chat_gate` | `mcp-hub.chat` | Halaman/aksi chat |
| `web.export_gate` | `mcp-hub.export` | Download privat |

Definisikan Gate melalui sistem izin aplikasi. Gate yang hilang menolak akses. Jangan menganggap semua user login adalah admin. `web.guard` dapat mengikuti guard host.

Routes memakai session, CSRF/origin checks, batas input, aset lokal, dan CSP. Browser tidak menerima key Hub/provider.

## Gateway SDK

Contoh ini dijalankan dalam controller/route yang sudah diautentikasi dan memakai resolver host yang benar:

```php
use McpHub\Laravel\Gateway;

$user = auth()->user();
$gateway = app(Gateway::class);
$models = $gateway->models($user);
$config = $gateway->chatConfig($user);
$answer = $gateway->turn($user, [
    'message' => 'Ringkas pesanan yang boleh saya akses.',
    'history' => [],
    'locale' => 'id',
]);
```

`turn()` mengembalikan data jawaban JSON non-streaming. Untuk orchestration mandiri, `complete($user, $input)` menerima model dari katalog yang diizinkan dan messages tervalidasi. Allowlist/budget Hub tetap berlaku.

## MCP SDK

```php
use McpHub\Laravel\HubClient;
use McpHub\Laravel\Security\Assertions;

$catalog = app(HubClient::class)->rpc('tools/list');
$delegation = app(Assertions::class)->delegate(auth()->user());
// Ambil nama tool dan schema arguments dari katalog.
```

Pada `tools/call`, kirim `X-Hub-Delegation` melalui parameter headers `rpc`. Client membatasi ukuran/waktu, memeriksa response ID, dan mendukung JSON/SSE Hub. SDK ini bukan client umum untuk semua MCP server.

## UI proposal dan laporan

Tampilkan proposal sebagai menunggu persetujuan pengguna. Widget membangun download link same-origin dari structured export reference yang tervalidasi; jangan mengambil tautan dari prosa model.

[Konfigurasi model di Hub](../hub/chat.md) · [Interface Gateway](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/src/Gateway.php)
