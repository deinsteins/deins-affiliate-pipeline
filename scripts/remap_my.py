"""Malaysia -> Indonesia link remap.

Two steps, kept separate because the browser session does the searching:
1. worklist: MY items that HAVE a name but still point at Shopee MY
   -> prints Shopee ID search URLs for the browser task to harvest
      (title + product_url + shop/item of the top results).
2. apply: a JSON report {item_id: [{title, product_url, shop_id,
   item_id}]} -> picks the best title match per item (>=0.45 similarity)
   and swaps product_url to the ID product. If the item already has an
   an_redir affiliate link, it is rebuilt from the new URL so commissions
   keep flowing to the owner.

Usage:
  python -m scripts.remap_my worklist --limit 15
  python -m scripts.remap_my apply --from my-search-report.json [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import db as dbmod  # noqa: E402
from src.name_resolver import pick_best_match  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "storage" / "pipeline.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worklist")
    w.add_argument("--limit", type=int, default=15)
    a = sub.add_parser("apply")
    a.add_argument("--from", dest="report", required=True)
    a.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conn = dbmod.connect(DB)
    if args.cmd == "worklist":
        rows = conn.execute(
            "SELECT id, product_name FROM items WHERE region = 'MY' "
            "AND product_name IS NOT NULL AND product_url LIKE '%shopee.com.my%' "
            "ORDER BY id LIMIT ?", (args.limit,)).fetchall()
        print(f"{len(rows)} item MY bernama yang masih ber-link MY:")
        for r in rows:
            print(f"\nITEM {r['id']}: {r['product_name']}")
            print(f"  search: https://shopee.co.id/search?keyword="
                  f"{quote(r['product_name'])}")
        return 0
    report = json.loads(Path(args.report).read_text())
    from src.config import Settings  # noqa: E402
    from src.packager import set_affiliate_link  # noqa: E402
    from src.shopee_affiliate import build_an_redir  # noqa: E402
    settings = Settings()
    swapped, skipped = 0, []
    for item_id_s, candidates in report.items():
        item_id = int(item_id_s)
        row = conn.execute("SELECT product_name, affiliate_source FROM items "
                           "WHERE id = ?", (item_id,)).fetchone()
        if not row or not row["product_name"]:
            skipped.append(item_id)
            continue
        best = pick_best_match(row["product_name"], candidates)
        if not best:
            skipped.append(item_id)
            continue
        print(f"#{item_id}: {row['product_name'][:50]} -> "
              f"{best['title'][:50]}")
        if not args.dry_run:
            conn.execute("UPDATE items SET product_url = ?, region = 'ID' "
                         "WHERE id = ?", (best["product_url"], item_id))
            conn.commit()
            if settings.shopee_affiliate_id:
                set_affiliate_link(
                    conn, item_id,
                    build_an_redir(best["product_url"],
                                   settings.shopee_affiliate_id,
                                   settings.shopee_affiliate_sub_id),
                    "an_redir")
            swapped += 1
    print(f"remap: {swapped} ditukar, {skipped} dilewati")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
