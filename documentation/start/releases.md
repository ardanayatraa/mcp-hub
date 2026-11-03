# Status dan versi

## Package Laravel

**`ardanayatraa/laravel-mcp-hub` 1.0.0** adalah rilis stable pertama, diterbitkan 3 November 2026. Instalasi memakai `^1.0` tanpa flag `@alpha`.

[Rilis dan ZIP terverifikasi](https://github.com/ardanayatraa/laravel-mcp-hub/releases/tag/v1.0.0) · [Packagist](https://packagist.org/packages/ardanayatraa/laravel-mcp-hub) · [CI tag 1.0.0](https://github.com/ardanayatraa/laravel-mcp-hub/actions/runs/41553234044)

Rilis mencakup pairing, SQL nonce, proposal CRUD, settings/chat, Gateway SDK, dan ekspor privat. Seluruh 16 job rilis lulus: 13 kombinasi PHP/Laravel, PostgreSQL, aset chat, serta distribusi. Suite package mengumpulkan 116 tes dengan dua tes opt-in; pemeriksaan PostgreSQL dijalankan terpisah. Hasil CI bukan benchmark kapasitas produksi.

## Kompatibilitas yang diuji

| Laravel | PHP |
|---|---|
| 5.8 | 7.2, 7.4 |
| 6 | 7.2 |
| 7 | 7.2 |
| 8 | 7.3 |
| 9 | 8.0, 8.2 |
| 10 | 8.1 |
| 11 | 8.2 |
| 12 | 8.2, 8.4 |
| 13 | 8.3, 8.4 |

Kebutuhan efektif PHP mengikuti framework/dependensi host. Matriks menguji patch acuan di [README package](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/README.md), bukan semua kombinasi patch. Kompatibilitas package tidak mengembalikan pemeliharaan keamanan upstream yang sudah berakhir.

## Server Hub

Dokumentasi Hub mengikuti edisi Python pada `main`. Nomor stable package Laravel tidak otomatis menjadi nomor rilis server Hub. Tinjau commit server, schema database, dan kontrak sebelum upgrade terkoordinasi. Edisi JavaScript pada `mcp-js` tidak dicakup panduan operasi ini.

Pertahankan lock file host dan ikuti [upgrade Laravel](../laravel/upgrade.md). Koreksi rilis diterbitkan sebagai patch baru; tag 1.0.0 tidak dipindahkan.
