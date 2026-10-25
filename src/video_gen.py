"""AI video generation: best-product discovery -> script -> Veo clips
-> one package -> approval queue.

Flow (mirrors the user's requested flow):
  1. DISCOVERY — "produk terbaik" = existing items ranked by shortlink
     clicks (analytics), plus any product added manually by URL.
     Ranking by clicks is honest: it measures what viewers actually
     tap, not what a channel happened to post.
  2. JOB — dashboard creates a video_jobs row (status pending).
  3. SCRIPT — the router LLM writes a 4-scene storyboard as JSON:
     hook (scene 1), demo + benefits (scenes 2-3), CTA (scene 4).
     Each scene: visual_prompt (for Veo, English works best),
     narration (Indonesian, spoken in the video's caption text),
     onscreen_text (short overlay text).
  4. VIDEO — one Veo 8s clip per scene, stitched with ffmpeg into a
     single vertical video. (Veo = Flow's engine; see veo_backend.py
     for why the Flow web app itself is not automated.)
  5. PACKAGE — the finished video is packed exactly like a channel
     package: storage/ready/<id>-<slug>/video.mp4 + captions.json +
     links.txt, with an items row (channel='ai_generated',
     status='packaged', review='pending') and the owner's affiliate
     link when shop/item ids are known.
  6. QUEUE — the package shows up in the normal dashboard review
     queue, ready for approve/reject like any other item.

States: pending -> scripting -> generating -> assembling ->
packaging -> done | failed (error text stored on the job).
A failed job keeps its script (if any) so a retry doesn't pay for
script generation twice — it resumes from the failed step.
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path

from . import analytics as an
from .shopee_affiliate import build_an_redir

ROOT = Path(__file__).resolve().parent.parent
READY = ROOT / "storage" / "ready"

SCRIPT_SYSTEM = (
    "Kamu penulis naskah video produk Shorts/Reels berbahasa Indonesia. "
    "Tulis naskah yang menjual tanpa lebay: hook kuat di 3 detik pertama, "
    "satu manfaat konkret per scene, tanpa klaim berlebihan (tanpa kata "
    "'terbaik', 'nomor 1', 'dijamin', 'viral' kecuali benar-benar umum). "
    "Balas HANYA JSON valid dengan bentuk: {\"hook\": \"...\", \"scenes\": "
    "[{\"visual_prompt\": \"...\", \"narration\": \"...\", \"onscreen_text\": \"...\"}], "
    "\"cta\": \"...\"}. visual_prompt dalam Bahasa Inggris (untuk model video), "
    "narration dan onscreen_text dalam Bahasa Indonesia. Tepat 4 scenes."
)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "produk").lower()).strip("-")
    return slug[:60] or "produk"


async def generate_script(settings, product_name: str,
                          category: str | None) -> dict:
    """Ask the router LLM for a 4-scene storyboard (JSON)."""
    if not settings.router_base_url or not settings.router_api_key:
        raise RuntimeError("router belum dikonfigurasi — script AI "
                           "menunggu router (9Router) kembali.")
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=settings.router_base_url,
                         api_key=settings.router_api_key)
    prompt = (f"Produk: {product_name}\n"
              f"Kategori: {category or 'umum'}\n"
              "Buat naskah video produk vertikal ~30 detik (4 scenes).")
    try:
        resp = await client.chat.completions.create(
            model=settings.router_model,
            messages=[{"role": "system", "content": SCRIPT_SYSTEM},
                      {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7, max_tokens=1500)
    except Exception as e:  # noqa: BLE001 - router down must read clearly
        raise RuntimeError(
            "router tidak terjangkau (9Router down?) — script AI gagal, "
            f"job bisa di-retry nanti: {e}") from e
    raw = resp.choices[0].message.content or "{}"
    try:
        script = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"script AI bukan JSON valid: {e}") from e
    scenes = script.get("scenes") or []
    if len(scenes) != 4 or not all(
            s.get("visual_prompt") and s.get("narration") for s in scenes):
        raise RuntimeError("script AI tidak lengkap (butuh 4 scenes dengan "
                           "visual_prompt + narration) — coba lagi.")
    return script


def assemble_video(clip_paths: list[Path], out_path: Path) -> Path:
    """Stitch scene clips into one vertical video (ffmpeg concat)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                     delete=False) as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")
        list_file = f.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-movflags", "+faststart", str(out_path)],
            check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg stitch gagal: {e.stderr[-500:]}") from e
    finally:
        Path(list_file).unlink(missing_ok=True)
    return out_path


def _set_status(conn, job_id: int, status: str, **extra) -> None:
    conn.execute("UPDATE video_jobs SET status = ?, updated_at = "
                 "CURRENT_TIMESTAMP WHERE id = ?",
                 (status, job_id))
    for k, v in extra.items():
        conn.execute(f"UPDATE video_jobs SET {k} = ? WHERE id = ?",
                     (v, job_id))
    conn.commit()


