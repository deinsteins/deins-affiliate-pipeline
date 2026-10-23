"""Caption + package worker: one pass over all 'downloaded' items.
Run: python -m src.worker   (safe to re-run; packaged items are skipped)
"""
import asyncio

from . import db as dbmod
from .caption_ai import generate_captions
from .config import Settings, load_channels
from .packager import build_package

DB = "storage/pipeline.db"


async def run_once() -> None:
    settings = Settings()
    cfg = load_channels()
    style_cfg = cfg.get("captions", {})
    conn = dbmod.connect(DB)
    items = dbmod.items_by_status(conn, "downloaded")
    print(f"[worker] {len(items)} item menunggu caption", flush=True)
    for item in items:
        try:
            captions = await generate_captions(
                settings, item["product_name"], item["source_text"],
                item["product_url"], style_cfg)
            pkg = build_package(conn, item, captions)
            print(f"[worker] item#{item['id']} -> {pkg.name}", flush=True)
        except Exception as e:
            print(f"[worker] item#{item['id']} GAGAL: {type(e).__name__}: "
                  f"{str(e)[:120]}", flush=True)
    print("[worker] selesai", flush=True)


if __name__ == "__main__":
    asyncio.run(run_once())
