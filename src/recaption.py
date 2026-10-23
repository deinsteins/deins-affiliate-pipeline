"""Rewrite captions for ALL packaged items with the current prompt.
Run: python -m src.recapton  ->  python -m src.recaption
Safe: only captions.json inside each package is replaced.
"""
import asyncio
import json
import sqlite3
from pathlib import Path

from .caption_ai import generate_captions
from .config import Settings, load_channels

ROOT = Path(__file__).resolve().parent.parent
DB = "storage/pipeline.db"


async def run() -> None:
    settings = Settings()
    cfg = load_channels()
    style_cfg = cfg.get("captions", {})
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    items = conn.execute(
        "SELECT * FROM items WHERE status = 'packaged' ORDER BY id").fetchall()
    print(f"[recaption] {len(items)} paket ditulis ulang", flush=True)
    sem = asyncio.Semaphore(5)

    async def one(item):
        async with sem:
            pkg = next((ROOT / "storage" / "ready").glob(f"{item['id']}-*/"), None)
            if pkg is None:
                print(f"[recaption] item#{item['id']}: paket tidak ketemu", flush=True)
                return
            try:
                caps = await generate_captions(
                    settings, item["product_name"], item["source_text"],
                    item["product_url"], style_cfg)
                (pkg / "captions.json").write_text(
                    json.dumps(caps, ensure_ascii=False, indent=2))
                print(f"[recaption] item#{item['id']} OK", flush=True)
            except Exception as e:
                print(f"[recaption] item#{item['id']} GAGAL: "
                      f"{type(e).__name__}: {str(e)[:100]}", flush=True)

    await asyncio.gather(*(one(it) for it in items))
    print("[recaption] selesai", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
