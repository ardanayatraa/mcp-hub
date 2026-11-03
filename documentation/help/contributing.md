# Kontribusi dokumentasi

Portal dibangun dari Markdown pada `documentation/` menggunakan Material for MkDocs. Referensi API tertentu disinkronkan dari kontrak Hub pada setiap build agar tidak perlu disalin manual.

## Preview lokal

Gunakan Python 3.12 dari root repository:

```bash
python -m pip install -r requirements-docs.txt
python scripts/build_docs_reference.py
python -m mkdocs serve --dev-addr 127.0.0.1:18181
```

Gunakan port lain bila 18181 dipakai; jangan menghentikan layanan yang tidak terkait.

## Struktur

| Lokasi | Isi |
|---|---|
| `documentation/start` | Konsep, jalur implementasi, versi |
| `documentation/hub` | Pengelolaan Hub |
| `documentation/laravel` | Integrasi aplikasi |
| `documentation/reference` | API/config serta hasil sinkronisasi |
| `documentation/help` | Keamanan dan troubleshooting |
| `documentation/assets` | Logo/styles lokal |
| `mkdocs.yml` | Navigasi dan konfigurasi situs |

`admin-api.md`, `connector-contract.md`, `tools.md`, dan `profiles.md` pada reference dihasilkan oleh script sinkronisasi. Edit sumber di `docs/`, bukan hasil build.

## Build dan publikasi

```bash
python scripts/build_docs_reference.py
python -m mkdocs build --strict
```

Workflow Documentation memeriksa PR dan menerbitkan artifact statis ke GitHub Pages setelah perubahan masuk `main`. Hanya direktori dokumentasi yang dibangun; environment, source aplikasi, artifacts privat, dan evidence tidak dipublikasikan.

Jelaskan perilaku berdasarkan kode/rilis yang diperiksa. Gunakan domain contoh, pisahkan versi package dari server Hub, dan jangan memasukkan credentials/alamat deployment pengguna pada contoh.
