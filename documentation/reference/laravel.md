# Artisan dan konfigurasi

## Perintah

| Perintah | Kegunaan |
|---|---|
| `mcp-hub:install --dry-run --migrate` | Preview config/migrasi package |
| `mcp-hub:install --migrate` | Config yang belum ada dan metadata SQL |
| `mcp-hub:connect --hub=...` | Pairing melalui prompt tersembunyi |
| `mcp-hub:connect --resume` | Lanjutkan proof tersimpan |
| `mcp-hub:connect --hub=... --replace` | Pasang replacement admin |
| `mcp-hub:connect --import-env` | Import koneksi diprovisikan |
| `mcp-hub:status` | Metadata status tanpa secrets |
| `mcp-hub:doctor --online` | Diagnosis lokal dan koneksi Hub |
| `mcp-hub:sync` | Sync kontrak |
| `mcp-hub:disconnect` | Disable lokal dan revoke remote |
| `mcp-hub:discover --schema` | Kandidat dari metadata |
| `make:mcp-resource orders --model=...` | Definisi/policy nonaktif |
| `mcp-hub:prune --days=30` | Cleanup metadata/artifact |

Gunakan `php artisan help <command>` untuk seluruh opsi versi yang terpasang.

## Environment

| Variabel | Arti |
|---|---|
| `MCP_HUB_APP_KEY` | Identitas aplikasi |
| `MCP_HUB_ENVIRONMENT` | Environment koneksi |
| `MCP_HUB_BASE_URL` | URL sumber aplikasi |
| `MCP_HUB_URL` | Endpoint Hub `/mcp` |
| `MCP_HUB_CLIENT_KEY` | Laravel → Hub |
| `MCP_HUB_APP_TOKEN` | Hub → Laravel |
| `MCP_HUB_DELEGATION_SECRET` | Signature konteks actor |
| `MCP_HUB_ENABLED` | Override koneksi |
| `MCP_HUB_TIMEOUT` | Request umum; default 12 detik |
| `MCP_HUB_CHAT_TIMEOUT` | SDK chat; default 120 detik |

Environment yang mempunyai nilai tetap mengungguli bundle tersimpan. Jangan mencetak environment untuk troubleshooting; diagnosis harus menyembunyikan secrets.

## Config

| Key | Default/perilaku |
|---|---|
| `models` | Kosong |
| `actor_resolver` | Resolver penolak akses |
| `routes.enabled`, `routes.prefix` | `true`, `api/ai/v1` |
| `web.enabled`, `web.prefix` | `true`, `mcp-hub`; tetap dilindungi Gate |
| `commands.enabled`, `commands.ttl` | `false`, 300 detik |
| `exports.enabled`, `exports.ttl` | `false`, 600 detik |
| `record_references` | `opaque` |
| `maintenance.scheduled_prune` | `true`; host scheduler harus berjalan |

Gunakan scalar, array, dan class string agar kompatibel dengan `config:cache`. Lihat [config rilis 1.0.0](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/config/mcp-hub.php).
