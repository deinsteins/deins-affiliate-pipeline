"""Backfill owner's affiliate links for packaged items that lack one.

Usage:
  python -m scripts.backfill_affiliate [--limit N] [--dry-run] [--api|--anredir]
Resumable: items that already have affiliate_url are skipped.
Rate-limited (~0.5s between API calls) to stay polite.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import db as dbmod  # noqa: E402
from src.config import Settings  # noqa: E402
from src.packager import set_affiliate_link  # noqa: E402
from src.shopee_affiliate import (ShopeeAffiliateClient, build_an_redir,  # noqa: E402
                                  platform_sub_ids)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "storage" / "pipeline.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--api", action="store_true")
    ap.add_argument("--anredir", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="tulis ulang link yang sudah ada")
    args = ap.parse_args()
    settings = Settings()
    use_api = args.api or (not args.anredir and
                           settings.shopee_affiliate_app_id and
                           settings.shopee_affiliate_secret)
    client = None
    if use_api:
        if not (settings.shopee_affiliate_app_id and
                settings.shopee_affiliate_secret):
            print("butuh SHOPEE_AFFILIATE_APP_ID + SECRET untuk mode API")
            return 2
        client = ShopeeAffiliateClient(settings.shopee_affiliate_app_id,
                                       settings.shopee_affiliate_secret)
    elif not settings.shopee_affiliate_id:
        print("butuh SHOPEE_AFFILIATE_ID untuk mode an_redir")
        return 2
    conn = dbmod.connect(DB)
    q = ("SELECT * FROM items WHERE status = 'packaged' "
         "ORDER BY id" if args.force else
         "SELECT * FROM items WHERE status = 'packaged' AND "
         "(affiliate_url IS NULL OR affiliate_url = '') ORDER BY id")
    rows = conn.execute(q).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f"{len(rows)} paket tanpa link afiliasi "
          f"(mode: {'api' if use_api else 'an_redir'})")
    ok = fail = 0
    for it in rows:
        try:
            if use_api:
                url, source = client.generate_link(
                    it["product_url"], it["shop_id"], it["item_id"],
                    [settings.shopee_affiliate_sub_id])
            else:
                url = build_an_redir(
                    it["product_url"], settings.shopee_affiliate_id,
                    settings.shopee_affiliate_sub_id)
                source = "an_redir"
            if args.dry_run:
                print(f"  #{it['id']} -> {source}: {url[:100]}")
            else:
                set_affiliate_link(conn, it["id"], url, source)
                print(f"  #{it['id']} OK ({source})")
            ok += 1
        except Exception as e:
            print(f"  #{it['id']} GAGAL: {type(e).__name__}: {str(e)[:120]}")
            fail += 1
        if use_api:
            time.sleep(0.5)
    print(f"selesai: {ok} ok, {fail} gagal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
