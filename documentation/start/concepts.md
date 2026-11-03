# Konsep dan arsitektur

MCP Hub menghubungkan client AI dengan aplikasi bisnis melalui tools yang ditinjau. Panduan Hub ini mengikuti edisi Python pada branch `main`: backend FastAPI, admin UI Vue, PostgreSQL untuk produksi, dan Redis untuk pembatasan bersama.

## Pembagian tanggung jawab

| Komponen | Tanggung jawab |
|---|---|
| Hub | Konfigurasi connector, secrets terenkripsi, katalog tools, profil, model gateway, dan audit metadata |
| Aplikasi sumber | Akun aktif, keanggotaan tenant, ownership record, validasi bisnis, persetujuan, dan file laporan |
| Client AI | Menemukan tools yang diizinkan dan mengirim argumen sesuai schema |
| Package Laravel | Endpoint sumber, SDK Hub, verifikasi assertion, proposal, dan UI yang dilindungi izin host |

Hub tidak memerlukan kredensial database bisnis. Record yang diizinkan dapat melintas saat permintaan berjalan; aplikasi tetap pemilik data. Konfigurasi dan audit Hub terpisah dari record bisnis. Memory opsional menyimpan catatan pengguna terenkripsi, sedangkan ekspor privat disimpan oleh aplikasi Laravel.

## Istilah utama

| Istilah | Makna |
|---|---|
| App / connector | Aplikasi dengan URL sumber, environment, dan identitas tetap |
| Data source / resource | Modul yang ditinjau, misalnya `orders` |
| Tool | Operasi dengan endpoint, schema, dan izin yang jelas |
| Client key | Kredensial satu client untuk scope aplikasi tertentu |
| Access profile | Pembatas tambahan terhadap resource dan tools |
| Skill | Instruksi reusable yang diterbitkan sebagai MCP prompt |
| Delegation | Bukti pengguna dari server aplikasi ke Hub |
| Assertion | Bukti singkat sekali pakai dari Hub ke aplikasi sumber |

## Alur satu permintaan

1. Server aplikasi menetapkan actor dari pengguna yang terautentikasi.
2. Client memanggil Hub memakai bearer key dan delegation untuk operasi per pengguna.
3. Hub memeriksa key, profil, connector, grants, schema, dan izin operasi.
4. Hub menghubungi endpoint tetap dengan service credential dan assertion actor.
5. Aplikasi menolak replay dan memeriksa ulang akun, tenant, policy, serta scope record.
6. Hub memvalidasi respons dan memproyeksikan field sebelum mengirim hasil ke client.

## Dua mode connector

**`source_managed`** mengikuti manifest izin aplikasi. Refresh yang gagal menolak katalog/panggilan daripada memakai grants lama. Pengaturan manual tools/modul di Hub dikunci.

**`http_contract`** memakai proses review, test, dan publish manual di Hub. Pilih mode ini bila kontrak tools dikelola operator Hub.

Lihat [connector contract](../reference/connector-contract.md) untuk manifest, respons, dan batas schema.
