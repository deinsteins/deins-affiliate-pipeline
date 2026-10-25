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

## Backend hybrid: Flow (kredit Pro) vs Veo API

Job punya kolom `backend`: `flow` (default) atau `veo`.

- **Flow** (pakai kredit langganan Google AI Pro, gratis sampai kredit habis):
  alurnya beda karena Flow tidak punya API publik. `run_job()` hanya
  menjalankan script, menulis worklist ke
  `storage/video_jobs/<id>/flow_worklist.json`, lalu parkir job di
  status `queued_flow`. Agen mengambil worklist itu dan menjalankan
  browser task ke Flow (URL: labs.google/fx/tools/flow) dengan
  instruksi dari `src/flow_backend.py::build_browser_assignment()`:
  cek login dulu (kalau belum login → lapor LOGIN_NEEDED, tidak
  generate, tidak login atas nama owner), lalu 1 generasi per scene
  (model = FLOW_MODEL, default fast, 9:16), download tiap klip.
  Setelah klip kembali, `continue_flow_job()` memverifikasi 4 klip,
  mencatat estimasi kredit (fast 20/klip, lite 10, quality 100),
  lalu assemble + package seperti biasa.
- **Veo API**: seperti sebelumnya — butuh GEMINI_API_KEY + billing,
  jalan sampai selesai di background.
- **Satu-satunya prasyarat Flow**: akun Google owner sudah login di
  browser server (sekali saja, seperti login Shopee dulu). Tanpa itu
  browser task berhenti di LOGIN_NEEDED dan tidak ada kredit terpakai.
- **Pelacak kredit**: dashboard menampilkan estimasi kredit Flow
  terpakai bulan berjalan vs FLOW_CREDITS_BUDGET (default 1000 =
  Google AI Pro). Estimasi dari model, bukan dibaca dari UI Flow.
  Kredit tidak rollover; generasi gagal tidak makan kredit.
- **Jangan dicampuradukkan**: kredit Flow TIDAK bisa dipakai lewat
  Gemini API — jalur billing-nya terpisah. Satu-satunya pengecualian
  yang masih perlu diverifikasi di akun owner: laporan Oktober 2026
  soal $10 kredit Cloud/bulan untuk paket Pro (lihat catatan di
  chat 2026-10-25).
