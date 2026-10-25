# Link afiliasi milik sendiri

Semua paket awalnya memakai link si pembagi channel (ID afiliasi
mereka). Modul `src/shopee_affiliate.py` menggantinya dengan link
atas nama pemilik pipeline. Dua tier:

## Tier 1 — an_redir (tanpa API, cukup affiliate_id)

Format resmi Shopee untuk affiliate partner (Help Center, "Affiliate
Short Link Implementation Guide"):

```
https://s.shopee.co.id/an_redir?origin_link=<URL produk>&affiliate_id=<ID>&sub_id=<sub>
```

Cara dapat `affiliate_id`:
1. Buka aplikasi Shopee → bagikan satu produk apa pun (tombol share).
2. Salin link-nya, cari `utm_source=an_XXXXXXXXXXX` — angka setelah
   `an_` itulah affiliate_id kamu.
3. Isi di `.env`: `SHOPEE_AFFILIATE_ID=XXXXXXXXXXX`.

Sub-ID default: `deins-pipeline-<platform>` (mis. `deins-pipeline-youtube`),
supaya laporan afiliasi Shopee bisa dipilah per platform.

## Tier 2 — Shopee Affiliate Open API (lebih lengkap)

Endpoint Indonesia: `https://open-api.affiliate.shopee.co.id/graphql`
Auth: `Authorization: SHA256 Credential={AppId}, Timestamp={unix},
Signature=SHA256(AppId + Timestamp + Payload + Secret)`.

Cara dapat kredensial: portal Shopee Affiliate (desktop) → API Access →
App ID + Secret. Isi di `.env`:

```
SHOPEE_AFFILIATE_APP_ID=...
SHOPEE_AFFILIATE_SECRET=...
```

Keuntungan tier 2: `productOfferV2` memberi offer link produk yang
punya komisi (kadang komisi XTRA), fallback otomatis ke
`generateShortLink`; nanti juga bisa menarik laporan konversi.

## Cara kerja di pipeline

- Worker: setiap paket baru langsung dibuatkan link afiliasinya
  (tier 2 kalau kredensial API ada, kalau tidak tier 1 kalau
  affiliate_id ada, kalau tidak keduanya dilewati diam-diam).
- Backfill paket lama: `python -m scripts.backfill_affiliate`
  (`--dry-run` untuk simulasi, `--limit N`, `--api`/`--anredir`
  untuk memaksa mode).
- Dashboard: tiap kartu yang sudah punya link menampilkan badge
  "link ✓"; di drawer ada kotak link afiliasi + tombol
  "Buat link afiliasi" untuk item yang belum punya.
- Publisher (saat diimplementasikan) WAJIB memakai
  `effective_link(item)` — link afiliasi kalau ada, kalau tidak
  product_url biasa — jangan pernah menempel product_url mentah.

## Catatan kejujuran

- Bentuk query GraphQL (`generateShortLink`, `productOfferV2`)
  mengikuti nama operasi yang didokumentasikan ekosistem SDK/plugin;
  parsing respons dibuat defensif dan error mentah ditampilkan, jadi
  satu panggilan live dengan kredensial asli langsung membuktikan
  bentuknya benar atau perlu dikoreksi.
- Link an_redir hanya mengatribusikan klik kalau akunnya memang
  terdaftar sebagai Shopee Affiliate. Kalau akun belum terdaftar,
  daftar dulu lewat aplikasi Shopee (Saya → Shopee Affiliate).
