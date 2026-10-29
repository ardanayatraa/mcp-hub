# PRD: Laravel MCP Hub Connector

| Atribut | Nilai |
|---|---|
| Versi dokumen | 0.2 |
| Tanggal | 28 Oktober 2026 |
| Status | Alpha tersedia; PRD mencakup target fitur berikutnya, termasuk pairing |
| Produk | Package Composer untuk menghubungkan aplikasi Laravel ke AI MCP Hub |
| Nama Composer | ardanayatraa/laravel-mcp-hub; rilis public MIT; dukungan lintas versi mulai v0.2.0-alpha.1 |
| Target awal | Telixmart, HiReach, Texcel, iSeeTalk, dan aplikasi Laravel berikutnya |
| Prioritas | Kompatibilitas, setup yang dapat diulang dengan aman, izin data, pemeliharaan terpusat |

Dokumen ini melengkapi [PRD utama Hub](../../../PRD.md). Implementasi public berada di [repository package](https://github.com/ardanayatraa/laravel-mcp-hub); cakupan aktual mengikuti README repository tersebut. Folder package ini adalah prototype pilot lokal. Kebutuhan di bawah tetap menjadi target produk, bukan klaim seluruh fitur sudah tersedia.

## 1. Ringkasan produk

Membangun satu produk package Laravel yang menyediakan connector API, klien Hub, pengaturan akses data, dan perintah Artisan. Developer cukup memasang melalui Composer, menjalankan installer, lalu menghubungkan aplikasi ke Hub sekali. Pembaruan berikutnya menggunakan Composer dan migrasi package tanpa menyalin controller, service, route, atau konfigurasi secara manual lagi.

Package menghubungkan dua arah komunikasi:

1. **Hub ke Laravel:** membaca manifest dan menjalankan tools atas data yang diizinkan.
2. **Laravel ke Hub:** mengirim konteks pengguna untuk MCP, chat, dan akses model melalui gateway Hub.

Database bisnis tetap berada di aplikasi Laravel. Hub tidak menerima akses database aplikasi. Model AI tidak menjadi sumber identitas atau otorisasi.

“Tanpa setup berulang” berarti otomatisasi pekerjaan integrasi yang sama. Pilihan resource, field, guard, dan aturan kepemilikan tetap ditetapkan sekali per aplikasi karena berbeda menurut bisnisnya.

## 2. Masalah dan kondisi sekarang

[Adapter saat ini](../README.md) berupa overlay khusus HiReach dengan skrip prepare, install, sync, configure, provision, dan verify. Proses tersebut bergantung pada snapshot file, hash, struktur aplikasi, dan beberapa service serta komponen UI milik aplikasi.

Masalah yang perlu diselesaikan:

- Integrasi baru memerlukan pemindahan dan penyesuaian file berulang.
- Perubahan adapter bisa berbenturan dengan perubahan aplikasi.
- Nama aplikasi, prefix cache, identitas pengguna, branding, dan permission belum seluruhnya generik.
- Setup masih melibatkan kredensial dan beberapa langkah manual di Laravel serta Hub.
- Laravel lama dan baru memiliki runtime, struktur aplikasi, serta dependency yang berbeda.

Dasar yang dapat digunakan kembali adalah Connector Contract 1.0 dan mode **source_managed**. Mode ini sudah mendukung sinkronisasi tools dari izin aplikasi sehingga tidak diperlukan konfigurasi ulang setiap model di Hub.

## 3. Baseline kompatibilitas yang ditemukan

Pemeriksaan dilakukan secara baca saja terhadap composer.json dan composer.lock proyek lokal pada tanggal dokumen.

| Aplikasi | Constraint Laravel | Versi di lockfile | Constraint PHP aplikasi | Implikasi |
|---|---|---|---|---|
| Telixmart | 5.8.* | 5.8.38 | ^7.1.3 | Dukungan legacy wajib; package tidak boleh langsung mensyaratkan PHP 8 |
| HiReach | ^9.2 | 9.52.21 | ^8.0.2 | Kompatibel dengan adapter dan Livewire 2 yang sudah ada |
| Texcel, sementara dipetakan ke folder telixcel | ^9.2 | 9.52.21 | ^8.0.2 | Nama dan identitas aplikasi harus configurable |
| iSeeTalk | ^12.0 | 12.52.0 | ^8.2 | Mendukung struktur Laravel modern dan frontend aplikasi yang berbeda |

Constraint PHP tersebut merupakan deklarasi proyek, bukan hasil pemeriksaan PHP server. Dependency dalam lockfile dapat memerlukan PHP lebih tinggi. Versi framework di lockfile juga belum membuktikan package bisa dipasang atau dijalankan.

**Asumsi yang perlu dikonfirmasi saat implementasi:** nama “Texcel” dari permintaan merujuk ke proyek lokal telixcel. Tidak ada perubahan pada proyek tersebut dalam penyusunan PRD.

### 3.1 Kebijakan versi package

Keputusan setelah compatibility spike: **satu nama Composer dan satu implementasi bersama**, dengan dukungan versi lama dipertahankan. Rencana awal dua jalur tidak diperlukan untuk cakupan connector alpha yang sudah diuji.

| Jalur | Target framework | Kebijakan runtime |
|---|---|---|
| Package 0.2 alpha | Laravel 5.8, 6, 7, 8, 9, 10, 11, 12, 13 | Minimum package PHP 7.2.5; minimum efektif mengikuti framework dan dependency aplikasi |
| Rilis berikutnya | Major Laravel setelah 13 | Ditambahkan setelah audit perubahan dan CI; tidak dijanjikan otomatis |

Semua versi memakai perintah, kontrak connector, dan perilaku keamanan yang sama. Composer memilih dependency yang cocok dengan constraint aplikasi. Constraint membatasi major Laravel yang benar-benar diuji; tidak menggunakan wildcard untuk mengklaim semua versi mendatang. HTTP client bersama memakai Guzzle 7.15.2 atau lebih baru, tanpa Laravel HTTP facade. PHP 7.1 tidak didukung oleh rilis ini; deklarasi minimum Laravel 5.8 bukan minimum package.

Laravel 5.8 memerlukan minimal PHP 7.1.3 menurut [dokumentasi instalasi](https://laravel.com/docs/5.8/installation); Laravel 9 minimal PHP 8.0.2 menurut [upgrade guide](https://laravel.com/docs/9.x/upgrade). Laravel 13 memerlukan PHP 8.3 menurut [release notes](https://laravel.com/framework/docs/releases). Karena itu, “modern minimal PHP 8.0.2” tidak berarti Laravel 13 dapat berjalan di PHP 8.0.

Dukungan package legacy merupakan kompatibilitas connector, bukan perpanjangan dukungan keamanan framework. Laravel 5.8 sudah melewati masa dukungan resminya; rujuk [kebijakan versi 5.8](https://laravel.com/docs/5.8/releases). Instalasi tidak boleh diam-diam melewati pemeriksaan platform atau dependency Composer.

### 3.2 Ketentuan implementasi lintas versi

- Isolasi perbedaan HTTP client, schema inspection, migrasi, cache, dan registrasi middleware melalui adapter internal.
- Jalur legacy tidak memuat sintaks PHP 8 seperti named arguments, match, atau union types.
- Jangan mengasumsikan Laravel HTTP facade tersedia di semua versi.
- Gunakan registrasi route dan middleware milik service provider package, bukan patch Kernel.php atau bootstrap/app.php.
- Package tidak mewajibkan Livewire, Jetstream, Sanctum, Flux, atau framework JavaScript tertentu.
- Discovery mengenali namespace model yang dikonfigurasi, termasuk app/ dan app/Models. Discovery hanya memberi kandidat; tidak membuka data otomatis.
- Mendukung user provider, banyak guard, dan identifier string/UUID; tidak mengasumsikan semua aplikasi memakai App\Models\User dengan ID numerik.
- Ketergantungan produksi tidak menarik testing framework atau UI library.

## 4. Pengguna dan hasil yang diharapkan

| Pengguna | Kebutuhan |
|---|---|
| Developer aplikasi | Memasang dan memperbarui connector tanpa menyalin implementasi |
| Admin aplikasi | Menghubungkan Hub, memilih resource dan field, mengatur akses |
| Admin Hub | Menyetujui koneksi dan mengelola model, budget, serta client key |
| Pengguna aplikasi | Memakai AI sesuai identitas, tenant, dan hak akses yang sedang berlaku |
| Pengelola package | Memperbaiki transport atau keamanan dari satu produk dengan rilis yang teruji |

Target keberhasilan berikut adalah sasaran produk, belum merupakan hasil pengujian:

| ID | Sasaran | Ukuran penerimaan |
|---|---|---|
| G-01 | Setup standar singkat | Maksimal 10 menit dari dependency terpasang sampai health dan katalog terverifikasi pada fixture yang sudah memiliki adapter izin |
| G-02 | Tidak ada salin file integrasi | Tidak perlu mengedit controller, service, routes, Kernel.php, atau bootstrap/app.php secara manual |
| G-03 | Aman dijalankan ulang | Install/connect kedua tidak membuat duplikat, merotasi secret, atau mengubah grants yang sudah disimpan |
| G-04 | Update terpusat | Update package mempertahankan koneksi, registrasi resource, dan pilihan admin |
| G-05 | Mencakup aplikasi target | Keempat baseline aplikasi lulus pilot sebelum dinyatakan didukung |
| G-06 | Tidak membuka data tanpa izin | Instalasi baru menghasilkan manifest kosong; akses lintas user/tenant dan field terlarang selalu ditolak |

Waktu review aturan bisnis, pemasangan DNS/TLS, dan membuat Hub bisa menjangkau aplikasi tidak dihitung sebagai waktu setup standar.

## 5. Ruang lingkup

### P0: fondasi rilis pertama

- Distribusi Composer dan package discovery.
- Installer, koneksi Hub, diagnosis, status, dan sinkronisasi yang idempotent.
- Pairing sekali pakai melalui Hub serta impor aman konfigurasi koneksi lama.
- Connector Contract 1.0 dengan source_managed sebagai default untuk koneksi baru.
- Registry resource, allowlist field, filter terdaftar, read/list/get/count, dan reporting melalui tools Hub yang sudah ada.
- Adapter actor, tenant scope, otorisasi, dan perlindungan data.
- Halaman pengaturan dasar berbasis Blade dengan JavaScript ringan; tidak memerlukan build frontend aplikasi.
- SDK server untuk MCP, daftar model, dan chat Hub; tidak mewajibkan aplikasi memasang jendela chat baru.
- Panduan migrasi adapter lama, dry-run migrator, serta pengujian kompatibilitas.

### P1: fitur lanjutan

- Komponen chat siap pakai dan integrasi opsional Livewire sesuai major yang diuji.
- Prepare/confirm create, update, delete dengan kebijakan bisnis aplikasi.
- Export PDF/Excel serta download yang terikat actor dan izin saat diakses.
- Migrasi penuh fitur chat, proposal, dan export HiReach setelah perilakunya setara.
- Rotasi kredensial terkoordinasi dan integrasi secret manager tambahan.

Fitur P1 yang sudah dipakai di aplikasi lama menjadi syarat migrasi aplikasi tersebut; aplikasi tidak boleh kehilangan fitur hanya karena P0 package sudah selesai.

### Di luar cakupan

- Upgrade framework, PHP, atau dependency aplikasi secara otomatis.
- Menghasilkan aturan bisnis atau menebak kepemilikan record.
- Membuka semua model/tabel, menjalankan SQL bebas, atau memberi Hub kredensial database.
- Menyediakan model AI sendiri atau menyimpan provider API key dalam browser.
- Menyalin semua UI aplikasi ke package.
- Membuat tunnel, mengubah DNS/TLS, atau memodifikasi allowlist jaringan secara otomatis.
- Marketplace publik, vector database, dan deployment aplikasi target.

## 6. Alur penggunaan

Nama package, URL, dan perintah berikut merupakan rancangan, belum tersedia untuk dijalankan.

~~~bash
composer require ardanayatraa/laravel-mcp-hub:0.1.0-alpha.1
php artisan mcp-hub:install
php artisan mcp-hub:connect --hub=https://hub.example.com --app=your_app --environment=staging
php artisan mcp-hub:doctor
~~~

### 6.1 Instalasi baru

1. Composer memasang versi yang kompatibel dan menemukan service provider.
2. Installer memeriksa runtime, dependency, route collision, storage, database, dan cache.
3. Installer membuat konfigurasi yang belum ada dan menjalankan hanya migrasi metadata package. Pada production, perubahan schema mengikuti opsi eksplisit installer dan proses deployment aplikasi.
4. Admin aplikasi menetapkan middleware/guard dan kemampuan pengelolaan package. Halaman pengaturan tetap tertutup sampai otorisasi ini valid.
5. Admin Hub membuat kode pairing untuk app key, environment, dan source URL yang telah disetujui.
6. Perintah connect meminta kode melalui prompt tersembunyi, menyimpan kredensial secara aman, lalu menyelesaikan verifikasi Hub.
7. Hub menguji health, menyinkronkan manifest, lalu mengaktifkan connector source_managed. Manifest kosong sah dan tidak memberi akses data.
8. Developer menetapkan resource dan scope adapter; admin memilih field serta mengaktifkan read.
9. Tools mengikuti manifest aplikasi tanpa setup model kedua di Hub.
10. Doctor menampilkan hasil terpisah untuk koneksi, izin resource, dan kesiapan chat/model gateway.

Network dua arah harus tersedia. Hub production tidak dapat menjangkau domain lokal .test begitu saja; kegagalan reachability harus dijelaskan tanpa mencoba membuat tunnel.

### 6.2 Pembaruan dan aplikasi tambahan

Update menggunakan Composer dan migrasi package yang diperlukan oleh rilis. Upgrade minor mempertahankan metadata dan tidak menjalankan connect ulang. Perpindahan jalur 1.x ke 2.x mengikuti upgrade guide dan migrasi metadata yang diuji.

Aplikasi berikutnya memakai prosedur yang sama dengan app key, environment, resource, dan adapter izin miliknya sendiri. Secret tidak dibagikan antar aplikasi atau antara development dan production.

Registrasi resource baru atau pencabutan izin tidak memerlukan reinstall, restart Hub, maupun publish tools satu per satu. Refresh memakai perilaku source_managed yang sudah ada.

## 7. Arsitektur produk

~~~mermaid
flowchart LR
    User[Pengguna login] --> App[Aplikasi Laravel]
    App --> SDK[SDK package]
    SDK -->|Client key dan delegation| Hub[AI MCP Hub]
    Hub -->|Bearer token dan assertion| API[Connector API package]
    API --> Guard[Actor, tenant scope, policy, allowlist]
    Guard --> DB[(Database aplikasi)]
    Admin[Admin aplikasi] --> Settings[Pengaturan package]
    Settings --> Registry[Registry resource dan grants]
    Registry --> API
~~~

Package memiliki service provider, transport, registry, connector controller, middleware keamanan, metadata repository, perintah Artisan, dan view pengaturan.

Aplikasi menyediakan extension point berupa class konfigurasi untuk **ActorResolver**, **TenantScope**, **ResourceAuthorizer**, dan otorisasi pengaturan. Mapping domain tidak boleh bergantung pada nama produk, tabel permission tertentu, atau kolom status tertentu.

Registrasi resource memuat class model/handler, key stabil, label, field yang diizinkan, filter, lookup, serta adapter scope dan policy. UI admin hanya boleh mengaktifkan subset dari batas yang ditetapkan developer. Field fillable bukan bukti bahwa field aman untuk AI.

## 8. Kebutuhan fungsional

| ID | Kebutuhan | Ketentuan penerimaan |
|---|---|---|
| FR-01 | Discovery package | Provider otomatis aktif ketika discovery tidak dinonaktifkan aplikasi; doctor menjelaskan fallback jika dinonaktifkan |
| FR-02 | Installer aman | Menyediakan dry-run; tidak menimpa file yang sudah diubah; tidak menjalankan seluruh migrasi aplikasi tanpa diminta |
| FR-03 | Connect sekali | Menyimpan connector ID, identitas instalasi, app key, environment, dan kredensial; pengulangan memakai koneksi yang sama |
| FR-04 | Impor konfigurasi lama | Membaca nama MCP_HUB_* yang ada dan alias lama; tidak menampilkan secret atau merotasinya tanpa permintaan |
| FR-05 | Katalog dinamis | Menghasilkan manifest valid dari registrasi dan grants saat ini; registrasi kosong menghasilkan modules kosong |
| FR-06 | Discovery kandidat | Mendeteksi model dan metadata schema tanpa membaca business records dan tanpa mengaktifkan akses |
| FR-07 | Scope wajib | User, tenant, status akun, dan policy diperiksa setiap request; resource tanpa adapter valid ditolak |
| FR-08 | Batas field | Hanya field terdaftar yang dipilih dari database; hidden, secret, PII terlarang, serta code sensitif tidak keluar |
| FR-09 | Query terbatas | Filter/sort/lookup hanya yang terdaftar, input ditutup, pagination dibatasi, tanpa raw SQL atau nama class dari model AI |
| FR-10 | Pengaturan akses | UI memakai web session, CSRF, dan authorization milik aplikasi; grant default kosong dan write default off |
| FR-11 | Hub client | Menangani autentikasi, delegation, JSON-RPC/MCP lifecycle, response JSON/SSE sesuai protokol yang dinegosiasikan |
| FR-12 | SDK chat dan model | Browser memanggil backend aplikasi; server menambahkan actor yang diverifikasi dan menjaga client key tetap server-side |
| FR-13 | Diagnosis | Status runtime, routes, storage, cache atomik, TLS, health, manifest, dan koneksi; pengujian tidak membaca data bisnis |
| FR-14 | Pengelolaan status | Membedakan belum terpasang, belum terhubung, terhubung, tidak ada resource, dan gateway belum diizinkan |
| FR-15 | Nonaktifkan integrasi | Menolak tools segera; tidak menghapus data bisnis, registrasi, atau secret tanpa operasi eksplisit |
| FR-16 | Log aman | Trace ID, operasi, status, dan durasi; tidak merekam token, prompt lengkap, raw assertion, atau record bisnis secara default |
| FR-17 | Migrasi adapter | Dry-run menunjukkan resource, izin, identifier, dan konflik; apply terpisah, resumable, dengan rollback |
| FR-18 | Upgrade | Menyediakan SemVer, changelog, constraint framework eksplisit, dan migrasi metadata lintas jalur rilis |

### 8.1 Perintah Artisan yang direncanakan

| Perintah | Fungsi |
|---|---|
| mcp-hub:install | Preflight, konfigurasi awal, metadata package; mendukung --dry-run dan opsi migrasi eksplisit |
| mcp-hub:connect | Pairing atau impor koneksi; kode/secret dibaca lewat prompt tersembunyi atau secret input CI |
| mcp-hub:status | Menampilkan metadata nonrahasia dan tahap koneksi |
| mcp-hub:doctor | Pemeriksaan lokal dan konektivitas terbatas; mode --json untuk CI |
| mcp-hub:sync | Validasi manifest; rekonsiliasi Hub melalui kewenangan connector yang terbatas, tanpa admin credential tersimpan |
| mcp-hub:migrate-legacy | Preview dan impor adapter lama; mode --dry-run sebagai default |
| mcp-hub:disconnect | Menutup akses lokal; revokasi Hub jika online, status pending revocation jika offline |

Exit code ditetapkan konsisten: 0 berhasil, 1 pemeriksaan/operasi gagal, 2 konfigurasi atau input tidak valid. Output JSON tidak mengandung secret. Mutasi tidak boleh terjadi pada status, dry-run, atau doctor.

## 9. Kontrak yang dipakai dan perubahan Hub

### 9.1 Kontrak yang sudah tersedia

Gunakan [Connector Contract](../../../docs/CONNECTOR_CONTRACT.md) sebagai sumber kebenaran. API package harus memenuhi schema validator Hub, bukan menciptakan format kedua.

| Arah | Endpoint/fitur | Ketentuan |
|---|---|---|
| Hub ke Laravel | GET /api/ai/v1/health | Bearer service token; respons minimal sesuai kontrak |
| Hub ke Laravel | GET /api/ai/v1/capabilities | contract_version 1.0, managed_by application, application sesuai app key |
| Hub ke Laravel | GET /api/ai/v1/{resource}/{action} | list/get/count yang didaftarkan; bearer dan assertion actor |
| Laravel ke Hub | /mcp | Client key terbatas aplikasi/environment dan X-Hub-Delegation untuk tools user-scoped |
| Laravel ke Hub | /gateway/v1/models dan /gateway/v1/chat/completions | Mengikuti daftar model serta budget yang diizinkan Hub |
| Laravel ke Hub | /chat/v1/config dan /chat/v1/turn | Chat Hub opsional; tidak menganggap fitur aktif hanya karena connector aktif |

Prefix route source configurable. Default di atas mengikuti adapter lama; collision harus terdeteksi sebelum koneksi diaktifkan. Route package tidak otomatis menggantikan route lama.

Envelope read menggunakan success, data, meta; metadata mencakup waktu, scope, coverage, dan pagination sesuai kontrak. Field tenant internal dipakai untuk validasi lalu dibuang sebelum hasil mencapai AI. Respons source memiliki Cache-Control: no-store.

Error source mengikuti kode yang diteruskan Hub: PERMISSION_DENIED, VALIDATION_FAILED, NOT_FOUND, RATE_LIMITED, SCHEMA_MISMATCH. Error diagnosis package yang lebih rinci tetap lokal, karena kode source lain dipetakan Hub menjadi UPSTREAM_ERROR.

Read retry dibatasi untuk kegagalan sementara; tidak retry 401/403 atau input invalid. Assertion dibuat baru setiap HTTP attempt. Write proposal P1 tidak di-retry otomatis.

### 9.2 Pairing baru: dependency pengembangan Hub

Hub saat ini mempunyai API admin berbasis session, MFA, dan CSRF untuk membuat connector, test, discover, activate, dan service identity. **Belum ditemukan API pairing atau token provisioning khusus package.** Client key MCP yang ada tidak boleh dianggap memiliki akses ke API admin.

Pairing adalah pekerjaan backend/UI Hub yang wajib masuk P0; Composer package saja tidak menyelesaikan otomatisasi onboarding sepenuhnya.

Kontrak berikut adalah **usulan**, bukan endpoint yang sudah tersedia:

| Operasi | Endpoint usulan | Hak dan hasil |
|---|---|---|
| Buat enrollment | POST /api/admin/v1/connector-enrollments | Session admin + CSRF + scope aplikasi; menetapkan app key, environment, source URL, masa berlaku |
| Claim | POST /api/connect/v1/enrollments/claim | Kode sekali pakai + binding instalasi; mengembalikan bundle kredensial connector pending |
| Finalisasi | POST /api/connect/v1/enrollments/{id}/complete | Proof enrollment; Hub menjalankan test, discover, activate; tidak memberi akses admin umum |
| Status | POST /api/connect/v1/enrollments/{id}/status | Proof enrollment; metadata tahap koneksi tanpa mengembalikan secret |
| Rekonsiliasi | POST /api/connect/v1/connector/sync | Credential khusus sync, terikat satu connector; hanya test/discover connector tersebut, tanpa perluasan scope |

Ketentuan pairing:

- Kode acak kuat, TTL maksimum 10 menit, disimpan hashed, sekali pakai secara atomik, dengan rate limit.
- Enrollment terikat pada app key, environment, source URL yang dinormalisasi, dan satu instalasi. Claim tidak dapat mengganti binding.
- Source URL melewati validasi egress/SSRF Hub yang sudah ada. Production menggunakan HTTPS.
- Hub memberikan app bearer token, delegation secret, dan client key read-only untuk aplikasi tersebut. Proof/credential pengelolaan connector terpisah dari client key runtime.
- Password admin dan session admin tidak disimpan di Laravel.
- Paket menyimpan secret secara atomik sebelum complete. Kegagalan simpan/finalisasi tidak boleh dilaporkan sebagai koneksi aktif.
- State: pending, claimed, configured, verified, active; ada expired, failed, dan revoked. Handle serta proof pemulihan disimpan sebelum langkah lanjutan.
- Retry memakai attempt ID/idempotency binding. Kode yang sudah dikonsumsi tidak bisa dipakai instalasi lain atau menerbitkan client key duplikat.
- Jika bundle respons hilang dan tidak dapat dipulihkan aman, cabut kredensial pending lalu terbitkan enrollment pengganti. Jangan membuka endpoint untuk membaca kembali secret tersimpan.
- Resume memvalidasi keadaan aktual Hub dan Laravel. Enrollment yang ditinggalkan kedaluwarsa serta membersihkan kredensial pending.
- Read-only client key tidak dapat menaikkan hak write, mengaktifkan chat, mengubah allowlist jaringan, budget, atau model yang diizinkan.

Fallback untuk Hub lama: impor blok konfigurasi melalui input rahasia atau environment yang sudah ada, disertai panduan setup satu kali. Status harus menyatakan pairing otomatis belum didukung. Fallback bukan bukti bahwa target onboarding penuh sudah tercapai.

## 10. Identitas, izin, dan keamanan

1. Actor berasal dari pengguna login yang diselesaikan aplikasi; user_id, tenant_id, role, URL, dan token dalam argumen model tidak pernah menetapkan hak akses.
2. Delegation mengikuti kontrak Hub yang sudah ada: HMAC-SHA256, app_key, tenant_id, user_ref, aud, exp; TTL penerbitan maksimal 120 detik.
3. Assertion Hub diverifikasi signature, audience source URL, app key, expiry, jti, dan actor aktif. Replay jti ditolak menggunakan penyimpanan atomik bersama sampai expiry.
4. Cache lokal per proses tidak cukup untuk deployment multi-worker. Doctor memeriksa dukungan atomic add; dapat menggunakan shared cache atau tabel nonce package dengan unique constraint.
5. Tenant resolver mendukung scope per akun, tim, atau organisasi melalui adapter eksplisit. Kolom user_id tidak diasumsikan sebagai tenant untuk semua aplikasi.
6. Query selalu menerapkan ownership/tenant scope dan authorization aplikasi. Soft delete, global scopes, serta batas aplikasi tetap berlaku.
7. Pencabutan izin diperiksa pada pemanggilan berikutnya. Cache katalog tidak boleh mempertahankan izin lama ketika sumber izin gagal diverifikasi.
8. Manifest hanya mengandung metadata yang diizinkan. Tidak menyertakan data contoh dari produksi.
9. Sensitive field diblokir sebelum keluar dari aplikasi, termasuk password, token, OTP, PIN, CVV, dan field pribadi yang dilarang kontrak.
10. Setting package ditutup secara default. Role admin tidak ditebak dari nama atau kolom; aplikasi menetapkan authorization.
11. Production memverifikasi TLS dan tidak mengikuti redirect ke host lain. Kredensial tidak dikirim ke URL model AI atau ke browser.
12. Hub yang tidak tersedia hanya menonaktifkan fitur integrasi/AI; route bisnis aplikasi tetap berjalan.

## 11. Konfigurasi dan penyimpanan

Konfigurasi package berada pada config/mcp-hub.php. Konfigurasi harus kompatibel dengan config:cache: gunakan scalar, array, dan class string; jangan menyimpan closure di config.

| Data | Penyimpanan/rancangan |
|---|---|
| Identitas koneksi | Tabel mcp_hub_connections: installation ID, app key, environment, connector ID, URL, status, versi metadata |
| Kredensial | Kolom terenkripsi dengan encrypter Laravel; deployment dapat memakai environment/secret store sebagai sumber pengganti |
| Registrasi dan grants | Metadata package terpisah dari business records; batas developer tidak dapat diperluas melalui UI |
| Nonce/replay | Cache bersama atomik atau tabel nonce dengan unique constraint dan TTL cleanup |
| Audit lokal | Metadata operasi yang disanitasi; tidak menggandakan log data bisnis |

Urutan resolusi konfigurasi: environment/secret override yang terisi, lalu koneksi tersimpan terenkripsi, lalu default nonrahasia. Jika override menunjuk app/environment yang berbeda dari metadata koneksi, operasi ditolak sampai dikonfigurasi konsisten.

Nama environment baru yang sudah dipakai adapter tetap didukung: MCP_HUB_URL, MCP_HUB_CLIENT_KEY, MCP_HUB_BASE_URL, MCP_HUB_APP_TOKEN, MCP_HUB_DELEGATION_SECRET. Alias lama hanya menjadi fallback; nama baru menang. MCP_HUB_BASE_URL adalah alamat source Laravel, bukan alamat Hub.

URL Hub root dan URL endpoint /mcp harus dinormalisasi dan divalidasi secara eksplisit agar gateway/chat tidak mendapat path yang salah. Koneksi tersimpan tidak mengharuskan menulis ulang .env. Penggantian APP_KEY harus disertai prosedur migrasi secret.

Composer hooks hanya melakukan discovery; tidak menghubungi Hub, merotasi key, menjalankan migrasi, atau membaca data bisnis. Restart worker panjang dan refresh config cache mengikuti prosedur deployment aplikasi setelah perubahan konfigurasi.

## 12. Migrasi dari overlay lama

Migrator membaca struktur adapter yang dikenali dan konfigurasi lama melalui mekanisme Laravel, tanpa mengirimkan file .env ke Hub.

Langkah wajib:

1. Inventory resource, field, grants, ownership mapping, connector ID, client identity, dan fitur yang sedang dipakai.
2. Dry-run menampilkan perubahan serta konflik dalam bentuk nonrahasia; tidak mengubah schema, route, file aplikasi, atau Hub.
3. Import metadata mempertahankan app key, tool key, serta grants yang masih memenuhi kontrak. Field terlarang dilaporkan dan tidak boleh diimpor sebagai granted.
4. Perbedaan policy atau data yang tidak bisa dipetakan tidak diberi default lebih luas; resource terkait tetap nonaktif sampai dipetakan.
5. Snapshot dan rollback meliputi metadata package, konfigurasi adapter, dan pemilihan route aktif. Backup secret harus tetap terenkripsi dan di luar publik/Git.
6. Validasi manifest dan katalog memakai source-managed discovery; pembandingan tidak memanggil write atau membaca business records.
7. Cutover eksplisit memastikan hanya satu implementasi endpoint aktif. Nama tool dan grant tidak berubah tanpa migration plan.
8. Route, chat, settings, proposal, dan export lama tetap menjadi tanggung jawab aplikasi sampai penggantinya lolos uji kesetaraan.

Khusus HiReach, parity mencakup akses akun aktif, filter yang diizinkan, lookup, larangan field sensitif, proposal terikat actor, serta pencabutan akses report setelah policy berubah. Hardcoded branding dan nama cache dipindahkan ke konfigurasi.

Installer tidak menghapus overlay atau mengedit menu dan layout aplikasi secara otomatis. Perubahan aplikasi target merupakan tahap implementasi terpisah.

## 13. Kebutuhan nonfungsional

| ID | Kebutuhan |
|---|---|
| NFR-01 | Boot service provider tidak melakukan network I/O, query business records, atau schema scan penuh |
| NFR-02 | Health dan manifest memiliki timeout terbatas; batas koneksi/read eksplisit, bukan request tanpa batas |
| NFR-03 | Manifest pada fixture 20 resource selesai dalam target p95 500 ms di lingkungan CI yang dicatat, di luar waktu network |
| NFR-04 | Pagination mengikuti batas manifest; default maksimum 50 record per halaman, dapat diturunkan |
| NFR-05 | Registrasi, migrasi, dan pairing tahan proses bersamaan serta retry; tidak menghasilkan grants atau identitas duplikat |
| NFR-06 | SQLite untuk test serta MySQL/MariaDB untuk pilot awal; PostgreSQL aplikasi menjadi cakupan tambahan setelah diuji |
| NFR-07 | Pemakaian config cache, route cache, queue worker, dan request panjang tidak membocorkan actor antar request |
| NFR-08 | Windows development dan Linux deployment mendapat smoke check installer serta path storage |
| NFR-09 | Pesan operasional tersedia dalam Bahasa Indonesia dan Inggris; tidak menampilkan detail internal dalam chat pengguna |

Batas jumlah resource, payload manifest, serta timeout final harus mengikuti validator Hub yang digunakan. Target performa tidak memasukkan latensi model AI.

## 14. Verifikasi dan acceptance criteria

### 14.1 Matriks pengujian

Setiap framework yang diklaim didukung memiliki fixture aplikasi dan kombinasi PHP yang memang sesuai dengan framework tersebut. CI mencatat versi framework, PHP, dependency, database, dan jalur rilis package.

- Baseline CI alpha 0.2: Laravel 5.8.38, 6.20.45, 7.30.7, 8.83.29, 9.52.21, 10.50.4, 11.45.0, 12.64.0, dan 13.38.0.
- Seluruh 13 kombinasi PHP/framework lulus: 18 pengujian aktif dan 70 assertion per kombinasi; satu pengujian HTTP opsional dilewati di CI.
- Simulasi HTTP Postman dijalankan lokal pada Laravel 5.8/PHP 7.4 dan Laravel 12/PHP 8.3: masing-masing 19 pengujian dan 71 assertion, tanpa skip.
- Jalur legacy diuji pada runtime minimum yang diklaim dan runtime fixture proyek yang dapat di-resolve; jalur modern diuji pada minimum per framework serta satu runtime terbaru yang sesuai.
- Gunakan Testbench versi kompatibel per jalur atau fixture aplikasi nyata bila tooling tidak menjangkau versi legacy.
- Pemeriksaan composer.json saja tidak cukup. Wajib ada dependency resolution, package boot, migration, route registration, dan alur runtime.
- Advisory dependency historis yang ditinjau diberi pengecualian ID hanya di fixture development terisolasi, tetap ditampilkan dalam audit lengkap. Advisory baru menyebabkan CI gagal. Manifest runtime public dan konfigurasi aplikasi tidak mendapat pengecualian otomatis, penonaktifan audit, atau pengabaian platform requirements.

| ID | Skenario penerimaan | Hasil wajib |
|---|---|---|
| AC-01 | Fresh install pada fixture target | Provider aktif, metadata terpasang, endpoint tersedia, tidak ada route/file aplikasi tertimpa |
| AC-02 | Install, connect, sync dijalankan dua kali | Connector, client identity, grants, dan secret tidak terduplikasi atau berubah tanpa permintaan |
| AC-03 | Pairing kedaluwarsa, replay, source berbeda, attempt bersamaan | Ditolak; tidak menerbitkan akses tambahan |
| AC-04 | Gagal tulis secret, response terputus, complete gagal | Tidak mengaku aktif; resume/rotasi aman terdokumentasi dan teruji |
| AC-05 | Resource baru diaktifkan lalu dicabut | tools/list dan tools/call berikutnya mengikuti izin terbaru tanpa publish manual di Hub |
| AC-06 | Missing/tampered/expired assertion dan replay lintas worker | Seluruhnya ditolak sebelum query data |
| AC-07 | Dua user/tenant dan akun dinonaktifkan | Tidak ada data silang, tidak ada akses akun nonaktif |
| AC-08 | Field sensitif, filter ilegal, dan identifier dari model AI | Ditolak atau dihapus sesuai kontrak sebelum keluar source; tidak muncul di log |
| AC-09 | Hub mati, timeout, 401, 429, model/budget belum diizinkan | Error terbatas dan jelas; route bisnis tetap berjalan; izin tidak diperluas |
| AC-10 | Config/route cache serta persistent worker | Package berfungsi, secret tidak tertanam di frontend, actor tidak tertukar |
| AC-11 | Upgrade minor dan legacy ke modern | Koneksi/resource/grants terjaga; downgrade/rollback yang didukung diuji |
| AC-12 | Migrasi overlay dan konflik route/policy | Preview akurat, apply idempotent, rollback dapat memulihkan adapter lama |
| AC-13 | Scope admin pengaturan | Pengunjung, user biasa, dan admin yang tidak diberi izin tidak bisa mengelola connector |
| AC-14 | Parity fitur yang dipakai aplikasi lama | Tidak ada cutover sebelum chat/proposal/export terkait memenuhi uji perilaku |

Contract tests menggunakan validator Hub dan contoh payload bersama sebagai acuan. Integrasi memakai Hub lokal terisolasi dan data dummy; pengujian legacy tidak boleh membuka data produksi.

Saat implementasi, request dan assertion API yang dapat dipakai ulang disimpan sebagai contract/collection lokal. Pengujian nyata terhadap Hub harus dibedakan dari hasil mock. Tidak diperlukan publikasi workspace Postman untuk menyusun PRD ini.

## 15. Tahapan dan syarat rilis

| Tahap | Hasil | Syarat selesai |
|---|---|---|
| M0: compatibility spike | Implementasi bersama untuk Laravel 5.8 sampai 13 dan bukti resolve/boot | Lulus pada matriks 13 kombinasi PHP/framework; pertahankan dukungan legacy saat package berkembang |
| M1: connector core | Installer, metadata, registry, scope/actor adapter, source API | Default kosong, kontrak valid, uji isolasi dan replay lulus |
| M2: onboarding | Pairing Hub, connect/resume, import konfigurasi, doctor | Alur dari install ke active tanpa copy-paste secret lulus |
| M3: pemakaian | Pengaturan dasar dan SDK MCP/chat/gateway | Tidak bergantung frontend tertentu; grants dan error mengikuti Hub |
| M4: pilot | Uji empat aplikasi di lingkungan terisolasi + dry-run migrasi lama | Compatibility evidence per aplikasi; fitur lama tidak terganggu |
| M5: cakupan dan rilis | CI semua major yang dijanjikan, panduan, changelog, distribusi | Semua P0 serta AC terkait lulus; versi belum diuji tidak dicantumkan sebagai supported |
| M6: migrasi lanjutan | Parity chat UI, CRUD, export sesuai kebutuhan pilot | Cutover aplikasi lama hanya setelah AC-14 lulus |

Alpha boleh terbatas pada baseline yang sudah lulus, dengan label cakupan eksplisit. Rilis yang mengklaim memenuhi seluruh permintaan harus mencakup empat aplikasi dan rentang framework yang dijanjikan. Jadwal kalender ditetapkan setelah M0; PRD ini tidak menjanjikan estimasi tanpa spike legacy.

Rilis alpha tersedia melalui GitHub public dan Packagist dengan lisensi MIT. Instruksi instalasi mengikuti versi yang benar-benar diterbitkan; cakupan framework dan fitur tetap dibatasi pada hasil pengujian rilis.

## 16. Keputusan terbuka sebelum implementasi

| Keputusan | Default rancangan | Kapan dipastikan |
|---|---|---|
| Identitas Texcel | Mengacu folder telixcel | Sebelum pilot aplikasi tersebut |
| Nama vendor, lisensi, distribusi | ardanayatraa/laravel-mcp-hub, MIT, GitHub public dan Packagist | Diputuskan dan diterbitkan pada rilis alpha |
| PHP server serta dependency legacy aktual | Mengikuti hasil runtime/dependency audit | M0 |
| Guard dan otorisasi pengaturan per aplikasi | Ditentukan aplikasi; default deny | Sebelum mengaktifkan pengaturan |
| Ownership/tenant dan resource pertama tiap aplikasi | Adapter eksplisit, belum ada resource aktif | Sebelum membuka data |
| Perubahan Hub pairing | Masuk P0; belum tersedia saat dokumen dibuat | M2 |
| Komponen UI opsional dan parity legacy | Blade dasar; UI aplikasi melalui adapter | Sebelum cutover |

Keputusan tersebut tidak menghalangi penulisan PRD, tetapi tidak boleh diganti asumsi yang memperluas akses ketika implementasi dimulai.

## 17. Referensi

- [PRD utama Hub](../../../PRD.md).
- [Adapter Laravel dan alur lama](../README.md).
- [Connector Contract 1.0](../../../docs/CONNECTOR_CONTRACT.md).
- [API admin, MCP, chat, model gateway](../../../docs/API.md).
- [Validator manifest Hub](../../../backend/app/connectors/contracts.py).
- [Skrip provisioning lama](../provision.py).
- [Composer snapshot adapter](../overlay/composer.json).
- Baseline aplikasi: composer.json dan composer.lock pada checkout lokal telixmart, hireach, telixcel, dan iseetalk; hanya metadata versi yang diperiksa. Tidak ada kredensial disalin ke dokumen.
- [Laravel Package Development](https://laravel.com/framework/docs/packages): provider discovery dan sumber daya package.
- [Laravel Release Notes](https://laravel.com/framework/docs/releases): versi modern, runtime, serta kebijakan dukungan.
