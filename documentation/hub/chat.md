# Chat dan model gateway

Provider credentials tetap di Hub. Server aplikasi memakai key scoped; browser tidak menerima provider key, Hub client key, atau delegation secret.

| Pola | API | Penggunaan |
|---|---|---|
| Hub chat | `/chat/v1/config`, `/chat/v1/turn` | Percakapan dengan tools dan pengaturan Hub |
| Model gateway | `/gateway/v1/models`, `/gateway/v1/chat/completions` | Aplikasi mengelola orchestration sendiri |
| Laravel SDK/UI | `Gateway`, `/mcp-hub/chat` | Integrasi dengan resolver dan izin host |

## Konfigurasi

Tambahkan provider pada AI providers, simpan key, uji koneksi, lalu pilih provider/model di tab Chat aplikasi. Tetapkan allowlist model dan budget bulanan gateway. Aktifkan chat jika menggunakan Hub chat, kemudian panggil dari server dengan konteks actor.

!!! important "Akses model produksi harus dikonfigurasi"
    Produksi menolak discovery/completion sampai allowlist dan budget tersedia. Daftar kosong atau budget nol bukan akses tanpa batas.

## Riwayat dan memory

Hub chat tidak menyimpan riwayat percakapan secara persisten; history dikirim aplikasi pada request. Memory merupakan fitur terpisah, opsional, dan terenkripsi per pengguna. Audit metadata dan file laporan memiliki lifecycle yang berbeda.

SDK Laravel `Gateway::turn()` memakai JSON non-streaming. Kontrak streaming Hub tersedia pada [API reference](../reference/admin-api.md) bagi implementasi client sendiri.

Proposal pending harus ditampilkan sebagai menunggu pengguna. Persetujuan tetap berada dalam sesi aplikasi. Lihat [chat Laravel](../laravel/chat.md) dan [proposal CRUD](../laravel/commands.md).
