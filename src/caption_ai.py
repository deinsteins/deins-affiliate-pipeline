"""AI captions via the owner's 9Router (OpenAI-compatible, deepseek-chat).

Anti-slop rules (owner's requirement, inspired by antislop.ai.id):
hook first, concrete specifics, no generic AI filler, platform-native
voice. Captions are always written fresh, never copied from the source.
"""
import json

from openai import AsyncOpenAI

from .config import Settings

PROMPT = """Kamu social media manager Indonesia yang nulis caption affiliate kayak creator beneran — bukan brosur, bukan hasil AI generik.

Produk: {product_name}
Teks sumber (referensi fakta saja, JANGAN disalin): {source_text}
Link produk: {product_url}

ATURAN WAJIB (anti-slop):
1. Kalimat pertama = HOOK yang bikin berhenti scroll. Pola yang boleh: pertanyaan yang relatable, momen/skenario konkret ("pas mau kondangan...", "POV: ..."), detail spesifik yang mengejutkan, atau mitos vs fakta. DILARANG membuka dengan nama produk atau kata sifat promosi.
2. Spesifik atau diam: pakai detail nyata dari produknya (model, bahan, fungsi, buat siapa, momen pakainya). Satu detail konkret > tiga kata sifat.
3. FRASA TERLARANG: "tampil kekinian", "desain modern yang nyaman", "cocok untuk berbagai acara", "rayakan momen kebersamaan", "makin kece", "kualitas terbaik", "solusi terbaik", "yuk cek langsung", "jangan sampai ketinggalan", "wajib punya". CTA "{cta}" boleh dipakai SEKALI, di paling akhir, hanya di platform yang cocok.
4. Bahasa Indonesia santai kayak ngobrol sama temen. Kalimat pendek-pendek, ritme bervariasi, boleh fragment. Hindari pola khas AI: "bukan hanya X tapi juga Y", "dengan X kamu bisa Y" berulang, tiga kata sifat berurutan, tanda seru berlebihan (maks 1 per caption).
5. Hashtag: 2-4 saja, spesifik ke produk/kategori (contoh bagus: #batikcouple #batikmodern; contoh buruk: #trendfashion #pakaiangaya #fashion).
6. Tiap platform beda rasa:
   - youtube.title: hook + kata kunci produk, <= 70 karakter, bikin penasaran.
   - youtube.description: baris pertama = hook, lanjut 1-2 baris detail spesifik, lalu "Link produk: {product_url}", terakhir hashtag.
   - threads.text: paling santai, kayak postingan orang beneran; boleh diakhiri pertanyaan balik ke pembaca. <= 480 karakter, link produk di akhir.
   - facebook.text: sedikit lebih informatif dari Threads tapi tetap hook-first. Link produk di akhir.
   - shopee.text: paling langsung: hook manfaat + satu detail + CTA singkat. Tanpa link (link ditempel terpisah di Shopee Video).

CONTOH (produk batik couple ayah-anak):
BURUK (generik): "Tampil kekinian bareng anak dengan Baju Batik Couple Korean Style. Desain modern yang nyaman dipakai untuk berbagai acara. Yuk, cek langsung di Shopee!"
BAGUS: "Anak cowok biasanya kabur pas diajak foto keluarga. Yang ini beda — batiknya couple-an sama ayahnya, model Korean style, nggak kaku kayak batik kondangan jadul."

Balas HANYA JSON valid:
{{"youtube": {{"title": "...", "description": "...", "tags": ["...", "..."]}},
  "threads": {{"text": "..."}},
  "facebook": {{"text": "..."}},
  "shopee": {{"text": "..."}}}}
tags YouTube: 3-6 kata kunci spesifik (bukan hashtag umum)."""


async def generate_captions(settings: Settings, product_name: str | None,
                            source_text: str, product_url: str,
                            style_cfg: dict) -> dict:
    client = AsyncOpenAI(base_url=settings.router_base_url,
                         api_key=settings.router_api_key)
    prompt = PROMPT.format(
        product_name=product_name or "produk pilihan (lihat teks sumber)",
        source_text=(source_text or "")[:600],
        product_url=product_url,
        cta=style_cfg.get("call_to_action", "Link produk ada di deskripsi ya!"))
    resp = await client.chat.completions.create(
        model=settings.router_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.9, max_tokens=2600)
    return json.loads(resp.choices[0].message.content)
