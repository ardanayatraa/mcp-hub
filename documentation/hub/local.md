# Jalankan Hub secara lokal

Sediakan Python 3.12, uv, Node.js 22, dan pnpm. Gunakan environment dan port terpisah dari layanan yang sudah berjalan.

```bash
git clone https://github.com/ardanayatraa/mcp-hub.git
cd mcp-hub
```

## Launcher Windows

```powershell
.\dev.ps1
```

Alternatifnya, jalankan `dev.cmd`. Launcher menyiapkan dependensi yang belum tersedia dan membuat `dev.env` dengan key acak pada penggunaan pertama, lalu menjalankan migrasi, bootstrap admin, API, dan admin UI. Simpan kredensial hasil bootstrap secara privat.

Port mengikuti `HUB_PORT` dan `UI_PORT` pada environment. Launcher dapat menghentikan proses Hub/UI lama yang dikenalnya pada port tersebut. Gunakan port berbeda untuk instance paralel. Ctrl+C menghentikan instance yang Anda jalankan.

## Komponen manual

Siapkan konfigurasi development seperti pada [README repository](https://github.com/ardanayatraa/mcp-hub#quick-start-local-development): database SQLite, encryption key, session signing key, password admin, allowed hosts/origins, dan URL publik yang sesuai port.

Dari `backend`:

```bash
uv sync --frozen --group dev
uv run --frozen alembic upgrade head
uv run --frozen python -m app.bootstrap
uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 18080
```

Dari `frontend` pada terminal lain, arahkan proxy ke port backend yang sama:

=== "PowerShell"

    ```powershell
    $env:HUB_API_TARGET = "http://127.0.0.1:18080"
    pnpm install --frozen-lockfile
    pnpm dev --host 127.0.0.1 --port 15180
    ```

=== "Bash"

    ```bash
    export HUB_API_TARGET=http://127.0.0.1:18080
    pnpm install --frozen-lockfile
    pnpm dev --host 127.0.0.1 --port 15180
    ```

Samakan proxy frontend, allowed origins, dan URL MCP dengan port yang dipilih. Gunakan launcher untuk konfigurasi lokal yang dikelola otomatis.

## Verifikasi

Login ke admin UI, periksa `/health` serta `/ready`, daftarkan sumber uji, lalu buat client key read-only. Verifikasi katalog dengan actor sintetis sebelum mengaktifkan akses bisnis.

HTTP lokal, loopback egress, dan SQLite adalah pilihan development. Layanan publik mengikuti [panduan produksi](operations.md).
