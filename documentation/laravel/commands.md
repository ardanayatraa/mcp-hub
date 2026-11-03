# Proposal CRUD dengan persetujuan

Create/update/delete memakai proposal yang ditinjau pengguna dalam sesi aplikasi. Pembuatan proposal tidak mengubah record bisnis.

## Syarat aktivasi

Koneksi aktif, `commands.enabled`, resource/operasi aktif, schema scalar tertutup, handler eksplisit, policy saat ini, dan write scope key semuanya harus mengizinkan aksi.

Implementasikan `CommandHandler` milik aplikasi. `EloquentCommands` tersedia untuk transaksi Eloquent generik; `WritePolicy` memvalidasi nilai bisnis dan menyediakan atribut ownership/default dari server. Mulai dari definisi hasil generator yang nonaktif.

## Alur transaksi

1. Hub meminta proposal menggunakan assertion actor sekali pakai.
2. Aplikasi memvalidasi input/scope dan menyimpan payload terenkripsi dengan expiry.
3. Receipt mengembalikan `proposal_ref` berstatus `pending`.
4. Pengguna meninjau nilai canonical pada `/mcp-hub/proposals/{proposal}`.
5. Approval/cancel memerlukan sesi actor/tenant yang tepat dan CSRF.
6. Commit mengunci proposal, memeriksa izin/schema/versi record kembali, lalu menjalankan perubahan dan mencatat receipt dalam transaksi yang sama.

| Method | Route default | Hasil |
|---|---|---|
| POST | `/api/ai/v1/{resource}/commands/{operation}` | Proposal expiring |
| GET | `/api/ai/v1/{resource}/commands/{proposal}` | Receipt actor-bound |
| POST | `/mcp-hub/proposals/{proposal}` | Keputusan pengguna melalui sesi web |

Operasi terbatas `create`, `update`, dan `delete`. Model tidak boleh mengirim `approved`, user ID, tenant ID, atau endpoint tujuan untuk menentukan otorisasi.

## Idempotency dan conflict

Key yang sama dengan payload yang sama mengembalikan receipt existing; payload berbeda ditolak. Approval ulang terhadap proposal committed tidak mengulangi write.

Pending bukan keberhasilan bisnis. Proposal expired, izin dicabut, konfigurasi berubah, atau versi record conflict dapat membutuhkan proposal baru. UI tidak boleh otomatis menampilkan committed dari receipt pending.

!!! warning "Efek eksternal adalah tanggung jawab aplikasi"
    Rollback database tidak membatalkan email, HTTP request, atau efek observer yang sudah dikirim. Gunakan transactional outbox host untuk efek eksternal. Handler generik membutuhkan koneksi transaksi default yang sama dengan metadata package.

[Interface handler dan WritePolicy](https://github.com/ardanayatraa/laravel-mcp-hub/tree/v1.0.0/src/Contracts)
