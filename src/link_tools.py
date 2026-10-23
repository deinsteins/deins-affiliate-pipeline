"""Extract Shopee links from a channel post and canonicalise them.

shope.ee / s.shopee.co.id short links redirect to
shopee.co.id/product/<shop_id>/<item_id> or /<slug>-i.<shop>.<item>.
The canonical product URL is what the affiliate portal turns into a
personal affiliate link, and what goes into descriptions on other
platforms in the meantime.
"""
import re
import httpx

URL_RE = re.compile(r"https?://(?:shope\.ee|s\.shopee\.co\.id|shopee\.co\.id)/\S+")


def extract_shopee_urls(text: str) -> list[str]:
    return URL_RE.findall(text or "")


async def resolve_product_url(url: str, client: httpx.AsyncClient) -> str | None:
    """Follow redirects; return canonical product URL or None."""
    # TODO: client.head(url, follow_redirects=True) -> str(resp.url)
    #       validate it contains a shop/item id pair
    ...
