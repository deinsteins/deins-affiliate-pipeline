"""Extract Shopee links from a channel post and canonicalise them.

Short links (s.shopee.co.id / s.shopee.com.my / shope.ee) redirect to the
canonical product URL. Indonesian product URLs embed the product name in
the slug: shopee.co.id/<Product-Name>-i.<shop_id>.<item_id> — the name is
free context for caption generation. Malaysian URLs use the plain
/<shop>/<shop_id>/<item_id> form (no name); those items are flagged
region=MY and get their name later (vision / manual).
"""
import re
import httpx

URL_RE = re.compile(r"https?://(?:shope\.ee|s\.shopee\.co\.id|s\.shopee\.com\.my|shopee\.co\.id|shopee\.com\.my)/\S+")
ID_ITEM_RE = re.compile(r"-i\.(\d+)\.(\d+)")
GENERIC_ITEM_RE = re.compile(r"/(\d{6,})/(\d{6,})")


def extract_shopee_urls(text: str) -> list[str]:
    return [u.rstrip(").,") for u in URL_RE.findall(text or "")]


def parse_product_url(url: str) -> dict:
    """Pull region / shop / item / name out of a canonical product URL."""
    info = {"product_url": url, "region": None, "shop_id": None,
            "item_id": None, "product_name": None}
    if "shopee.co.id" in url:
        info["region"] = "ID"
    elif "shopee.com.my" in url:
        info["region"] = "MY"
    m = ID_ITEM_RE.search(url)
    if m:
        info["shop_id"], info["item_id"] = m.group(1), m.group(2)
        slug = url.split("/")[-1].split("-i.")[0]
        info["product_name"] = slug.replace("-", " ").strip() or None
    else:
        m = GENERIC_ITEM_RE.search(url)
        if m:
            info["shop_id"], info["item_id"] = m.group(1), m.group(2)
    return info


async def resolve_product_url(url: str, client: httpx.AsyncClient) -> dict | None:
    """Follow redirects; return parse_product_url(final) or None."""
    try:
        resp = await client.get(url, follow_redirects=True, timeout=30)
        final = str(resp.url)
    except Exception:
        return None
    if "shopee" not in final:
        return None
    return parse_product_url(final)


async def remap_region(product_name: str, to_region: str = "ID") -> str | None:
    """Region remap (owner's design): the VIDEO from a Shopee MY post is
    reused as-is; only the product link is replaced by the best-matching
    Shopee ID product (name search via the logged-in browser session —
    Shopee's raw APIs 403 this server). Implemented in the browser
    worker step; returns None until that step runs."""
    return None
