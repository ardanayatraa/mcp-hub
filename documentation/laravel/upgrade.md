# Upgrade dan pemeliharaan

Composer update adalah bagian dari proses rilis aplikasi, bukan pengganti review konfigurasi/migrasi produksi.

## Alpha ke 1.0

1. Simpan backup database, lock file, config, resource definitions, dan private storage yang konsisten.
2. Pertahankan APP_KEY dan credentials melalui secret management host.
3. Perbarui dependency ke `ardanayatraa/laravel-mcp-hub:^1.0` dalam build yang ditinjau.
4. Periksa conflicts/audit tanpa ignore-platform atau security bypass.
5. Tinjau dan jalankan metadata migrations.
6. Restart queue/long-running workers, lalu periksa Doctor/status sebelum switching traffic.

```bash
php artisan mcp-hub:install --dry-run --migrate
php artisan mcp-hub:install --migrate --force
php artisan mcp-hub:doctor --online
php artisan mcp-hub:status
```

`--force` diperlukan untuk produksi setelah backup/review. Installer mempertahankan config existing; tambahkan optional keys tanpa mengganti seluruh file host.

## Integrasi existing

Jika host sudah memiliki connector routes, pertahankan `routes.enabled=false` sampai pengganti setara terverifikasi. Simpan resolver, registrasi resource, policy, scope, handler, dan UI host. Package generik tidak merekonstruksi permission bisnis.

Pending proposal dari snapshot development lama dapat perlu disiapkan ulang. Jangan memindahkan pending metadata lintas instalasi/environment. Reference 1.0 default opaque.

## Scheduler

Provider mendaftarkan prune setiap jam dengan overlap lock. Host tetap harus menjalankan scheduler Laravel.

```bash
php artisan mcp-hub:prune --days=30
```

Jika dijadwalkan host sendiri, atur `maintenance.scheduled_prune=false` agar tidak ganda. Retention terminal receipt menerima 1–365 hari; expired payload/artifact memiliki aturan cleanup sendiri. Perintah hanya menyentuh metadata/file package.

## Recovery

Rollback kode dan lock melalui prosedur host. Jangan otomatis downgrade schema atau menghapus tabel. Metadata baru boleh tetap tidak digunakan sampai penyebab diperiksa.

Rollback file tidak memulihkan credentials yang sudah dicabut. Gunakan pairing resume/replacement. APP_KEY rotation membutuhkan rencana pemulihan file dan queue tersendiri; package tidak merotasinya otomatis.

[Panduan upgrade/recovery lengkap](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/UPGRADE.md)
