"""Test + manual YouTube upload for one packaged item.

  python -m scripts.post_youtube --dry-run [--item ID]
      Show exactly what WOULD be uploaded (title, description with the
      shortlink swapped in, tags, privacy) without calling YouTube.
  python -m scripts.post_youtube --item ID [--privacy private|public]
      Real upload. Default privacy is private — inspect the video on
      YouTube before anything goes public. Updates posts(youtube).

Production rule (enforced by the scheduler, not here): only items
with review='approved' may be auto-posted. --force bypasses that gate
for a manual test upload only — say so out loud when you use it.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import analytics as an  # noqa: E402
from src import db as dbmod  # noqa: E402
from src.config import Settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "storage" / "pipeline.db"
READY = ROOT / "storage" / "ready"


def pick_item(conn, item_id: int | None, force: bool):
    if item_id is not None:
        row = conn.execute("SELECT * FROM items WHERE id = ?",
                           (item_id,)).fetchone()
        if not row:
            raise SystemExit(f"item {item_id} tidak ada")
        if row["status"] != "packaged":
            raise SystemExit(f"item {item_id} belum packaged "
                             f"(status: {row['status']})")
        if row["review"] != "approved" and not force:
            raise SystemExit(
                f"item {item_id} belum approved (review: {row['review']}) — "
                "approve dulu di dashboard, atau pakai --force untuk tes")
        return row
    q = ("SELECT * FROM items WHERE status = 'packaged' "
         + ("" if force else "AND review = 'approved' ")
         + "ORDER BY id LIMIT 1")
    row = conn.execute(q).fetchone()
    if not row:
        raise SystemExit("tidak ada item packaged"
                         + ("" if force else " yang approved"))
    return row


def load_caption(item) -> tuple[Path, dict]:
    pkg = sorted(READY.glob(f"{item['id']}-*/"))
    if not pkg:
        raise SystemExit(f"paket item {item['id']} tidak ada di storage/ready")
    caps_file = pkg[0] / "captions.json"
    if not caps_file.exists():
        raise SystemExit(f"captions.json tidak ada untuk item {item['id']}")
    caps = json.loads(caps_file.read_text())
    return pkg[0], caps.get("youtube", {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", type=int, default=None)
    ap.add_argument("--force", action="store_true",
                    help="lewati gerbang approved (tes manual saja)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--privacy", default="private",
                    choices=["private", "public", "unlisted"])
    args = ap.parse_args()
    settings = Settings()
    conn = dbmod.connect(DB)
    item = pick_item(conn, args.item, args.force)
    pkg, caption = load_caption(item)
    shortlink = an.shortlink(item["id"], settings.public_base_url)
    from src.publishers.youtube import build_body
    body = build_body(caption, shortlink, args.privacy)
    print(f"item #{item['id']}: {item['product_name'] or '(tanpa nama)'}")
    print(f"video: {pkg / 'video.mp4'}")
    print(f"shortlink: {shortlink}")
    print(f"judul ({len(body['snippet']['title'])} karakter): "
          f"{body['snippet']['title']}")
    print(f"privacy: {args.privacy}")
    print(f"tags: {', '.join(body['snippet']['tags'])}")
    print("--- deskripsi (link sudah diganti shortlink) ---")
    print(body["snippet"]["description"][:800])
    if args.dry_run:
        print("\n[DRY RUN] tidak ada yang di-upload.")
        return 0
    from src.publishers.youtube import upload_short
    try:
        url = upload_short(pkg, caption, shortlink, args.privacy)
    except Exception as e:  # noqa: BLE001 - recorded, not hidden
        conn.execute(
            "INSERT INTO posts (item_id, platform, status, error, attempts) "
            "VALUES (?, 'youtube', 'failed', ?, 1) "
            "ON CONFLICT(item_id, platform) DO UPDATE SET status='failed', "
            "error=excluded.error, attempts=attempts+1",
            (item["id"], str(e)))
        conn.commit()
        print(f"GAGAL: {e}")
        return 1
    conn.execute(
        "INSERT INTO posts (item_id, platform, status, remote_url, attempts) "
        "VALUES (?, 'youtube', 'posted', ?, 1) "
        "ON CONFLICT(item_id, platform) DO UPDATE SET status='posted', "
        "remote_url=excluded.remote_url, error=NULL",
        (item["id"], url))
    conn.commit()
    print(f"\nTERPOSTING: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
