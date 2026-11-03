# Instalasi Laravel 1.0

Package `ardanayatraa/laravel-mcp-hub` menyediakan connector sumber dan SDK server untuk aplikasi Laravel. Package tidak mengasumsikan user model, tabel bisnis, permission package, atau sistem billing tertentu.

## Prasyarat

Gunakan PHP/framework sesuai [matriks kompatibilitas](../start/releases.md), Composer, serta ekstensi yang diminta dependency resolver. Sediakan `APP_KEY` tetap, database metadata, Hub yang dapat dijangkau aplikasi, serta URL sumber yang dapat dijangkau Hub.

```bash
composer require ardanayatraa/laravel-mcp-hub:^1.0
php artisan mcp-hub:install --dry-run --migrate
```

Tinjau rencana, lalu jalankan:

```bash
php artisan mcp-hub:install --migrate
```

Produksi memerlukan `--migrate --force` setelah backup/review normal aplikasi. Perintah ini hanya menjalankan file migrasi package; migrasi bisnis dan schema dump aplikasi tidak dijalankan olehnya.

## Artefak instalasi

| Artefak | Isi |
|---|---|
| `config/mcp-hub.php` | Konfigurasi awal, hanya bila file belum ada |
| `mcp_hub_nonces` | Pencegahan replay menggunakan uniqueness SQL |
| `mcp_hub_commands` | Proposal dan receipt transaksi |
| `mcp_hub_exports` | Metadata laporan privat |

Laravel menemukan provider melalui package discovery. Jika host menonaktifkan discovery, daftarkan `McpHub\Laravel\McpHubServiceProvider` melalui mekanisme provider versi Laravel Anda.

## Kondisi awal

Resolver default menolak identitas, model registry kosong, serta writes/exports mati. Instalasi tidak membuka data otomatis. Implementasikan resolver dan policy sebelum mengaktifkan resource.

```bash
php artisan mcp-hub:doctor
php artisan mcp-hub:status
```

Doctor bisa melaporkan konfigurasi belum lengkap sebelum pairing. Lanjutkan ke [pairing dan konfigurasi](connection.md).

!!! note "Prototipe lokal adalah dependency berbeda"
    `mcp-hub/laravel-connector` merupakan pilot lama. Namespace PHP-nya sama dengan package publik, sehingga keduanya tidak boleh dipasang bersamaan. Tinjau dependency, route, dan integrasi host sebelum menggantinya.
