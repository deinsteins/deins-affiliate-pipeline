"""AI captions via the owner's 9Router (OpenAI-compatible).

One product -> three platform-specific outputs, always rewritten fresh
(never copied from the source post) to avoid duplicate-content signals:
  youtube : {title (<=70 chars), description (with affiliate link), tags}
  threads : {post text <= 500 chars, hashtags inline}
  facebook: {caption, hashtags}
  shopee  : {caption for the manual Shopee Video post}
"""
from openai import AsyncOpenAI

from .config import Settings

PROMPT = """Kamu copywriter afiliasi Indonesia. Dari teks sumber berikut,
buat caption BARU (jangan menyalin) untuk produk ini.
Gaya: {style}. Bahasa: {language}. Maksimal {max_hashtags} hashtag relevan.
CTA: "{call_to_action}". Tanpa klaim medis/berlebihan.

Teks sumber: {source_text}
Link produk: {product_url}
Format target: {platform}
"""


async def generate_captions(settings: Settings, source_text: str,
                            product_url: str, style_cfg: dict) -> dict:
    client = AsyncOpenAI(base_url=settings.router_base_url,
                         api_key=settings.router_api_key)
    # TODO: one call per enabled platform; parse JSON; return dict
    ...
