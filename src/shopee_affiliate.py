"""Owner's Shopee affiliate links — two tiers.

Tier 1 — an_redir (NO API credentials needed, only the owner's
affiliate_id). This is Shopee's own documented short-link format for
affiliate partners (Shopee Help Center, "Affiliate Short Link
Implementation Guide"):
    https://s.shopee.co.id/an_redir?origin_link=<urlencoded canonical
    product URL>&affiliate_id=<id>&sub_id=<sub>
Clicks resolve to the product page carrying utm_source=an_<id> and
utm_medium=affiliates, i.e. attributed to the owner.

Tier 2 — Shopee Affiliate Open API (needs AppId + Secret from the
affiliate portal's API Access section). Indonesia endpoint:
    https://open-api.affiliate.shopee.co.id/graphql
Auth (per the official SDK docs + independent plugin docs):
    Authorization: SHA256 Credential={AppId}, Timestamp={unix},
                   Signature={Signature}
    Signature = SHA256(AppId + Timestamp + Payload + Secret)
where Payload is the EXACT JSON body sent. The secret is never sent,
only used to compute the signature. Strategy mirrors the SDK:
productOfferV2 first (commission offer link when the product has one),
fall back to generateShortLink.

Caveat, stated plainly: the GraphQL field shapes below follow the
ecosystem's documented operation names (generateShortLink,
productOfferV2). Response parsing is defensive (it walks the returned
data for the first https Shopee URL / offerLink value), and any
unexpected shape is surfaced with the raw response so a single live
test with real credentials reveals the true shape immediately.
"""

import hashlib
import json
import time
from urllib.parse import quote, urlparse

import httpx

ID_ENDPOINT = "https://open-api.affiliate.shopee.co.id/graphql"
AN_REDIR_BASE = "https://s.shopee.co.id/an_redir"


def canonical_product_url(url: str) -> str:
    """Strip tracking params; the origin link must be clean."""
    return (url or "").split("?")[0].split("#")[0]


def build_an_redir(product_url: str, affiliate_id: str,
                   sub_id: str = "") -> str:
    """Tier 1: documented an_redir link. No API call involved."""
    origin = quote(canonical_product_url(product_url), safe="")
    link = f"{AN_REDIR_BASE}?origin_link={origin}&affiliate_id={affiliate_id}"
    if sub_id:
        link += f"&sub_id={quote(sub_id, safe='')}"
    return link


def sign(app_id: str, timestamp: int, payload: str, secret: str) -> str:
    """SHA256(AppId + Timestamp + Payload + Secret), hex digest."""
    return hashlib.sha256(
        f"{app_id}{timestamp}{payload}{secret}".encode()).hexdigest()


class ShopeeAffiliateError(Exception):
    pass


