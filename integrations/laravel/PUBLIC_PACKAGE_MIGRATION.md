# Migrasi pilot ke package publik

Package tujuan adalah `ardanayatraa/laravel-mcp-hub`. Package lama
`mcp-hub/laravel-connector` merupakan prototipe lokal. Keduanya memakai namespace
PHP yang sama, sehingga tidak boleh dipasang bersamaan.

Panduan ini khusus adapter HiReach yang sudah direview. Aplikasi Laravel lain
memakai instalasi generik dengan model/policy miliknya sendiri. Tidak ada model
billing, kelas user, role atau kolom bisnis yang diwajibkan oleh package publik.

## Status verifikasi

Migrasi sudah dicoba pada salinan kode di `.verification/public-package-pilot`,
dengan APP_KEY baru dan environment dummy. Tidak ada `.env`, storage, database,
credential atau data bisnis aplikasi asli yang disalin untuk pengujian.

- 85 tes konektor lulus, termasuk chat, proposal, laporan, isolasi pengguna dan
  pencabutan izin yang tetap dimiliki aplikasi.
- 11 tes wrapper client lulus dengan transport publik dan HTTP palsu.
- Replay tetap ditolak sesudah cache dihapus; health menjadi 503 saat metadata
  nonce hilang.
- Hash `.env` dan konfigurasi pilot tetap sama sebelum/sesudah migrasi.
- Enam tes planner/pemulihan memeriksa perubahan yang direview, path, dependency,
  environment dan perlindungan terhadap edit pengguna yang berlangsung bersamaan.

Aplikasi asli belum dipindahkan ke dependency publik. Tidak ada akses aaPanel,
SSH, deployment produksi, perubahan credential atau perubahan database asli.

## Apa yang berubah

Script `migrate-public-package.py` mengganti dependency prototipe dengan package
publik, menyelesaikan dependency yang diperlukan dan menjalankan metadata package
saja. Setelah metadata siap, script memperbarui tiga bagian adapter:

1. `McpActorIdentity` memakai nonce SQL dari package sehingga penghapusan cache
   tidak membuka replay.
2. Health source memeriksa metadata keamanan dan menolak layanan yang belum siap.
3. Wrapper `McpClient` menyesuaikan objek argumen kosong dengan SDK baru dan tetap
   memberi pesan error umum yang aman.

Registrasi/grant model, field, route source, UI, chat, proposal, report, handler
bisnis dan konfigurasi koneksi tetap menjadi milik aplikasi. Tidak ada proses
yang mengisi ulang `.env` atau menerbitkan ulang seluruh konfigurasi. Fitur baru
package seperti export generik tidak otomatis menggantikan report native.

Sesudah dependency publik dipasang, script legacy `install.py`, `sync.py`,
`apply-package.py` dan `configure.py` menolak pemakaian pada aplikasi tersebut.
Ini mencegah overlay lama menimpa kontrol keamanan atau credential yang sudah
dimigrasikan. Pemeriksaan aplikasi berikutnya memakai prosedur publik.

## Pratinjau

Jalankan dari workspace Hub. Sampai versi berisi fitur ini dirilis, gunakan
checkout development yang sudah diuji:

```powershell
backend/.venv/Scripts/python.exe integrations/laravel/migrate-public-package.py `
  --app ../hireach --local-package repositories/laravel-mcp-hub
```

Tanpa `--apply`, tidak ada file, dependency atau database yang diubah. Planner
menolak bagian verifikasi actor/client/health yang berbeda dari pola yang sudah
direview, serta target yang keluar dari direktori aplikasi.

Setelah review, pengujian aplikasi dan backup, tambahkan `--apply` pada target
lokal yang memang hendak dimigrasikan. Untuk produksi, gunakan proses release dan
maintenance aplikasi yang sudah ada; metadata produksi memerlukan izin eksplisit
`--force-metadata`. Script ini tidak mengatur aaPanel atau memindahkan traffic.

Sesudah stable yang memuat fitur ini tersedia, `--local-package` dapat dihilangkan.
Composer memilih rilis stabil yang cocok dengan versi PHP/framework. Tidak perlu
nama package berbeda untuk setiap versi Laravel. Published alpha saat ini belum
berisi seluruh fitur development tersebut.

## Pemulihan

Backup file yang disentuh dan log berada di
`.verification/public-package-migrations/<id>`. Folder ini privat dan diabaikan
Git. `.env` tidak dimasukkan ke backup script karena tidak pernah ditulis.

Jika dependency atau metadata gagal, script mencoba mengembalikan manifest/lock
dan file hasil tulisannya, lalu memulihkan dependency tanpa menjalankan plugin
atau script Composer. File yang sudah diedit pengguna setelah penulisan script
dipertahankan untuk review; konfigurasi dan `.env` tidak ditimpa saat pemulihan.
Kegagalan pemulihan dependency memerlukan pemeriksaan log dan file backup sebelum
aplikasi dipakai kembali. Script tidak menurunkan schema atau menghapus tabel.

Periksa `mcp-hub:doctor`, health source, suite konektor dan kecocokan catalog
sebelum mengalihkan pemakaian. Menjalankan ulang migrasi tidak memutar credential.
Credential yang sengaja dicabut/replaced perlu dipulihkan melalui pairing resmi,
bukan melalui restore `.env` dari overlay lama.

## Temuan aplikasi yang perlu dipertahankan dalam review

Salinan install bersih menemukan kontrak vendor Jetstream khusus
`CurentTeamResponse` yang digunakan service provider aplikasi. Fixture membawa
kontrak kode tersebut agar pengujian mencerminkan aplikasi terpasang. Ini bukan
dependency/kontrak package publik. Review dan kelola kustomisasi vendor aplikasi
sebelum melakukan install bersih atau deployment Laravel baru.

Audit dependency aplikasi warisan juga memiliki temuan upstream di luar package.
Pemasangan connector tidak menyelesaikan semua temuan Laravel/Jetstream/Excel dan
dependency aplikasi lainnya. Audit modern package/Hub serta baseline fixture
lama dicatat terpisah. Jangan menyalin exception audit fixture ke konfigurasi
produksi, mengabaikan platform requirement, atau menaikkan dependency bisnis
secara diam-diam agar migrasi terlihat berhasil.
