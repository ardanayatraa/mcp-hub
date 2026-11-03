# Produksi dan pemulihan

Gunakan HTTPS, PostgreSQL, Redis khusus, reverse proxy, dan pengelolaan secrets untuk Hub produksi. Tentukan ukuran server melalui pengukuran workload, bukan hasil CI.

## Konfigurasi pokok

| Pengaturan | Tujuan |
|---|---|
| `ENVIRONMENT=production` | Pemeriksaan konfigurasi produksi |
| `DATABASE_URL` | PostgreSQL dengan akun layanan terbatas |
| `SECRET_ENCRYPTION_KEY` | Membaca credentials terenkripsi; diperlukan saat restore |
| `SESSION_SIGNING_KEY` | Signature sesi dengan key acak kuat |
| `COOKIE_SECURE=true` | Cookie melalui HTTPS saja |
| `RATE_LIMIT_BACKEND=redis` | Counter bersama antar proses |
| Redis URL/password/namespace | Redis privat, autentikasi kuat, state pembatas konsisten |
| `ALLOWED_HOSTS`, `ALLOWED_ORIGINS` | Domain/origin yang sah |
| `MCP_PUBLIC_URL`, `MCP_ISSUER_URL` | Identitas endpoint publik |
| `EGRESS_ALLOWED_HOSTS` / `EGRESS_ALLOWED_CIDRS` | Sumber yang boleh dihubungi |
| `FORWARDED_ALLOW_IPS` | Proxy terpercaya saja |

Produksi menolak konfigurasi tidak aman. Jangan menyelesaikan readiness error dengan bypass HTTP/TLS atau in-memory limits.

## Build dan deployment

Gunakan lock file backend/frontend. Jalankan Alembic sesuai prosedur deployment; backend menolak schema tertinggal. Proxy melayani `/api/`, `/mcp`, `/chat/`, `/gateway/`, `/health`, dan `/ready`, bersama aset frontend.

`infra/compose.yml` adalah development stack. Gunakan [deployment guide lengkap](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/DEPLOY.md) atau [panduan aaPanel](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/DEPLOY_AAPANEL_OTOMATIS.md) untuk deployment terjaga. Secrets dan konfigurasi panel tetap dikelola server.

## Admin dan operasi

Root memakai authenticator MFA di produksi. Siapkan SMTP TLS sebelum mengundang anggota, berikan scope sesuai peran, dan atur model allowlist/budget setiap aplikasi. Pantau readiness, error code, trace ID, dan metadata audit tanpa mencatat payload bisnis/secrets.

## Backup dan restore

Simpan database dump terlindungi di luar server dan uji restore ke database sementara. Pertahankan encryption key yang cocok; dump saja tidak cukup untuk membaca secrets.

Sebelum upgrade, simpan versi kode, lock file, konfigurasi, dan backup yang konsisten. Sesudah upgrade, periksa login/readiness/catalog serta operasi scoped dengan data sintetis. Jika gagal, gunakan rollback yang diuji, bukan penghapusan tabel otomatis.

[Backup dan rollback Hub](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/BACKUP.md) · [Pemeliharaan Laravel](../laravel/upgrade.md)