def package_video(conn, settings, job: dict, video_path: Path,
                  script: dict) -> int:
    """Create the items row + package dir so the video enters review."""
    slug = slugify(job["product_name"])
    cur = conn.execute(
        "INSERT INTO items (channel, product_url, product_name, region, "
        "shop_id, item_id, slug, status, review, category) "
        "VALUES ('ai_generated', ?, ?, 'ID', ?, ?, ?, 'packaged', "
        "'pending', ?) RETURNING id",
        (job["product_url"], job["product_name"], job["shop_id"],
         job["item_id"], slug, job["category"]))
    item_id = cur.fetchone()[0]
    pkg = READY / f"{item_id}-{slug}"
    pkg.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copyfile(video_path, pkg / "video.mp4")
    narration = " ".join(s.get("narration", "") for s in script["scenes"])
    captions = {
        "youtube": {
            "title": script.get("hook", job["product_name"])[:100],
            "description": f"{narration}\n\nLink produk: "
                           f"{job['product_url']}",
            "tags": [job["category"] or "produk", "racun shopee",
                     "shopee haul"],
        },
        "threads": {"text": f"{script.get('hook', '')} {narration} "
                            f"{script.get('cta', '')}".strip()},
        "facebook": {"text": f"{script.get('hook', '')} {narration} "
                             f"{script.get('cta', '')}".strip()},
        "shopee": {"text": f"{script.get('hook', '')} {narration}".strip()},
    }
    (pkg / "captions.json").write_text(
        json.dumps(captions, ensure_ascii=False, indent=2))
    affiliate_url = ""
    if job["shop_id"] and job["item_id"] and settings.shopee_affiliate_id:
        affiliate_url = build_an_redir(
            job["product_url"], settings.shopee_affiliate_id,
            settings.shopee_affiliate_sub_id)
        conn.execute("UPDATE items SET affiliate_url = ?, "
                     "affiliate_source = 'an_redir' WHERE id = ?",
                     (affiliate_url, item_id))
    (pkg / "links.txt").write_text(
        f"product_url: {job['product_url']}\n"
        f"product_name: {job['product_name']}\n"
        f"affiliate_url: {affiliate_url}\n"
        f"source: ai_video_job_{job['id']}\n")
    conn.commit()
    return item_id


def run_job(conn, settings, job_id: int) -> dict:
    """Run one job through its state machine. Returns the final job row."""
    from .veo_backend import generate_clip, VeoError
    job = dict(conn.execute("SELECT * FROM video_jobs WHERE id = ?",
                            (job_id,)).fetchone() or {})
    if not job:
        raise ValueError(f"job {job_id} tidak ada")
    try:
        # 1. script (skip if a previous attempt already produced one)
        if job.get("script_json"):
            script = json.loads(job["script_json"])
        else:
            _set_status(conn, job_id, "scripting")
            import asyncio
            script = asyncio.run(generate_script(
                settings, job["product_name"], job["category"]))
            _set_status(conn, job_id, "scripting",
                        script_json=json.dumps(script, ensure_ascii=False))
        # 2. clips (one per scene; resume skips scenes already on disk)
        _set_status(conn, job_id, "generating")
        workdir = ROOT / "storage" / "video_jobs" / str(job_id)
        workdir.mkdir(parents=True, exist_ok=True)
        clips = []
        for i, scene in enumerate(script["scenes"]):
            clip = workdir / f"scene{i}.mp4"
            if not clip.exists() or clip.stat().st_size == 0:
                prompt = (scene["visual_prompt"]
                          + ". Vertical 9:16 product video, bright, "
                            "clean, realistic, no text overlays.")
                generate_clip(settings.gemini_api_key, prompt, clip,
                              model=settings.veo_model)
            clips.append(clip)
        # 3. assemble
        _set_status(conn, job_id, "assembling")
        final = workdir / "final.mp4"
        assemble_video(clips, final)
        # 4. package into the review queue
        _set_status(conn, job_id, "packaging")
        item_id = package_video(conn, settings, job, final, script)
        _set_status(conn, job_id, "done", package_item_id=item_id)
    except (RuntimeError, VeoError, Exception) as e:  # noqa: BLE001
        _set_status(conn, job_id, "failed", error=str(e)[:500])
    return dict(conn.execute("SELECT * FROM video_jobs WHERE id = ?",
                             (job_id,)).fetchone())


def top_products(conn, limit: int = 10) -> list[dict]:
    """Best products by shortlink clicks (analytics) for discovery."""
    clicks = an.click_counts(conn)
    rows = conn.execute(
        "SELECT id, product_name, product_url, shop_id, item_id, category "
        "FROM items WHERE product_name IS NOT NULL").fetchall()
    ranked = sorted(
        ({"item_id": r["id"], "name": r["product_name"],
          "product_url": r["product_url"], "shop_id": r["shop_id"],
          "item_id_shop": r["item_id"], "category": r["category"],
          "clicks": clicks.get(r["id"], 0)} for r in rows),
        key=lambda d: -d["clicks"])
    return ranked[:limit]
