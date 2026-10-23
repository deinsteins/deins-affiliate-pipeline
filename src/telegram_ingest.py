"""Telethon listener: watch configured channels, download new product
videos (+ the source post text, which carries the Shopee product link).

Requires a user session (scripts/telegram_login.py) — the Bot API cannot
read arbitrary channels. Egress goes through the sandbox HTTP proxy.
"""
from telethon import TelegramClient, events

from .config import Settings, load_channels
from .db import connect, file_sha256


async def run_ingest(settings: Settings, db_path: str) -> None:
    cfg = load_channels()
    channels = [c["username"] for c in cfg["channels"] if c.get("enabled")]
    client = TelegramClient(settings.telegram_session,
                            settings.telegram_api_id,
                            settings.telegram_api_hash)
    # TODO: pass proxy= from HTTPS Proxy env (Telethon HTTP proxy support)

    @client.on(events.NewMessage(chats=channels))
    async def on_message(event):  # noqa: ANN001
        if not (event.video or (event.document and event.file.mime_type == "video/mp4")):
            return
        # TODO: download to storage/downloads/, sha256 dedupe via db,
        # insert item(status='downloaded', source_text=event.raw_text)
        ...

    await client.start()
    await client.run_until_disconnected()
