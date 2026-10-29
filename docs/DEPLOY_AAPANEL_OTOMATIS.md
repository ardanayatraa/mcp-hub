# Deploy otomatis MCP Hub ke aaPanel

Status: struktur kode dan template disiapkan di repository. Belum diaktifkan pada
server dan belum diuji terhadap instalasi aaPanel Anda. Tidak ada akses ke panel
atau perubahan credential server selama penyiapan ini.

Panduan ini untuk **Hub Python dan frontend Vue pada repository ini**. Package
Laravel diterbitkan melalui repository Composer tersendiri; deploy Hub tidak
menjalankan `composer update` atau mengubah aplikasi Laravel yang terhubung.

## Perilaku setelah diaktifkan

```text
push main
  → CI backend SQLite/PostgreSQL, security, frontend, deploy tests, Docker smoke
  → pastikan commit masih menjadi main terbaru
  → build frontend dan bundle kode yang dibatasi
  → upload melalui SSH dengan host key yang diverifikasi
  → siapkan releases/<commit> dan virtualenv baru
  → periksa schema dan buat backup metadata PostgreSQL
  → simpan asset frontend lama, ganti symlink current, restart service
  → /ready harus berhasil; kegagalan memulihkan rilis sebelumnya
```

Hanya satu deploy berjalan pada satu waktu; deploy aktif tidak dibatalkan oleh
push berikutnya. Commit yang sudah digantikan pada `main` dilewati.
[Perilaku concurrency GitHub Actions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

Otomatisasi ini **tidak menulis ulang** `hub.env`, deploy config, SSH keys,
konfigurasi Nginx/SSL aaPanel, model-provider keys, client keys, atau pengaturan
aplikasi di database. Tidak ada `git reset --hard`, `rsync --delete`, pembuatan
encryption key baru, reset admin, restore database, atau migrasi otomatis.

Schema yang berbeda menghentikan deploy sebelum pergantian rilis. Ini penting
karena rollback kode ke schema yang tidak kompatibel tidak dapat dijamin aman.
Perubahan schema menggunakan prosedur operator terpisah di bagian bawah.

## Berkas yang disediakan

| Berkas | Fungsi |
|---|---|
| `.github/workflows/ci.yml` | Menjalankan pemeriksaan; memanggil deploy hanya untuk `main` setelah semuanya lulus |
| `.github/workflows/deploy-aapanel.yml` | Build, pemeriksaan commit terbaru, environment production, SSH deploy |
| `deploy/aapanel/build_release.py` | Bundle deterministik, manifest SHA-256, tanpa `.env`, virtualenv atau data lokal |
| `deploy/aapanel/push-release.sh` | Upload dan pemanggilan controller melalui SSH |
| `deploy/aapanel/deploy.py` | Controller milik server, lock, validasi arsip, backup, aktivasi, rollback |
| `deploy/aapanel/runtime.py` | Pemeriksaan versi schema dan `pg_dump` dari virtualenv rilis |
| `deploy/aapanel/deploy.example.json` | Template path dan service server; tidak berisi credential |
| `deploy/aapanel/mcp-hub.service.example` | Service systemd pada loopback, user khusus |
| `deploy/aapanel/nginx.locations.conf.example` | Routing statis/API untuk vhost HTTPS aaPanel |
| `deploy/aapanel/sudoers.example` | Hak restart untuk satu service saja |

## 1. Persiapan server sekali saja

Gunakan Linux dengan Python 3.12+, `uv`, PostgreSQL dan `pg_dump` yang kompatibel,
Redis privat berautentikasi dengan `maxmemory-policy noeviction`, systemd,
OpenSSH, serta domain HTTPS di aaPanel. Hub production menolak SQLite dan
in-process rate limiter. Node/pnpm hanya diperlukan pada runner build GitHub.

Default contoh:

| Komponen | Nilai contoh |
|---|---|
| Domain | `hub.example.com` |
| Folder deploy khusus | `/www/wwwroot/mcp-hub` |
| Service | `mcp-hub.service` |
| Port backend lokal | `127.0.0.1:18321` |
| User SSH deploy | `hub-deploy` |
| User proses aplikasi | `mcp-hub` |

Sesuaikan contoh dengan server sebenarnya. Jangan menggunakan folder website
lama sebagai target `current`: controller menolak mengganti direktori biasa.
Pilih folder layout baru, lalu arahkan website ketika aktivasi pertama selesai.

Jalankan penyiapan berikut dari terminal operator yang berwenang. Jika user,
service atau berkas konfigurasi sudah ada, periksa dan gunakan konfigurasi
tersebut; jangan menimpa atau menggandakan service yang aktif.

Contoh untuk instalasi baru:

```bash
sudo groupadd --system mcp-hub
sudo useradd --system --gid mcp-hub --no-create-home --shell /usr/sbin/nologin mcp-hub
sudo useradd --system --gid mcp-hub --home-dir /var/lib/mcp-hub-deploy --no-create-home --shell /bin/bash hub-deploy

sudo install -d -o root -g root -m 0755 /var/lib/mcp-hub-deploy
sudo install -d -o root -g root -m 0755 /var/lib/mcp-hub-deploy/.ssh
sudo install -d -o hub-deploy -g mcp-hub -m 0755 /www/wwwroot/mcp-hub
sudo install -d -o hub-deploy -g mcp-hub -m 0755 /www/wwwroot/mcp-hub/releases
sudo install -d -o hub-deploy -g mcp-hub -m 0700 /www/wwwroot/mcp-hub/incoming
sudo install -d -o hub-deploy -g mcp-hub -m 0751 /www/wwwroot/mcp-hub/shared
sudo install -d -o hub-deploy -g mcp-hub -m 0700 /www/wwwroot/mcp-hub/shared/backups
sudo install -d -o hub-deploy -g mcp-hub -m 0755 /www/wwwroot/mcp-hub/shared/frontend-assets
sudo install -d -o hub-deploy -g mcp-hub -m 0750 /www/wwwroot/mcp-hub/shared/uv-cache
sudo install -d -o root -g mcp-hub -m 0750 /etc/mcp-hub
sudo install -d -o root -g root -m 0755 /usr/local/lib/mcp-hub
```

User aplikasi hanya membaca kode rilis. Nginx membaca frontend publik, tanpa
perlu menjadi anggota grup yang dapat membaca `hub.env`.

### Credential dan pengaturan aplikasi

Simpan `.env` production yang sudah ada sebagai:

```text
/www/wwwroot/mcp-hub/shared/hub.env
```

Untuk memindahkan konfigurasi yang sudah ada, lakukan salinan **sekali** ke file
baru menggunakan `cp -n`; pastikan target belum ada. Jangan mengganti encryption
key atau DSN database. Jangan menampilkan isi file di terminal/log/chat.

```bash
# Ganti /path/to/existing/.env dengan path konfigurasi milik instalasi Anda.
sudo test ! -e /www/wwwroot/mcp-hub/shared/hub.env
sudo cp -n /path/to/existing/.env /www/wwwroot/mcp-hub/shared/hub.env
sudo chown hub-deploy:mcp-hub /www/wwwroot/mcp-hub/shared/hub.env
sudo chmod 0640 /www/wwwroot/mcp-hub/shared/hub.env
```

Untuk instalasi baru, isi konfigurasi production melalui editor server, mengikuti
[DEPLOY.md](DEPLOY.md). Semua key harus dibuat dan disimpan oleh operator sebelum
aktivasi pertama; workflow tidak menghasilkannya. Pastikan khususnya
`ENVIRONMENT=production`, DSN PostgreSQL, encryption/session keys, Redis settings,
domain/origin/host HTTPS, approved egress, dan secure cookies benar. Tambahkan
konfigurasi baru yang memang belum ada; jangan meregenerasi nilai yang sudah ada.

Database tetap berada pada DSN yang sama. Pengaturan provider, budget, client key
dan konektor tetap memakai database tersebut. Backup metadata hanya bisa dibaca
oleh user deploy/root dan tidak diunggah ke GitHub.
Password `pg_dump` memakai password file sementara berizin `0600`, lalu dihapus;
nilainya tidak menjadi argumen proses atau `PGPASSWORD`.
[Dokumentasi password file PostgreSQL](https://www.postgresql.org/docs/current/libpq-pgpass.html).

### Pasang controller, config dan service

Gunakan checkout dari commit yang sudah direview. Perintah berikut mengasumsikan
terminal berada di root checkout tersebut. Untuk penyiapan pertama, cek bahwa
target belum ada sebelum menyalin:

```bash
sudo test ! -e /usr/local/lib/mcp-hub/deploy.py && \
  sudo install -o root -g root -m 0755 deploy/aapanel/deploy.py /usr/local/lib/mcp-hub/deploy.py

sudo test ! -e /etc/mcp-hub/deploy.json && \
  sudo install -o root -g mcp-hub -m 0640 deploy/aapanel/deploy.example.json /etc/mcp-hub/deploy.json
sudoedit /etc/mcp-hub/deploy.json

sudo test ! -e /etc/systemd/system/mcp-hub.service && \
  sudo install -o root -g root -m 0644 deploy/aapanel/mcp-hub.service.example /etc/systemd/system/mcp-hub.service

sudo test ! -e /etc/sudoers.d/mcp-hub-deploy && \
  sudo install -o root -g root -m 0440 deploy/aapanel/sudoers.example /etc/sudoers.d/mcp-hub-deploy
sudo visudo -cf /etc/sudoers.d/mcp-hub-deploy
sudo systemctl daemon-reload
sudo systemctl enable mcp-hub.service
```

Sesuaikan semua path jika Python/uv/pg_dump dari server berbeda, serta domain
`health_host`. Jika mengganti nama service/folder/port, sesuaikan deploy JSON,
unit systemd, sudoers dan Nginx bersama-sama. Controller hanya mengizinkan probe
loopback. API menguji database dan Redis melalui `/ready`.

Service belum perlu dimulai sebelum ada rilis aktif. Controller merupakan file
root-owned di luar rilis, sehingga push kode tidak mengganti kebijakan SSH atau
service. Perubahan controller pada masa depan dipasang operator setelah review;
`deploy.json` dan `hub.env` tetap dipertahankan.

## 2. SSH deployment key

Buat key khusus deploy dari komputer operator atau secret manager. Private key
tidak disimpan di repository. Tambahkan public key ke
`/var/lib/mcp-hub-deploy/.ssh/authorized_keys` dengan forced command:

```text
restrict,command="/usr/bin/python3.12 /usr/local/lib/mcp-hub/deploy.py /etc/mcp-hub/deploy.json" ssh-ed25519 PUBLIC_KEY_DEPLOY_ANDA
```

Gunakan editor untuk mempertahankan entry lain jika file sudah ada. Setelah itu:

```bash
sudo chown root:root /var/lib/mcp-hub-deploy/.ssh/authorized_keys
sudo chmod 0644 /var/lib/mcp-hub-deploy/.ssh/authorized_keys
```

Key ini dapat menjalankan `upload <commit>`, `deploy <commit> <checksum>` dan
`status` saja. Tidak memberikan shell, PTY, port forwarding, akses root umum,
atau hak mengubah konfigurasi systemd/Nginx. Kode deploy tetap harus dipercaya:
key deploy yang bocor bisa mengirim kode aplikasi berbahaya. Lindungi `main`,
environment production, dan key ini seperti credential production lainnya.

Verifikasi fingerprint host key server melalui kanal operator terpercaya.
Masukkan entry `known_hosts` yang sesuai hostname dan port ke GitHub Secret.
Jangan mengganti verifikasi dengan `StrictHostKeyChecking=no` atau mempercayai
hasil `ssh-keyscan` tanpa membandingkan fingerprint terlebih dahulu.

## 3. GitHub Environment dan aktivasi

Buat environment `aapanel-production` dan batasi deployment branch ke `main`.
Untuk deploy tanpa klik approval setiap push, jangan menambahkan required
reviewer pada environment tersebut. Tetap gunakan branch protection/review PR
pada `main`. [Pengaturan environment GitHub](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

Tambahkan **Environment Secrets**:

| Nama | Isi |
|---|---|
| `AAPANEL_SSH_HOST` | Host/IP SSH server Anda |
| `AAPANEL_SSH_USER` | `hub-deploy` atau account khusus yang telah disiapkan |
| `AAPANEL_SSH_PRIVATE_KEY` | Private key deploy khusus |
| `AAPANEL_SSH_KNOWN_HOSTS` | Entry host key yang fingerprint-nya telah diverifikasi |

Tambahkan **Repository Variables**:

| Nama | Isi |
|---|---|
| `AAPANEL_DEPLOY_ENABLED` | `true` untuk mengaktifkan; kosong/`false` membuat deploy dilewati |
| `AAPANEL_SSH_PORT` | Port SSH, misalnya `22` |

Credential database, encryption keys dan model-provider keys tidak perlu
dimasukkan ke GitHub. Jika runner GitHub tidak dapat menjangkau SSH server,
siapkan konektivitas yang disetujui operator; jangan membuka backend 18321 ke
Internet. Deployment memakai SSH, bukan API panel aaPanel.

Setelah berkas workflow sudah di `main` dan penyiapan server selesai, push ke
`main` menjalankan CI lalu deployment. Workflow juga dapat diulang melalui
**Re-run jobs**, atau menjalankan workflow `ci` pada branch `main` untuk retry
dengan pemeriksaan lengkap.

## 4. Aktivasi pertama dan schema database

Jika schema database sudah sama dengan rilis, deployment langsung dilanjutkan.
Jika database baru atau masih pada revisi sebelumnya, run pertama akan berhenti
dengan:

```text
SCHEMA_CHANGE_REQUIRES_REVIEW_NO_DATABASE_CHANGES_MADE
```

Ini menyiapkan folder rilis dan virtualenv, tanpa mengaktifkan rilis atau
memodifikasi database. Catat commit dari run tersebut. Operator dapat melakukan
inisialisasi/migrasi dari rilis yang sudah disiapkan, setelah backup dan review
migration:

```bash
# Isi commit 40 karakter dari run GitHub, bukan main yang dapat berubah.
commit=ISI_COMMIT_40_KARAKTER
release="/www/wwwroot/mcp-hub/releases/$commit"
cd "$release/backend"

# Backup terlebih dahulu; DSN/password dibaca dari hub.env, tidak menjadi argumen proses.
sudo -u hub-deploy env -i PATH=/usr/bin:/usr/local/bin PYTHONPATH="$release/backend" \
  "$release/backend/.venv/bin/python" "$release/deploy/aapanel/runtime.py" backup \
  /usr/bin/pg_dump /www/wwwroot/mcp-hub/shared/backups/pre-schema-review.dump

# Untuk perubahan schema instalasi aktif, hentikan service pada maintenance window.
# Jangan jalankan stop ini sebagai bagian deploy kode rutin.
sudo systemctl stop mcp-hub.service
sudo -u hub-deploy env -i PATH=/usr/bin:/usr/local/bin \
  "$release/backend/.venv/bin/python" -m alembic upgrade head

# Khusus database baru: seed admin awal dari konfigurasi server sekali saja.
# Jangan gunakan reset password/MFA pada upgrade rutin.
sudo -u hub-deploy env -i PATH=/usr/bin:/usr/local/bin \
  "$release/backend/.venv/bin/python" -m app.bootstrap
```

Pilih nama backup baru agar backup sebelumnya tidak tertimpa. Jika instalasi
pertama belum memiliki `current`, ulangi workflow setelah schema siap.

Jika sudah ada rilis aktif dan schema memang berubah, controller menolak
rollback kode lintas schema. Sesudah migrasi yang direview, operator di terminal
interaktif dapat mengaktifkan rilis tersebut:

```bash
archive="/www/wwwroot/mcp-hub/incoming/$commit.tar.gz"
checksum="$(sudo -u hub-deploy sha256sum "$archive" | cut -d ' ' -f 1)"
sudo -u hub-deploy /usr/bin/python3.12 /usr/local/lib/mcp-hub/deploy.py \
  /etc/mcp-hub/deploy.json --schema-cutover "$commit" "$checksum"
```

Mode ini tidak tersedia melalui key SSH GitHub. Ia tetap tidak menjalankan
migration/downgrade. Jika health check gagal setelah cutover schema, database dan
credential dipertahankan; pemulihan dilakukan operator dari backup yang sudah
direview. Jangan otomatis mengembalikan dump karena perubahan konfigurasi baru
dapat hilang.

## 5. Vhost aaPanel

Gunakan website statis khusus domain Hub. Root-nya:

```text
/www/wwwroot/mcp-hub/current/frontend/dist
```

Gabungkan `deploy/aapanel/nginx.locations.conf.example` ke server block HTTPS
website tersebut satu kali. Pertahankan directive SSL, certificate paths,
ACME challenge dan pengaturan panel yang sudah ada. Sesuaikan/hapus location
duplikat pada website itu, kemudian jalankan pemeriksaan Nginx sebelum reload.
Skrip deploy tidak menyalin template ini ke server dan tidak me-reload Nginx.

Sertifikat HTTPS tetap dikelola aaPanel. HTTP harus redirect ke HTTPS melalui
konfigurasi website. Backend hanya mendengarkan loopback; PostgreSQL dan Redis
tetap pada jaringan privat. Bila memakai security header tambahan seperti HSTS,
pertahankan kebijakan domain yang sudah direview operator.

Folder `shared`, `incoming`, `backups`, `.env` dan kode backend tidak menjadi
document root. Asset lama disimpan di `shared/frontend-assets`, sehingga tab
browser yang masih terbuka dapat mengambil chunk dari rilis sebelumnya.

## 6. Operasional dan pemulihan

- **Deploy kode gagal sebelum aktivasi:** `current` dan service lama tetap dipakai.
- **Health check rilis baru gagal, schema sama:** controller mengembalikan symlink
  dan me-restart rilis sebelumnya. Jika rollback juga tidak siap, run berstatus
  gagal dan memerlukan pemeriksaan operator.
- **Koneksi database/Redis gagal:** `/ready` gagal; deployment tidak dianggap sukses.
- **Credential dirotasi saat deploy:** hash file berubah, deployment dihentikan;
  perubahan operator tidak ditimpa dengan nilai lama.
- **Konfigurasi aplikasi berubah melalui UI Hub:** tetap berada di database yang
  sama; bundle rilis tidak berisi salinan database lokal.
- **Mematikan auto deploy:** set `AAPANEL_DEPLOY_ENABLED=false`; rilis aktif tetap berjalan.
- **Melihat status tanpa secret:** `ssh hub-deploy@HOST status` memakai forced command.
- **Log:** gunakan `journalctl -u mcp-hub.service`; jangan menyalin isi `hub.env`
  atau dump ke log/issue/chat.

Rilis, backup dan asset lama tidak dihapus otomatis. Pantau ruang disk; deploy
menolak persiapan bila ruang tersedia kurang dari 2 GiB. Buat kebijakan retensi
server setelah restore drill, dengan selalu menyimpan rilis aktif, rilis
pemulihan, dan backup yang diperlukan. Jangan menghapus encryption key yang masih
dibutuhkan untuk membaca backup credential terenkripsi.

Perubahan pengaturan di server tidak dimasukkan ke Git. `.gitignore` dan
allowlist bundle membantu mencegah file lokal terunggah, tetapi file rahasia yang
sudah pernah di-commit memerlukan penanganan riwayat/rotasi secara terpisah;
`.gitignore` tidak menghapus riwayat tersebut.

## 7. Verifikasi yang sudah tersedia

Jalankan pengujian controller pada Linux atau container Linux lokal:

```bash
python3 -m unittest discover -s deploy/aapanel/tests -v
bash -n deploy/aapanel/push-release.sh
```

Test memakai filesystem sementara dan simulasi service/database. Cakupannya
preservasi `.env`/settings, checksum dan manifest, path traversal/link berbahaya,
lock antar-deploy, asset lama, schema gate dan rollback. Test ini tidak membuktikan
konfigurasi SSH, systemd, Nginx, PostgreSQL atau aaPanel pada server Anda; verifikasi
server dilakukan setelah Anda menginstruksikannya.
