# Analitik: shortlink + statistik platform

## Shortlink (jalan sekarang)

- Setiap item punya shortlink permanen: `<PUBLIC_BASE_URL>/r/<kode>`.
  Kode diturunkan dari id item, jadi tidak berubah walau domain berubah.
- `GET /r/<kode>` bersifat publik (tanpa login dashboard): mencatat klik
  (waktu, referer host, mobile/desktop/bot) lalu redirect 302 ke link
  afiliasi item tersebut. Link yang tidak dikenal -> 404.
- Publisher WAJIB memakai shortlink di caption (`public_link()` di
  `src/analytics.py`), bukan URL afiliasi mentah — kalau tidak, klik
  tidak tercatat.
- Dashboard menampilkan shortlink + jumlah klik per item (drawer),
  panel Analitik (klik 30 hari, item teratas, klik per kategori), dan
  tombol salin shortlink.

### Caveat domain (penting)

`PUBLIC_BASE_URL` di `.env` saat ini adalah URL tunnel Serveo, yang
**berubah setiap VM restart**. Kode shortlink tetap valid, tapi
shortlink yang sudah terlanjur diposting dengan domain tunnel lama
akan mati sampai domain diperbarui. Setelah VM restart:
1. Ambil URL tunnel baru (`journalctl -u affiliate-tunnel`).
2. Update `PUBLIC_BASE_URL` di `.env`, restart `affiliate-dashboard`.
3. Shortlink baru langsung jalan; shortlink lama yang sudah diposting
   tidak bisa diselamatkan tanpa domain tetap.

Solusi permanen: domain sendiri yang mengarah ke dashboard (mis. via
Cloudflare Tunnel atau Serveo subdomain tetap) — begitu domain tetap
ada, isi `PUBLIC_BASE_URL` dengan domain itu sekali, dan semua
shortlink stabil selamanya.

## Statistik platform (siap, menunggu posting)

- Tabel `platform_stats` (per item x platform): views, likes,
  comments, shares, fetched_at.
- `python -m scripts.sync_stats` menarik data:
  - YouTube: butuh `YOUTUBE_API_KEY` di `.env` (Data API v3, read-only,
    cukup untuk video publik). Tanpa key -> `not_configured`.
  - Facebook / Threads: `not_connected` sampai akun posting (fitur #1)
    tersambung dan ada `posts.remote_url`.
- Panel Analitik menampilkan status ini apa adanya — tidak ada angka
  palsu. Begitu video terposting dan key/token tersedia, angka views /
  likes muncul otomatis di panel yang sama.

## Kategori

- Otomatis dari nama produk (keyword Indonesia: fashion, kecantikan,
  rumah, dapur, elektronik, kesehatan, anak & mainan, olahraga,
  lainnya) via `categorize()`; bisa diubah per item lewat dropdown
  kategori di drawer dashboard (POST /api/items/{id}/category).
- Panel Analitik merangkum klik per kategori + rata-rata klik per
  item — inilah jawaban "kategori apa yang beneran laku".
