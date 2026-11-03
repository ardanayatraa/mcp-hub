# Ekspor laporan privat

CSV, XLSX, dan PDF dibuat di Laravel. Hub hanya menerima receipt/status job, bukan file laporan. Ini terpisah dari analitik JSON `run_report`.

## Aktivasi

```php
'exports' => [
    'enabled' => true,
    'ttl' => 600,
    'connection' => 'database',
    'queue' => 'default',
],
```

Pada resource yang ditinjau, tambahkan format `exports`, misalnya `['csv', 'xlsx', 'pdf']`. Policy harus mengizinkan `list` dan `export` untuk actor saat ini. Definisikan export Gate dan migrasikan metadata package.

Backend queue host harus tersedia; package tidak membuat infrastrukturnya. Contoh backend database:

```bash
php artisan queue:work database --queue=default --tries=1 --timeout=60
```

Produksi menolak driver `sync`. Atur `retry_after` lebih besar dari timeout worker, misalnya 90 detik untuk timeout 60 detik.

## Batas default

| Batas | Nilai |
|---|---|
| TTL | 30–900 detik; default 600 |
| Active exports | 2 per actor, 40 per instalasi |
| Record | 1–500; default 200 |
| PDF | Maksimal 100 record |
| Kolom | Maksimal 10 field yang ditinjau |
| File | Maksimal 5 MiB |

```json
{"format":"xlsx","columns":"title,status,total","limit":200,"status":"paid"}
```

POST memerlukan assertion baru dan `Idempotency-Key` 16–128 karakter huruf/angka/underscore/hyphen. Tidak menerima query string atau input di luar schema. Aggregate terbatas pada record yang dipilih; `coverage: partial` bukan total populasi lengkap.

## Storage dan download

Web/queue workers berbagi database, APP_KEY, config, dan private filesystem `storage/app/mcp-hub`. File terenkripsi dan tidak boleh dipublikasi/symlink ke public disk. Worker dengan storage lokal independen tidak didukung alur ini.

Download memeriksa session, Gate, actor/tenant, grants, format, expiry, serta snapshot query/record saat ini. Link saja tidak memberi akses. Data/grants berubah menghasilkan conflict dan memerlukan export baru; expired download menghasilkan 410.

Worker crash dapat meninggalkan job tidak tersedia sampai expiry. Buat request/key baru, bukan replay job manual. Jalankan scheduler host untuk prune berkala.

[Kontrak ekspor lengkap](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/EXPORTS.md)
