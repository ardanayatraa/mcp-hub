# Keamanan dan batas kepercayaan

Izin efektif merupakan irisan beberapa lapisan. Mengetahui endpoint atau opaque reference tidak memberi akses record.

## Identitas

Service credential mengautentikasi koneksi antar server. Client key membatasi aplikasi/tools/profil/write scope. Delegation menetapkan actor dari trusted server; assertion sekali pakai mengikat request Hub ke sumber. Resolver/policy host memeriksa ulang akun aktif, tenant, record, dan izin saat ini.

Laravel 1.0 memakai uniqueness SQL untuk menolak replay lintas worker dan cache reset. Metadata security yang hilang membuat readiness menolak layanan. Jangan menambahkan fallback cache lokal untuk melewati kegagalan ini.

## Secrets dan data

Provider key tetap di Hub. Credentials koneksi serta payload privat disimpan terenkripsi. Key, pairing code, APP_KEY, database URL, dan laporan privat tidak boleh masuk Git, browser HTML, URL query, log, maupun dokumentasi publik.

Field sensitif dan argumen identity/routing model ditolak. Review allowlist/policy tetap wajib: deteksi PII otomatis tidak menggantikan klasifikasi data aplikasi.

## Jaringan dan persetujuan

Gunakan egress allowlist, endpoint yang ditinjau, batas ukuran/waktu, HTTPS, serta origin/host spesifik. Keterjangkauan HTTP bukan bukti autentikasi actor.

Persetujuan transaksi berada pada sesi aplikasi dengan actor proposal yang sama. File laporan tetap privat, terenkripsi, expired, dan diperiksa ulang saat download. Reference dan URL bukan bearer grant.

## Pelaporan

Gunakan private vulnerability reporting GitHub bila tersedia. Jika tidak, minta kanal privat tanpa mengirim exploit, credentials, atau data pribadi melalui issue publik.

[Security package](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/SECURITY.md) · [Security Hub](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/SECURITY.md)

Jalankan audit dependensi host. Kompatibilitas dengan Laravel/PHP lama tidak memperpanjang pemeliharaan keamanan upstream.
