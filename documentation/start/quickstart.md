# Jalur implementasi

Pilih titik awal sesuai komponen yang sudah tersedia. Contoh menggunakan domain `example.com` dan app key `your_app`; ganti dengan identitas environment Anda.

## Memulai dari awal

1. [Jalankan Hub lokal](../hub/local.md) dan masuk ke admin UI.
2. Daftarkan URL sumber dan app key yang stabil.
3. [Pasang package Laravel](../laravel/install.md) pada aplikasi uji.
4. Selesaikan [pairing](../laravel/connection.md).
5. Implementasikan resolver/policy dan tinjau [resource](../laravel/resources.md).
6. Buat client key read-only dan verifikasi katalog serta scope pengguna.

## Hub sudah tersedia

```bash
composer require ardanayatraa/laravel-mcp-hub:^1.0
php artisan mcp-hub:install --dry-run --migrate
php artisan mcp-hub:install --migrate
php artisan mcp-hub:connect --hub=https://hub.example.com
php artisan mcp-hub:doctor --online
```

Masukkan pairing code melalui prompt tersembunyi. Hub harus dapat menjangkau URL aplikasi. Produksi memerlukan `--force` untuk menjalankan migrasi setelah proses backup/review host.

!!! note "Resource kosong adalah kondisi awal yang benar"
    Instalasi tidak otomatis mengekspos tabel. Katalog berisi resource setelah developer menetapkan model, field, identitas, dan policy yang sah.

## Kriteria integrasi pertama selesai

- Health dan Doctor menunjukkan kondisi siap.
- Client hanya melihat resource yang ditinjau.
- Pengguna/tenant A tidak dapat membaca record milik B.
- Pencabutan izin menolak permintaan berikutnya.
- Model allowlist dan budget tersedia jika memakai gateway/chat.

Setelah read berjalan, tambahkan [proposal CRUD](../laravel/commands.md) atau [ekspor privat](../laravel/exports.md) sesuai kebutuhan.
