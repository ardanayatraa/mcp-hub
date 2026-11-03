# Pemecahan masalah

Mulai dari `php artisan mcp-hub:status` dan `php artisan mcp-hub:doctor --online`. Catat error code, waktu, serta trace ID; hindari secrets dan payload bisnis.

| Gejala | Pemeriksaan | Tindakan |
|---|---|---|
| Doctor/health 503 | Metadata security tersedia? | Review dry-run dan jalankan migrasi package |
| Tools kosong | Registry/grants belum aktif? | Implementasikan resolver/policy, tinjau resource, sync |
| Source catalog unavailable | Manifest valid dan terjangkau? | Perbaiki sumber; refresh gagal tidak memakai izin lama |
| Source 401 | App token sama di dua sisi? | Tinjau provisioning tanpa mencetak token |
| Operasi pengguna 403 | Delegation, actor, policy, profil sah? | Uji akun/tenant dan izin terkini |
| Settings/chat 403 | Gate/guard host tersedia? | Definisikan Gate sesuai permission host |
| Mutation web 419 | Session dan CSRF satu aplikasi? | Perbaiki sesi/origin, jangan matikan CSRF |
| Pairing terputus | Proof terenkripsi tersimpan? | Jalankan `connect --resume` |
| Replacement tidak efektif | Env lama override bundle? | Tinjau pinned configuration melalui operator |
| Model kosong/ditolak | Allowlist dan budget tersedia? | Konfigurasikan akses model aplikasi |
| Proposal conflict/expired | Versi record/policy/expiry berubah? | Buat proposal baru, minta approval ulang |
| Export pending/failed | Worker, queue, storage siap? | Perbaiki worker; job crash perlu request/key baru |
| Download 409 | Snapshot data/grants berubah? | Buat export baru |
| Download 410 | TTL berakhir? | Buat export baru |
| Composer conflict | PHP/framework/Guzzle sesuai? | Review solver dan lock, tanpa bypass security/platform |

## Bedakan URL dan kredensial

`MCP_HUB_URL` menunjuk Hub `/mcp`. `MCP_HUB_BASE_URL` menunjuk sumber. Client key dipakai Laravel ke Hub; app token dipakai Hub ke Laravel. Delegation secret menandatangani actor dan bukan token API biasa.

## Pemeriksaan worker

Web/queue harus memakai release, config, APP_KEY, database, serta private filesystem yang sama. Restart worker sesuai prosedur host setelah perubahan. Perbarui cached configuration melalui proses deployment terkontrol.

## Laporan masalah

Sertakan versi package/server, PHP/Laravel, error code, dan reproduksi dengan data sintetis. Sebutkan apakah kasus berasal dari unit test, simulasi, staging, atau produksi. Hapus token, code, identitas pengguna, alamat internal, dan record bisnis dari laporan publik.
