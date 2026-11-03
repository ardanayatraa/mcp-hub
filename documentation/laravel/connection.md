# Pairing dan konfigurasi

Pairing mengikat satu aplikasi, environment, dan URL sumber dengan Hub. Gunakan code sekali pakai dari admin yang memiliki scope aplikasi tersebut.

## Identitas aplikasi

```dotenv
MCP_HUB_APP_KEY=your_app
MCP_HUB_ENVIRONMENT=production
MCP_HUB_BASE_URL=https://app.example.com
```

Samakan URL sumber dengan pendaftaran Hub. Environment/source URL menjadi bagian dari binding proposal, record reference, dan artifact. Konfigurasi environment yang sudah dipasang operator tetap lebih tinggi prioritasnya daripada bundle tersimpan.

## Pairing melalui prompt

```bash
php artisan mcp-hub:connect --hub=https://hub.example.com
php artisan mcp-hub:status
php artisan mcp-hub:doctor --online
```

Masukkan code pada prompt tersembunyi. Opsi `--code` tersedia untuk otomasi terkendali, tetapi prompt menghindari code masuk shell history. Jangan menaruh code/proof di URL, log, atau screenshot.

Proof instalasi disimpan terenkripsi sebelum claim selesai. Aktivasi mengikuti validasi health/kontrak. Direktori `storage/app/mcp-hub` harus privat, dapat ditulis proses aplikasi, dan dipertahankan lintas deployment.

## Recovery

| Kondisi | Tindakan |
|---|---|
| Respons pairing hilang | `php artisan mcp-hub:connect --resume` |
| Code expired/claim tidak dapat dipulihkan | Minta replacement pada admin berwenang |
| Replacement tersedia | Connect menggunakan `--hub=... --replace` |
| Resource/kontrak berubah | `php artisan mcp-hub:sync` |
| Koneksi dicabut | `php artisan mcp-hub:disconnect` |

Replacement mencabut credentials lama, mempertahankan restrictions profil/tools, dan tidak memberikan write scope. Disconnect menonaktifkan koneksi lokal dahulu; revocation remote tetap pending bila Hub belum mengakuinya.

## Import koneksi existing

Untuk credentials yang sudah diprovisikan, siapkan `MCP_HUB_URL`, `MCP_HUB_CLIENT_KEY`, `MCP_HUB_APP_TOKEN`, serta `MCP_HUB_DELEGATION_SECRET`, selain identitas di atas.

```bash
php artisan mcp-hub:connect --import-env --dry-run
php artisan mcp-hub:connect --import-env
```

App token/delegation secret minimal 32 karakter acak. Salinan koneksi disimpan terenkripsi pada `storage/app/mcp-hub/connection.enc` menggunakan `APP_KEY`.

`MCP_HUB_URL` menunjuk endpoint Hub `/mcp`; `MCP_HUB_BASE_URL` menunjuk sumber Laravel. HTTP hanya untuk loopback di environment local/testing. Produksi menggunakan HTTPS.
