"""Build a ready-to-post package per item:
storage/ready/<slug>/
  video.mp4      -- the downloaded product video
  captions.json  -- per-platform captions from caption_ai
  links.txt      -- canonical product URL (+ affiliate link slot)
The Shopee Video package is consumed manually by the owner in-app;
the other platforms are consumed by the publishers.
"""
import json, shutil
from pathlib import Path


def build_package(item: dict, captions: dict, root: Path) -> Path:
    pkg = root / "storage" / "ready" / item["slug"]
    pkg.mkdir(parents=True, exist_ok=True)
    shutil.copy(item["video_path"], pkg / "video.mp4")
    (pkg / "captions.json").write_text(json.dumps(captions, ensure_ascii=False, indent=2))
    (pkg / "links.txt").write_text(
        f"product_url: {item['product_url']}\naffiliate_url: \n")
    return pkg
