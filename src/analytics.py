"""Analytics: own shortlinks with click tracking + platform stats.

Two halves, deliberately separated:

1. SHORTLINK (works today). Every item gets a permanent short code
   derived from its id, so the code never changes even if the public
   domain does. The dashboard serves GET /r/<code> WITHOUT auth: it
   logs the click, then 302-redirects to the item's effective
   affiliate link. Publishers must put the SHORTLINK in captions, not
   the raw affiliate URL — otherwise clicks bypass measurement.
   Caveat, stated honestly: the public domain is currently the
   Serveo tunnel URL, which changes on every VM replacement. Codes
   survive that (only the domain prefix changes), but shortlinks
   already posted under an old tunnel URL will break until a stable
   domain fronts the dashboard. See ANALYTICS_SETUP.md.

2. PLATFORM STATS (ready, waiting on feature #1 publishers). Once
   videos are actually posted, posts.remote_url holds the platform
   URL and this module pulls views/likes/comments back into
   platform_stats. Until posting accounts exist, sync_platform_stats()
   reports each platform as not_configured / not_connected instead of
   inventing numbers — a dashboard showing "belum terhubung" is more
   useful than one showing zeros that look like failure.

Categories are keyword-based on the product name (Indonesian),
overridable per item in the dashboard. They exist so the analytics
panel can answer "kategori apa yang beneran laku" from clicks.
"""

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from .shopee_affiliate import effective_link

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def short_code(item_id: int) -> str:
    """Permanent 6-char code for an item id (deterministic, opaque)."""
    digest = hashlib.sha256(f"deins-r-{item_id}".encode()).digest()
    num = int.from_bytes(digest[:5], "big")
    out = ""
    for _ in range(6):
        out += _ALPHABET[num % 36]
        num //= 36
    return out


