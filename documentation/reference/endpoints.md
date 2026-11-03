# Peta endpoint

Hub dan Laravel mempunyai host serta autentikasi berbeda. Bedakan keduanya saat menyiapkan koneksi atau debugging.

## Host Hub

| Prefix/endpoint | Pemanggil | Tujuan |
|---|---|---|
| `/api/admin/v1` | Admin UI/operator | Session + CSRF untuk konfigurasi/lifecycle |
| `/mcp` | MCP client/server aplikasi | Client key; delegation untuk pengguna |
| `/gateway/v1/models` | Server aplikasi | Model yang diizinkan |
| `/gateway/v1/chat/completions` | Server aplikasi | Completion berdasarkan policy gateway |
| `/chat/v1/config`, `/chat/v1/turn` | Server aplikasi | Chat Hub dengan konteks actor |
| `/health`, `/ready` | Probe | Kesehatan proses dan kesiapan |

## Host Laravel

Prefix berikut merupakan default yang dapat dikonfigurasi.

| Method | Route | Tujuan |
|---|---|---|
| GET | `/api/ai/v1/health` | Health dan metadata readiness |
| GET | `/api/ai/v1/capabilities` | Manifest/grants saat ini |
| GET | `/api/ai/v1/{resource}/list` | Pagination scoped |
| GET | `/api/ai/v1/{resource}/get` | Lookup exact scoped |
| GET | `/api/ai/v1/{resource}/count` | Count scoped |
| POST | `/api/ai/v1/{resource}/commands/{operation}` | Proposal CRUD |
| GET | `/api/ai/v1/{resource}/commands/{proposal}` | Receipt proposal |
| POST | `/api/ai/v1/{resource}/exports` | Job laporan privat |
| GET | `/api/ai/v1/{resource}/exports/{reference}` | Receipt export |
| GET | `/mcp-hub` | Settings dengan manage Gate |
| GET/POST | `/mcp-hub/chat` | Chat dengan chat Gate |
| GET/POST | `/mcp-hub/proposals/{proposal}` | Review dan keputusan pengguna |
| GET | `/mcp-hub/exports/{reference}` | Download privat dengan export Gate |

Endpoint sumber memakai service bearer token; actor-scoped operations juga memerlukan assertion sekali pakai. Endpoint web menggunakan session, Gate, dan CSRF pada mutation.

## Kontrak lengkap

- [Admin dan MCP API](admin-api.md): request fields, response, streaming, dan error.
- [Connector contract](connector-contract.md): manifest/schema dan identity.
- [Tools/reporting](tools.md): filters, metrics, pagination, dan coverage.
- [Artisan/config](laravel.md): konfigurasi aplikasi dan maintenance.
