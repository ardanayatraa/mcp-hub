---
hide:
  - toc
---
<div class="hero" markdown>
<p class="eyebrow">Developer documentation</p>

# Satu penghubung AI.<br>Data dalam kendali aplikasi.

Bangun integrasi AI yang mengikuti izin pengguna, scope tenant, dan aturan bisnis aplikasi Anda. MCP Hub mengelola koneksi dan tools; package Laravel menyediakan batas akses di sisi aplikasi.

[Mulai implementasi](start/quickstart.md){ .md-button .md-button--primary }
[Instal Laravel 1.0](laravel/install.md){ .md-button }

<p class="meta">Laravel package 1.0.0 stable · Hub Python edition · Diperiksa 3 November 2026</p>
</div>

## Pilih jalur Anda

<div class="doc-cards" markdown>
<div class="doc-card" markdown>
<span class="label">Untuk pengelola platform</span>

## MCP Hub

Jalankan Hub, hubungkan aplikasi, atur client key dan tools, lalu kelola akses model dari satu tempat.

[Siapkan Hub →](hub/local.md)
</div>
<div class="doc-card" markdown>
<span class="label">Untuk developer aplikasi</span>

## Laravel MCP Hub

Pasang package Composer, daftarkan resource yang ditinjau, lalu terapkan identitas dan izin pengguna dari aplikasi Anda sendiri.

[Integrasikan Laravel →](laravel/install.md)
</div>
</div>

## Cara komponen bekerja bersama

<div class="flow" role="img" aria-label="Client AI memanggil Hub; Hub meneruskan permintaan terverifikasi ke aplikasi Laravel">
<div class="node"><strong>Client AI</strong><small>MCP client atau chat aplikasi</small></div>
<div class="arrow" aria-hidden="true">→</div>
<div class="node"><strong>MCP Hub</strong><small>Tools, key, profil, model, audit</small></div>
<div class="arrow" aria-hidden="true">→</div>
<div class="node"><strong>Aplikasi Laravel</strong><small>Identitas, policy, record, persetujuan</small></div>
</div>

Hub memeriksa akses pada setiap pemanggilan. Aplikasi memeriksa ulang pengguna dan record sebelum memberikan data atau menjalankan perubahan. Model tidak menetapkan identitas pengguna, tenant, URL sumber, maupun persetujuan transaksi.

| Kebutuhan | Panduan |
|---|---|
| Memahami batas tanggung jawab | [Konsep dan arsitektur](start/concepts.md) |
| Menghubungkan aplikasi pertama | [Pairing Laravel](laravel/connection.md) |
| Mengekspos data secara terbatas | [Resource dan izin](laravel/resources.md) |
| Membuat perubahan dengan persetujuan | [Proposal CRUD](laravel/commands.md) |
| Membuat laporan privat | [CSV, XLSX, dan PDF](laravel/exports.md) |
| Menangani koneksi gagal | [Pemecahan masalah](help/troubleshooting.md) |

[Repository Hub](https://github.com/ardanayatraa/mcp-hub) · [Repository Laravel](https://github.com/ardanayatraa/laravel-mcp-hub) · [Package Composer](https://packagist.org/packages/ardanayatraa/laravel-mcp-hub)
