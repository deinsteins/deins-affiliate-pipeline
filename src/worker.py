"""Caption + package worker: one pass over all 'downloaded' items.
Run: python -m src.worker   (safe to re-run; packaged items are skipped)
"""
import asyncio

from . import db as dbmod
from .caption_ai import generate_captions
from .config import Settings, load_channels
from .health import now_ts, write_health
from .packager import build_package, set_affiliate_link
from .shopee_affiliate import (ShopeeAffiliateClient, build_an_redir,
                               platform_sub_ids)

DB = "storage/pipeline.db"


async def run_once() -> None:
    write_health(worker_last_start=now_ts())
    settings = Settings()
    cfg = load_channels()
    style_cfg = cfg.get("captions", {})
    conn = dbmod.connect(DB)
    items = dbmod.items_by_status(conn, "downloaded")
    print(f"[worker] {len(items)} item menunggu caption", flush=True)
    sem = asyncio.Semaphore(5)

    async def attach_affiliate(item):
        """Best-effort: a package must never fail because link gen did."""
        try:
            if settings.shopee_affiliate_app_id and \
                    settings.shopee_affiliate_secret:
                client = ShopeeAffiliateClient(
                    settings.shopee_affiliate_app_id,
                    settings.shopee_affiliate_secret)
                url, source = await asyncio.to_thread(
                    client.generate_link, item["product_url"],
                    item["shop_id"], item["item_id"],
                    [settings.shopee_affiliate_sub_id])
            elif settings.shopee_affiliate_id:
                url = build_an_redir(
                    item["product_url"], settings.shopee_affiliate_id,
                    settings.shopee_affiliate_sub_id)
                source = "an_redir"
            else:
                return  # belum dikonfigurasi: lewati diam-diam
            set_affiliate_link(conn, item["id"], url, source)
            print(f"[worker] item#{item['id']} link afiliasi: {source}",
                  flush=True)
        except Exception as e:
            print(f"[worker] item#{item['id']} link afiliasi GAGAL: "
                  f"{type(e).__name__}: {str(e)[:120]}", flush=True)

    counts = {"ok": 0, "fail": 0, "last_error": ""}

    async def process(item):
        async with sem:
            try:
                captions = await generate_captions(
                    settings, item["product_name"], item["source_text"],
                    item["product_url"], style_cfg)
                pkg = build_package(conn, item, captions)
                print(f"[worker] item#{item['id']} -> {pkg.name}", flush=True)
                await attach_affiliate(item)
                counts["ok"] += 1
            except Exception as e:
                counts["fail"] += 1
                counts["last_error"] = f"{type(e).__name__}: {str(e)[:120]}"
                print(f"[worker] item#{item['id']} GAGAL: "
                      f"{counts['last_error']}", flush=True)

    await asyncio.gather(*(process(it) for it in items))
    write_health(worker_last_finish=now_ts(), worker_last_ok=counts["ok"],
                 worker_last_failed=counts["fail"],
                 worker_last_error=counts["last_error"])
    print("[worker] selesai", flush=True)


if __name__ == "__main__":
    asyncio.run(run_once())
