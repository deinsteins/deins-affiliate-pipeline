"""Telethon ingest: backfill recent channel history once, then listen
for new posts. Each video post becomes one item in SQLite:
download -> sha256 dedupe -> extract + resolve the Shopee product link.

Runs through the sandbox egress proxy (see config.proxy_from_env).
"""
import re
from pathlib import Path

import httpx
from telethon import events

from . import db as dbmod
from .health import now_ts, write_health
from .config import Settings, load_channels, make_client
from .link_tools import extract_shopee_urls, resolve_product_url

ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = ROOT / "storage" / "downloads"
BACKFILL_PER_CHANNEL = 15


def slugify(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:60] or fallback


async def ingest_message(conn, http: httpx.AsyncClient, channel: str,
                         msg, region_hint: str | None) -> str:
    """Process one message; return what happened (for logging)."""
    if not msg.video:
        return "skip:no-video"
    seen = conn.execute("SELECT id FROM items WHERE channel = ? AND "
                        "message_id = ?", (channel, msg.id)).fetchone()
    if seen:
        return "skip:already-ingested"
    urls = extract_shopee_urls(msg.raw_text or "")
    if not urls:
        return "skip:no-link"
    tmp = DOWNLOADS / f".tmp-{channel}-{msg.id}.mp4"
    await msg.download_media(file=str(tmp))
    try:
        fhash = dbmod.file_sha256(tmp)
        existing = conn.execute("SELECT id FROM items WHERE file_hash = ?",
                                (fhash,)).fetchone()
        if existing:
            tmp.unlink(missing_ok=True)
            return "skip:duplicate"
        info = await resolve_product_url(urls[0], http)
        if info is None:
            tmp.unlink(missing_ok=True)
            return "skip:link-unresolved"
        final = DOWNLOADS / f"{fhash[:12]}.mp4"
        tmp.rename(final)
        slug = slugify(info.get("product_name"), f"item-{fhash[:8]}")
        item_id = dbmod.insert_item(
            conn, channel=channel, message_id=msg.id, file_hash=fhash,
            video_path=str(final.relative_to(ROOT)),
            source_text=(msg.raw_text or "")[:2000],
            product_url=info["product_url"],
            product_name=info.get("product_name"),
            region=info.get("region") or region_hint,
            shop_id=info.get("shop_id"), item_id=info.get("item_id"),
            slug=slug, status="downloaded")
        if item_id:
            write_health(ingest_last_item_at=now_ts())
        return f"item#{item_id} {slug}" if item_id else "skip:duplicate"
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


async def backfill(client, conn, http, cfg) -> None:
    for c in cfg["channels"]:
        if not c.get("enabled"):
            continue
        uname = c["username"]
        ent = await client.get_entity(uname)
        got, scanned = 0, 0
        async for msg in client.iter_messages(ent, limit=200):
            if got >= BACKFILL_PER_CHANNEL or scanned >= 200:
                break
            scanned += 1
            if not msg.video:
                continue
            result = await ingest_message(conn, http, uname, msg,
                                          c.get("link_region"))
            print(f"[backfill:{uname}] msg {msg.id}: {result}", flush=True)
            if result.startswith("item#"):
                got += 1
        print(f"[backfill:{uname}] selesai: {got} item baru", flush=True)


async def run_ingest(settings: Settings, db_path: str) -> None:
    cfg = load_channels()
    conn = dbmod.connect(db_path)
    client = make_client(settings)
    await client.start()
    write_health(ingest_started_at=now_ts())
    print("[ingest] Telegram tersambung", flush=True)
    async with httpx.AsyncClient(trust_env=True) as http:
        await backfill(client, conn, http, cfg)
        channels = [c["username"] for c in cfg["channels"] if c.get("enabled")]

        @client.on(events.NewMessage(chats=channels))
        async def on_message(event):
            ch = getattr(event.chat, "username", None) or "?"
            result = await ingest_message(conn, http, ch, event.message, None)
            print(f"[live:{ch}] msg {event.message.id}: {result}", flush=True)

        print("[ingest] listener aktif untuk:", ", ".join(channels), flush=True)
        await client.run_until_disconnected()
