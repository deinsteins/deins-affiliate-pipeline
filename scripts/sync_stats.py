"""Pull platform views/likes into platform_stats + refresh categories.

Usage: python -m scripts.sync_stats
Honest by design: platforms without accounts/keys report
not_configured / not_connected instead of zeros. Run it on a timer
once posting (feature #1) is live; until then it mostly refreshes
categories, which is still useful after renames.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import analytics as an  # noqa: E402
from src import db as dbmod  # noqa: E402
from src.config import Settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    conn = dbmod.connect(ROOT / "storage" / "pipeline.db")
    n = an.backfill_categories(conn)
    print(f"kategori diperbarui: {n} item")
    for platform, res in an.sync_platform_stats(conn, Settings()).items():
        print(f"{platform}: {res['status']} (updated {res['updated']})"
              + (f" — {res['detail']}" if res["detail"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
