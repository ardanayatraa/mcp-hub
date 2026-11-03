# Hubungkan aplikasi

Tentukan app key, environment, URL sumber, dan pemilik kebijakan resource sebelum koneksi dibuat. Perubahan identitas/URL perlu ditinjau karena nilai itu terikat pada kredensial dan reference.

## Pairing Laravel

1. Daftarkan aplikasi/connector di Hub dengan URL sumber yang benar.
2. Buat enrollment code melalui admin yang mempunyai scope aplikasi.
3. Jalankan [pairing dari Laravel](../laravel/connection.md).
4. Pastikan Hub memvalidasi health dan capability manifest sumber.
5. Periksa status aktif, grants, dan client key yang terikat.

Pairing memberikan kredensial read-only. Replacement mempertahankan restrictions dan tidak menambahkan hak tulis.

## Mode pengelolaan

| Mode | Pemilik konfigurasi | Alur |
|---|---|---|
| `source_managed` | Aplikasi sumber | Manifest mengikuti grants aplikasi; refresh gagal menolak akses |
| `http_contract` | Operator Hub | Test connector, discover, review modul, test tools, publish |

Manifest `source_managed` wajib menyatakan `managed_by: application`. Daftar `modules: []` yang eksplisit mencabut seluruh generated tools. Profil dan key tetap dapat mempersempit akses.

## Sumber non-Laravel

Implementasikan health, manifest, dan endpoint sesuai [connector contract](../reference/connector-contract.md). Service credential membuktikan Hub boleh menghubungi aplikasi; assertion membuktikan konteks pengguna. Endpoint dan metode ditetapkan oleh manifest, bukan argumen model.

## Siklus hidup

**Test** memeriksa autentikasi/keterjangkauan. **Discover/sync** memvalidasi kontrak. **Activate** mengaktifkan connector. **Pause** memblokir panggilan sambil mempertahankan metadata. **Revoke/archive** mencabut akses sesuai scope aksi.

Renewal mempertahankan identitas. Replacement mencabut credentials instalasi lama dan mengeluarkan code sekali pakai untuk penggantinya. Detail expiry dan recovery tersedia di [API enrollment](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/CONNECTOR_ENROLLMENT.md).
