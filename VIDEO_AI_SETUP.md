# Video AI: produk terbaik -> script -> video -> antrean approve

## Alur

1. **Discovery** — panel "Video AI" di dashboard menampilkan produk
   terbaik berdasarkan klik shortlink (analitik), plus form produk
   manual (link + nama). Klik "Generate" membuat satu `video_jobs`.
2. **Script** — router LLM menulis storyboard JSON 4 scenes (hook,
   demo, manfaat, CTA). Butuh router hidup (9Router); kalau router
   mati, job gagal dengan pesan jelas dan bisa di-retry nanti.
3. **Video** — satu klip Veo 8 detik per scene (potret 9:16),
   disambung ffmpeg jadi satu video vertikal ~32 detik.
4. **Paket** — video + captions.json + links.txt + link afiliasi
   (an_redir kalau shop/item dikenal) masuk `storage/ready/` sebagai
   item `channel='ai_generated'` dengan `review='pending'`.
5. **Antrean** — paket muncul di antrean review dashboard seperti
   biasa; tombol "Lihat di antrean" di panel Video AI membukanya.

## Google Flow vs Veo (penting)

Google Flow (aplikasi web labs.google) **tidak punya API publik**.
Mengotomasi UI web-nya lewat browser itu rapuh (login, antrean
generasi bermenit-menit, UI berubah) dan tidak cocok untuk pipeline
tanpa awak. Jalur programatik yang didukung ke mesin yang sama
adalah **Veo via Gemini API** — itulah yang dipakai backend ini
(`src/veo_backend.py`, model default `veo-3.1-fast-generate-preview`,
bisa diubah ke `veo-3.1-generate-preview` lewat `VEO_MODEL`).
Kalau suatu hari kamu tetap ingin Flow web-nya, itu bisa ditambah
sebagai backend eksperimental terpisah — bukan jalur utama.

## Yang dibutuhkan

- `GEMINI_API_KEY` di `.env` + billing aktif di project Google Cloud
  (Veo berbayar per detik video; cek harga terbaru di halaman
  pricing Gemini API). Tanpa key, job gagal jelas di langkah video.
- Router hidup untuk script (9Router). Script yang sudah jadi
  tersimpan di job, jadi retry tidak membayar script dua kali;
  klip scene yang sudah jadi juga dipakai ulang saat retry.
- ffmpeg (sudah ada di server) untuk stitching.

## Perintah

- Dashboard: panel Video AI (buat job, jalankan, lihat status).
- CLI: `python -m scripts.run_video_job <job_id>` (jalan sinkron;
  untuk job beneran jalankan di bawah nohup).
- Job gagal bisa di-retry dari dashboard (tombol Jalankan) — proses
  dilanjutkan dari langkah yang gagal, bukan dari nol.
