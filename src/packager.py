"""Build a ready-to-post package per item:
storage/ready/<slug>/
  video.mp4 · captions.json · links.txt
Also seeds db.posts rows: youtube/facebook/threads = pending,
shopee = manual (no official upload API; owner posts in-app).
"""
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = ("youtube", "facebook", "threads", "shopee")


def build_package(conn, item, captions: dict) -> Path:
    pkg = ROOT / "storage" / "ready" / f"{item['id']}-{item['slug']}"
    pkg.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / item["video_path"], pkg / "video.mp4")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:  # poster frame for the dashboard (best effort)
        try:
            subprocess.run([ffmpeg, "-v", "error", "-ss", "1", "-i",
                            str(pkg / "video.mp4"), "-frames:v", "1",
                            "-vf", "scale=384:-2", str(pkg / "thumb.jpg"),
                            "-y"], timeout=30, check=False)
        except Exception:
            pass
    (pkg / "captions.json").write_text(
        json.dumps(captions, ensure_ascii=False, indent=2))
    (pkg / "links.txt").write_text(
        f"product_url: {item['product_url']}\n"
        f"product_name: {item['product_name'] or '(belum diketahui - item MY)'}\n"
        f"region: {item['region']}\naffiliate_url: \n")
    for platform in PLATFORMS:
        status = "manual" if platform == "shopee" else "pending"
        conn.execute(
            "INSERT OR IGNORE INTO posts (item_id, platform, status) "
            "VALUES (?, ?, ?)", (item["id"], platform, status))
    conn.execute("UPDATE items SET status = 'packaged' WHERE id = ?",
                 (item["id"],))
    conn.commit()
    return pkg