def shortlink(item_id: int, base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    return f"{base}/r/{short_code(item_id)}" if base else f"/r/{short_code(item_id)}"


def public_link(item, base_url: str) -> str:
    """What publishers put in captions: the trackable shortlink."""
    return shortlink(int(item["id"]), base_url)


def _device_class(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        return "mobile"
    if "bot" in ua or "spider" in ua or "crawl" in ua:
        return "bot"
    return "desktop"


def record_click(conn, item_id: int, request) -> None:
    """Log one redirect click. No raw IPs stored, only referer host."""
    referer = ""
    try:
        referer = urlparse(request.headers.get("referer", "")).netloc
    except Exception:
        referer = ""
    conn.execute(
        "INSERT INTO clicks (item_id, ts, referer, device) VALUES (?, ?, ?, ?)",
        (item_id, datetime.now(timezone.utc).isoformat(), referer,
         _device_class(request.headers.get("user-agent", ""))))
    conn.commit()


def click_counts(conn, days: int | None = None) -> dict[int, int]:
    q = "SELECT item_id, COUNT(*) FROM clicks"
    args: list = []
    if days is not None:
        q += " WHERE ts >= datetime('now', ?)"
        args.append(f"-{days} days")
    q += " GROUP BY item_id"
    return dict(conn.execute(q, args).fetchall())


def daily_clicks(conn, days: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT substr(ts, 1, 10) AS day, COUNT(*) FROM clicks "
        "WHERE ts >= datetime('now', ?) GROUP BY day ORDER BY day",
        (f"-{days} days",)).fetchall()
    return [{"day": r[0], "clicks": r[1]} for r in rows]


# ---------------------------------------------------------------- categories
CATEGORIES: dict[str, list[str]] = {
    "fashion": ["baju", "celana", "jaket", "kardigan", "dress", "gamis",
                "hijab", "sepatu", "sandal", "tas ", "tas,", "dompet",
                "topi", "kemeja", "kaos", "rok ", "jeans", "kulot",
                "piyama", "bra ", "singlet", "tanktop", "hoodie",
                "cardigan", "outer", "selop", "clogs", "wedges",
                "jepit", "jepitan", "bando", "pita rambut",
                "jacket", "pants", "skirt", "blouse", "shoes", "heels",
                "windbreaker", "crop", "mukena", "kacamata", "sunglasses",
                "bag", "charm", "sweater", "blazer", "tunik"],
    "kecantikan": ["lip ", "lipstik", "blush", "make up", "makeup",
                   "skincare", "serum", "cushion", "bedak", "eyeshadow",
                   "maskara", "bulu mata", "gloss", "kosmetik",
                   "kuas make", "brush make"],
    "rumah": ["rak ", "rak,", "organizer", "kotak penyimpanan",
              "gantungan", "hook", "keranjang", "lemari", "cermin",
              "karpet", "gorden", "bantal", "selimut", "laci",
              "troli", "susun", "penyimpanan", "wadah",
              "kursi", "meja", "sofa", "tempat tidur", "folding",
              "kasur"],
    "dapur": ["panci", "wajan", "pisau", "botol minum", "tumbler",
              "sendok", "garpu", "sumpit", "dispenser", "pembersih",
              "saringan", "wastafel", "pel ", "mop", "sapu",
              "minyak goreng", "bumbu", "tempat telur", "egg",
              "gelas", "mangkok", "piring"],
    "elektronik": ["kipas", "charger", "kabel", "headset", "earphone",
                   "kamera", "tripod", "tongsis", "lampu", "stop kontak",
                   "speaker", "power bank", "catokan", "hair dryer",
                   "blender", "chopper", "mixer", "setrika",
                   "casing", "case", "iphone", "handphone", "powerbank",
                   "airpods", "tws"],
    "kesehatan": ["pijat", "massager", "pemijat", "terapi", "penyangga",
                  "postur", "korset", "obat", "vitamin", "masker"],
    "anak & mainan": ["squishy", "mainan", "boneka", "lego", "balon",
                      "kostum", "onesie", "anak", "bayi", "balita",
                      "robot", "building", "puzzle"],
    "olahraga": ["yoga", "matras", "dumbbell", "skipping", "gym",
                 "olahraga", "lari ", "badminton", "sepeda"],
    "makanan": ["sambal", "bawang", "kue", "bakpia", "snack", "kopi",
                "coklat", "kerupuk", "basreng", "rendang", "dendeng",
                "abon", "saos", "kecap", "mie", "sarden", "biskuit",
                "roti", "dodol", "emping", "teri", "paru", "oseng"],
}


def categorize(name: str | None) -> str:
    """Keyword category for a product name; 'lainnya' when unsure."""
    text = f" {(name or '').lower()} "
    best, best_hits = "lainnya", 0
    for cat, keywords in CATEGORIES.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


def backfill_categories(conn) -> int:
    """(Re)assign categories for all named items without an override."""
    rows = conn.execute("SELECT id, product_name FROM items "
                        "WHERE product_name IS NOT NULL").fetchall()
    n = 0
    for r in rows:
        conn.execute("UPDATE items SET category = ? WHERE id = ?",
                     (categorize(r["product_name"]), r["id"]))
        n += 1
    conn.commit()
    return n


# ------------------------------------------------------------ platform stats
def _youtube_video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{6,})", url or "")
    return m.group(1) if m else None


def sync_platform_stats(conn, settings) -> dict:
    """Pull views/likes for posted videos. Honest statuses, no fake data.

    Returns {platform: {status, updated, detail}} where status is one of
    ok / not_configured / not_connected / error."""
    out: dict = {}
    posted = conn.execute(
        "SELECT item_id, platform, remote_url FROM posts "
        "WHERE status = 'posted' AND remote_url IS NOT NULL").fetchall()
    by_platform: dict[str, list] = {}
    for p in posted:
        by_platform.setdefault(p["platform"], []).append(p)

    # YouTube: Data API v3, needs YOUTUBE_API_KEY (read-only key is enough
    # for public videos; the uploader's own Shorts are public by default).
    yt = by_platform.get("youtube", [])
    if not getattr(settings, "youtube_api_key", ""):
        out["youtube"] = {"status": "not_configured", "updated": 0,
                          "detail": "YOUTUBE_API_KEY belum diisi di .env"}
    elif not yt:
        out["youtube"] = {"status": "ok", "updated": 0,
                          "detail": "belum ada video YouTube yang terposting"}
    else:
        try:
            import httpx
            ids = [v for v in (_youtube_video_id(p["remote_url"])
                               for p in yt) if v]
            updated = 0
            for i in range(0, len(ids), 50):
                chunk = ids[i:i + 50]
                r = httpx.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={"part": "statistics", "id": ",".join(chunk),
                            "key": settings.youtube_api_key},
                    timeout=30)
                r.raise_for_status()
                for it in r.json().get("items", []):
                    st = it.get("statistics", {})
                    pid = next((p for p in yt
                                if _youtube_video_id(p["remote_url"])
                                == it["id"]), None)
                    if not pid:
                        continue
                    conn.execute(
                        "INSERT INTO platform_stats (item_id, platform, "
                        "post_id, post_url, views, likes, comments, "
                        "fetched_at) VALUES (?, 'youtube', ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(item_id, platform) DO UPDATE SET "
                        "views=excluded.views, likes=excluded.likes, "
                        "comments=excluded.comments, fetched_at=excluded.fetched_at",
                        (pid["item_id"], it["id"], pid["remote_url"],
                         int(st.get("viewCount", 0)),
                         int(st.get("likeCount", 0)),
                         int(st.get("commentCount", 0)),
                         datetime.now(timezone.utc).isoformat()))
                    updated += 1
            conn.commit()
            out["youtube"] = {"status": "ok", "updated": updated, "detail": ""}
        except Exception as e:  # noqa: BLE001 - surfaced, not hidden
            out["youtube"] = {"status": "error", "updated": 0, "detail": str(e)}

    # Facebook + Threads: no posting accounts connected yet (feature #1
    # stubs), so there is nothing real to pull — say so explicitly.
    for platform, why in (
            ("facebook", "belum ada token Page (butuh fitur posting #1)"),
            ("threads", "belum ada token Threads (butuh fitur posting #1)")):
        rows = by_platform.get(platform, [])
        out[platform] = {
            "status": "not_connected" if not rows else "error",
            "updated": 0,
            "detail": why if not rows else
            "postingan ada tapi fetcher belum diimplementasikan",
        }
    return out
