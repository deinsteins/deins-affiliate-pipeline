"""Worklist generator + report applier for product-name resolution.

Worklist (for the logged-in browser session task):
  python -m scripts.resolve_names worklist --region ID --limit 15
  -> prints one block per item: item id, shop/item ids, the in-session
     API URL, and the fallback product page URL.

Apply (a JSON report {item_id: name} from the browser task):
  python -m scripts.resolve_names apply --from report.json --source browser
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import db as dbmod  # noqa: E402
from src.name_resolver import apply_names  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "storage" / "pipeline.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worklist")
    w.add_argument("--region", default="ID")
    w.add_argument("--limit", type=int, default=15)
    w.add_argument("--exclude", default="",
                   help="comma-separated item ids to skip (e.g. captcha hits)")
    a = sub.add_parser("apply")
    a.add_argument("--from", dest="report", required=True)
    a.add_argument("--source", default="browser")
    args = ap.parse_args()
    conn = dbmod.connect(DB)
    if args.cmd == "worklist":
        excl = [int(x) for x in args.exclude.split(",") if x.strip()]
        rows = conn.execute(
            "SELECT id, shop_id, item_id FROM items "
            "WHERE product_name IS NULL AND region = ? "
            "AND shop_id IS NOT NULL ORDER BY id",
            (args.region,)).fetchall()
        rows = [r for r in rows if r["id"] not in excl][:args.limit]
        print(f"{len(rows)} item tanpa nama (region {args.region}):")
        for r in rows:
            print(f"\nITEM {r['id']} (shop {r['shop_id']}, item {r['item_id']}):")
            print(f"  api: https://shopee.co.id/api/v4/item/get"
                  f"?itemid={r['item_id']}&shopid={r['shop_id']}")
            print(f"  page: https://shopee.co.id/product/"
                  f"{r['shop_id']}/{r['item_id']}")
        return 0
    report = {int(k): v for k, v in
              json.loads(Path(args.report).read_text()).items()}
    applied, skipped = apply_names(conn, report, args.source)
    print(f"nama diterapkan: {applied}, dilewati: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
