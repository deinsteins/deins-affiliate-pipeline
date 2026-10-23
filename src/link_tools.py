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


async def remap_region(product_name: str, to_region: str = "ID") -> str | None:
    """Region remap (owner's request): the VIDEO from a Shopee MY post is
    reused as-is; only the product link is replaced. Resolve the MY item
    name, search the same product on Shopee ID, return the best match
    (highest sales, Mall/official preferred). Matching is name-based —
    the package keeps the matched name + thumbnail for a human glance.
    NOTE: shopee.* APIs 403 this server's datacenter IP, so name
    resolution goes through a headless-browser step, not raw HTTP."""


async def resolve_product_url(url: str, client: httpx.AsyncClient) -> str | None:
    """Follow redirects; return canonical product URL or None."""
    # TODO: client.head(url, follow_redirects=True) -> str(resp.url)
    #       validate it contains a shop/item id pair
    ...
