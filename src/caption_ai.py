"""AI captions via the owner's 9Router (OpenAI-compatible, deepseek-chat).

One call per item returns JSON for every platform. Captions are always
written fresh from the product name + source text (never copied), in
casual persuasive Indonesian, with the product link embedded.
"""
import json

from openai import AsyncOpenAI

from .config import Settings

PROMPT = """Kamu copywriter afiliasi Indonesia. Buat caption BARU (jangan menyalin teks sumber) untuk produk ini.

Produk: {product_name}
Teks sumber (referensi saja): {source_text}
Link produk: {product_url}
Gaya: {style}
Maksimal {max_hashtags} hashtag relevan per platform. CTA: "{cta}"
Tanpa klaim medis/berlebihan, tanpa janji palsu.

Balas HANYA JSON valid dengan struktur:
{{"youtube": {{"title": "...", "description": "...", "tags": ["...", "..."]}},
  "threads": {{"text": "..."}},
  "facebook": {{"text": "..."}},
  "shopee": {{"text": "..."}}}}
Aturan: title YouTube <= 70 karakter. Description YouTube memuat link produk + hashtag. Teks Threads <= 480 karakter termasuk link + hashtag. Facebook & Shopee: 2-4 kalimat + link + hashtag."""


async def generate_captions(settings: Settings, product_name: str | None,
                            source_text: str, product_url: str,
                            style_cfg: dict) -> dict:
    client = AsyncOpenAI(base_url=settings.router_base_url,
                         api_key=settings.router_api_key)
    prompt = PROMPT.format(
        product_name=product_name or "produk pilihan (lihat teks sumber)",
        source_text=(source_text or "")[:600],
        product_url=product_url,
        style=style_cfg.get("style", "santai, persuasif"),
        max_hashtags=style_cfg.get("max_hashtags", 8),
        cta=style_cfg.get("call_to_action", "Link produk ada di deskripsi ya!"))
    resp = await client.chat.completions.create(
        model=settings.router_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.8, max_tokens=1200)
    return json.loads(resp.choices[0].message.content)