class ShopeeAffiliateClient:
    """Tier 2: signed GraphQL client for the Affiliate Open API."""

    def __init__(self, app_id: str, secret: str,
                 endpoint: str = ID_ENDPOINT, timeout: float = 60.0):
        self.app_id = app_id
        self.secret = secret
        self.endpoint = endpoint
        self.timeout = timeout

    def _post(self, query: str, variables: dict,
              _retry_swapped: bool = False) -> dict:
        body = json.dumps({"query": query, "variables": variables},
                          separators=(",", ":"), ensure_ascii=False)
        ts = int(time.time())
        sig = sign(self.app_id, ts, body, self.secret)
        headers = {
            "Content-Type": "application/json",
            "Authorization": (
                f"SHA256 Credential={self.app_id}, "
                f"Timestamp={ts}, Signature={sig}"),
        }
        try:
            resp = httpx.post(self.endpoint, content=body.encode(),
                              headers=headers, timeout=self.timeout)
        except Exception as e:  # network/proxy failure
            raise ShopeeAffiliateError(f"request gagal: {e}") from e
        try:
            data = resp.json()
        except Exception as e:
            raise ShopeeAffiliateError(
                f"respons bukan JSON (HTTP {resp.status_code})") from e
        errors = data.get("errors") or []
        # Code 10020 = bare signature error: documented retry is to send
        # Signature before Timestamp with a fresh timestamp, same body.
        if errors and any(e.get("code") == 10020 or "signature" in
                          str(e.get("message", "")).lower()
                          for e in errors) and not _retry_swapped:
            ts2 = int(time.time())
            sig2 = sign(self.app_id, ts2, body, self.secret)
            headers["Authorization"] = (
                f"SHA256 Signature={sig2}, "
                f"Credential={self.app_id}, Timestamp={ts2}")
            try:
                resp = httpx.post(self.endpoint, content=body.encode(),
                                  headers=headers, timeout=self.timeout)
                data = resp.json()
            except Exception as e:
                raise ShopeeAffiliateError(
                    f"retry signature gagal: {e}") from e
            errors = data.get("errors") or []
        if errors:
            raise ShopeeAffiliateError(
                f"API error: {json.dumps(errors, ensure_ascii=False)[:400]}")
        return data.get("data") or {}

    @staticmethod
    def _first_url(node, keys=("offerLink", "shortLink", "url")):
        """Walk a GraphQL data dict for the first usable Shopee URL."""
        if isinstance(node, str) and node.startswith("https://"):
            return node
        if isinstance(node, dict):
            for k in keys:
                if isinstance(node.get(k), str) and \
                        node[k].startswith("https://"):
                    return node[k]
            for v in node.values():
                found = ShopeeAffiliateClient._first_url(v, keys)
                if found:
                    return found
        if isinstance(node, list):
            for v in node:
                found = ShopeeAffiliateClient._first_url(v, keys)
                if found:
                    return found
        return None

    def generate_short_link(self, origin_url: str,
                            sub_ids: list[str] | None = None) -> str:
        query = (
            "mutation GenerateShortLink($originUrl: String!, "
            "$subIds: [String!]) { generateShortLink(originUrl: $originUrl, "
            "subIds: $subIds) { shortLink } }")
        data = self._post(query, {"originUrl": origin_url,
                                  "subIds": sub_ids or []})
        url = self._first_url(data)
        if not url:
            raise ShopeeAffiliateError(
                f"generateShortLink tanpa shortLink: "
                f"{json.dumps(data, ensure_ascii=False)[:300]}")
        return url

    def product_offer(self, shop_id: str, item_id: str) -> dict | None:
        query = (
            "query ProductOfferV2($shopId: Long!, $itemId: Long!) { "
            "productOfferV2(shopId: $shopId, itemId: $itemId) { "
            "offerLink productName imageUrl priceMin priceMax "
            "commissionRate } }")
        try:
            data = self._post(query, {"shopId": int(shop_id),
                                      "itemId": int(item_id)})
        except ShopeeAffiliateError:
            return None
        url = self._first_url(data, keys=("offerLink",))
        if not url:
            return None
        return {"affiliate_url": url, "raw": data}

    def generate_link(self, product_url: str, shop_id: str | None,
                      item_id: str | None,
                      sub_ids: list[str] | None = None
                      ) -> tuple[str, str]:
        """(affiliate_url, source). Offer first, short link fallback."""
        if shop_id and item_id:
            offer = self.product_offer(shop_id, item_id)
            if offer:
                return offer["affiliate_url"], "api_offer"
        return (self.generate_short_link(product_url, sub_ids),
                "api_short")


def effective_link(item) -> str:
    """What publishers must put in captions: owner's link if present.

    Works for dicts and sqlite3.Row alike."""
    try:
        mine = item["affiliate_url"]
    except Exception:
        mine = None
    return mine or item["product_url"]


def sub_id_for(platform: str, base: str = "deins-pipeline") -> str:
    """sub_id per platform, so the affiliate report splits by channel.

    Shopee sub_id format: up to 5 dash-separated parts; we use two
    (base + platform), which keeps reports readable."""
    return f"{base}-{platform}"


def platform_sub_ids(platform: str, base: str = "deins-pipeline"
                     ) -> list[str]:
    return [sub_id_for(platform, base)]
