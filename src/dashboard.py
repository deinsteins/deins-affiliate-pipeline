"""Web dashboard for the affiliate pipeline: monitor + review queue.

Run: uvicorn src.dashboard:app --port 8600
Features: stats, filterable item grid with inline video, per-platform
captions, and approve/reject review (items.review). Publishers will
only post items whose review = 'approved'.
Basic-auth protected (DASHBOARD_USER / DASHBOARD_PASSWORD in .env).
"""
import json
import secrets
import sqlite3
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import analytics as an
from . import db as dbmod
from .config import Settings

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "storage" / "pipeline.db"
READY = ROOT / "storage" / "ready"

settings = Settings()
app = FastAPI(title="Deins Affiliate Pipeline")
security = HTTPBasic()


def auth(creds: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(creds.username, settings.dashboard_user)
    ok_pass = secrets.compare_digest(creds.password, settings.dashboard_password)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="Login dulu ya",
                            headers={"WWW-Authenticate": "Basic"})
    return creds.username


def conn():
    return dbmod.connect(DB)  # runs schema + review-column migration


def package_dir(item_id: int, slug: str) -> Path | None:
    hits = sorted(READY.glob(f"{item_id}-*/"))
    return hits[0] if hits else None


@app.get("/r/{code}")
def shortlink_redirect(code: str, request: Request):
    """Public click-tracked redirect: /r/<code> -> item's affiliate link.

    No auth here by design — this URL is what gets posted in video
    descriptions. Unknown codes 404; items without any link fall back
    to their Shopee product page."""
    c = conn()
    for row in c.execute("SELECT id, product_url, affiliate_url FROM items"):
        if an.short_code(row["id"]) == code:
            an.record_click(c, row["id"], request)
            target = row["affiliate_url"] or row["product_url"]
            return RedirectResponse(target, status_code=302)
    raise HTTPException(404, "shortlink tidak dikenal")


@app.get("/api/stats/analytics")
def analytics_stats(_: str = Depends(auth)):
    """Click + category + platform rollup for the analytics panel."""
    from .shopee_affiliate import effective_link
    c = conn()
    clicks = an.click_counts(c)
    clicks30 = an.click_counts(c, days=30)
    items = c.execute("SELECT id, product_name, category, channel "
                      "FROM items").fetchall()
    top = sorted(
        ({"id": it["id"], "name": it["product_name"],
          "category": it["category"] or "lainnya",
          "clicks": clicks.get(it["id"], 0)} for it in items),
        key=lambda d: -d["clicks"])[:8]
    cats: dict = {}
    for it in items:
        cat = it["category"] or "belum bernama"
        e = cats.setdefault(cat, {"items": 0, "clicks": 0})
        e["items"] += 1
        e["clicks"] += clicks.get(it["id"], 0)
    platforms = {}
    for r in c.execute("SELECT platform, SUM(views), SUM(likes), "
                       "SUM(comments), MAX(fetched_at) FROM platform_stats "
                       "GROUP BY platform").fetchall():
        platforms[r[0]] = {"views": r[1] or 0, "likes": r[2] or 0,
                           "comments": r[3] or 0, "fetched_at": r[4]}
    return {"clicks_total": sum(clicks.values()),
            "clicks_30d": sum(clicks30.values()),
            "daily": an.daily_clicks(c, days=30),
            "top_items": [t for t in top if t["clicks"] > 0],
            "categories": [{"category": k, "items": v["items"],
                            "clicks": v["clicks"],
                            "avg": round(v["clicks"] / max(v["items"], 1), 1)}
                           for k, v in sorted(cats.items(),
                                              key=lambda kv: -kv[1]["clicks"])],
            "platforms": platforms,
            "shortlink_base": settings.public_base_url or ""}


@app.get("/api/video-jobs")
def video_jobs_list(_: str = Depends(auth)):
    from . import video_gen as vg
    c = conn()
    jobs = [dict(r) for r in c.execute(
        "SELECT * FROM video_jobs ORDER BY id DESC LIMIT 50").fetchall()]
    for j in jobs:
        j.pop("script_json", None)
    from . import flow_backend as fb
    return {"jobs": jobs, "top_products": vg.top_products(c, limit=10),
            "flow_credits_used": fb.credits_used_this_month(c),
            "flow_credits_budget": settings.flow_credits_budget}


@app.post("/api/video-jobs")
async def video_jobs_create(request: Request, _: str = Depends(auth)):
    from . import video_gen as vg
    body = await request.json()
    c = conn()
    if body.get("item_id"):
        row = c.execute("SELECT * FROM items WHERE id = ?",
                        (body["item_id"],)).fetchone()
        if not row:
            raise HTTPException(404, "item tidak ada")
        url, name = row["product_url"], row["product_name"]
        shop, iid, cat = row["shop_id"], row["item_id"], row["category"]
        src = row["id"]
    else:
        url = (body.get("product_url") or "").strip()
        name = (body.get("product_name") or "").strip()
        shop, iid = body.get("shop_id") or "", body.get("item_id") or ""
        cat, src = body.get("category") or "", None
        if not url or not name:
            raise HTTPException(400, "product_url + product_name wajib diisi")
    backend = body.get("backend") or "flow"
    if backend not in ("flow", "veo"):
        raise HTTPException(400, "backend harus 'flow' atau 'veo'")
    cur = c.execute(
        "INSERT INTO video_jobs (source_item_id, product_url, product_name,"
        " shop_id, item_id, category, backend) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src, url, name, shop, iid, cat, backend))
    c.commit()
    return JSONResponse({"ok": True, "job_id": cur.lastrowid})


def _run_video_job_sync(job_id: int):
    from . import video_gen as vg
    vg.run_job(conn(), Settings(), job_id)


@app.post("/api/video-jobs/{job_id}/run")
def video_jobs_run(job_id: int, bg: BackgroundTasks,
                   _: str = Depends(auth)):
    c = conn()
    row = c.execute("SELECT status FROM video_jobs WHERE id = ?",
                    (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "job tidak ada")
    if row["status"] in ("scripting", "generating", "assembling",
                         "packaging"):
        raise HTTPException(409, "job sedang berjalan")
    bg.add_task(_run_video_job_sync, job_id)
    return JSONResponse({"ok": True, "job_id": job_id, "status": "started"})


@app.get("/api/stats")
def stats(_: str = Depends(auth)):
    c = conn()
    out = {
        "total": c.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "by_status": dict(c.execute(
            "SELECT status, COUNT(*) FROM items GROUP BY status").fetchall()),
        "by_review": dict(c.execute(
            "SELECT review, COUNT(*) FROM items GROUP BY review").fetchall()),
        "by_channel": dict(c.execute(
            "SELECT channel, COUNT(*) FROM items GROUP BY channel").fetchall()),
        "affiliate": c.execute(
            "SELECT COUNT(*) FROM items WHERE affiliate_url IS NOT NULL "
            "AND affiliate_url != ''").fetchone()[0],
        "posts": [list(r) for r in c.execute(
            "SELECT platform, status, COUNT(*) FROM posts "
            "GROUP BY platform, status").fetchall()],
    }
    return out


@app.get("/api/items")
def items(review: str = "all", region: str = "all", q_text: str = "",
          _: str = Depends(auth)):
    c = conn()
    clicks = an.click_counts(c)
    q = "SELECT * FROM items WHERE status IN ('packaged','downloaded')"
    args = []
    if review != "all":
        q += " AND review = ?"
        args.append(review)
    if region != "all":
        q += " AND region = ?"
        args.append(region)
    if q_text:
        q += " AND (product_name LIKE ? OR channel LIKE ?)"
        args += [f"%{q_text}%", f"%{q_text}%"]
    q += " ORDER BY id DESC LIMIT 500"
    result = []
    for it in c.execute(q, args).fetchall():
        pkg = package_dir(it["id"], it["slug"])
        caps = {}
        if pkg and (pkg / "captions.json").exists():
            try:
                caps = json.loads((pkg / "captions.json").read_text())
            except Exception:
                caps = {}
        yt_title = caps.get("youtube", {}).get("title", "")
        result.append({
            "id": it["id"], "name": it["product_name"],
            "display_name": it["product_name"] or yt_title or None,
            "channel": it["channel"],
            "region": it["region"], "status": it["status"],
            "review": it["review"] or "pending",
            "product_url": it["product_url"],
            "created": it["created_at"],
            "affiliate_url": it["affiliate_url"],
            "affiliate_source": it["affiliate_source"],
            "clicks": clicks.get(it["id"], 0),
            "short_code": an.short_code(it["id"]),
            "shortlink": an.shortlink(it["id"], settings.public_base_url),
            "category": it["category"] or "lainnya",
            "has_video": pkg is not None and (pkg / "video.mp4").exists(),
            "has_thumb": pkg is not None and (pkg / "thumb.jpg").exists(),
            "yt_title": caps.get("youtube", {}).get("title", ""),
            "captions": caps,
        })
    return result


@app.get("/media/{item_id}")
def media(item_id: int, _: str = Depends(auth)):
    c = conn()
    it = c.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not it:
        raise HTTPException(404, "item tidak ada")
    pkg = package_dir(item_id, it["slug"])
    video = pkg / "video.mp4" if pkg else None
    if not video or not video.exists():
        raise HTTPException(404, "video tidak ada")
    return FileResponse(video, media_type="video/mp4")


@app.get("/thumb/{item_id}")
def thumb(item_id: int, _: str = Depends(auth)):
    c = conn()
    it = c.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not it:
        raise HTTPException(404, "item tidak ada")
    pkg = package_dir(item_id, it["slug"])
    img = pkg / "thumb.jpg" if pkg else None
    if not img or not img.exists():
        raise HTTPException(404, "thumbnail tidak ada")
    return FileResponse(img, media_type="image/jpeg")


@app.get("/api/health")
def health_status(_: str = Depends(auth)):
    from .health import (now_ts, read_health, router_status, service_active,
                         worker_status)
    h = read_health()
    return {
        "worker": worker_status(h.get("worker_last_finish")),
        "worker_last_finish": h.get("worker_last_finish"),
        "worker_last_ok": h.get("worker_last_ok"),
        "worker_last_failed": h.get("worker_last_failed"),
        "worker_last_error": h.get("worker_last_error"),
        "router": router_status(h.get("router_ok"), h.get("router_last_probe"),
                                h.get("router_fails_in_a_row", 0)),
        "router_last_probe": h.get("router_last_probe"),
        "router_detail": h.get("router_detail"),
        "ingest": ("ok" if service_active("affiliate-pipeline.service")
                   else "down"),
        "ingest_last_item_at": h.get("ingest_last_item_at"),
        "notifier_configured": bool(settings.notify_bot_token and
                                    settings.notify_chat_id),
        "checked_at": now_ts(),
    }


@app.post("/api/items/bulk-review")
async def bulk_review_api(request: Request, _: str = Depends(auth)):
    from .health import bulk_review
    body = await request.json()
    decision = body.get("decision")
    filt = body.get("filter") or {}
    ids = body.get("ids")
    c = conn()
    try:
        n = bulk_review(c, decision, ids=ids, filt=filt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"ok": True, "updated": n})


@app.post("/api/items/{item_id}/rename")
async def rename_item(item_id: int, request: Request,
                      _: str = Depends(auth)):
    from .name_resolver import apply_names
    body = await request.json()
    name = (body.get("name") or "").strip()
    if len(name) < 3:
        raise HTTPException(400, "nama terlalu pendek")
    c = conn()
    applied, skipped = apply_names(c, {item_id: name}, "manual")
    if not applied:
        raise HTTPException(404, "item tidak ada atau nama tidak valid")
    return JSONResponse({"ok": True, "id": item_id, "name": name})


@app.post("/api/items/{item_id}/category")
async def set_category(item_id: int, request: Request,
                       _: str = Depends(auth)):
    body = await request.json()
    cat = (body.get("category") or "").strip()
    if cat not in list(an.CATEGORIES) + ["lainnya"]:
        raise HTTPException(400, "kategori tidak dikenal")
    c = conn()
    cur = c.execute("UPDATE items SET category = ? WHERE id = ?",
                    (cat, item_id))
    c.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "item tidak ada")
    return JSONResponse({"ok": True, "id": item_id, "category": cat})


@app.post("/api/items/{item_id}/affiliate")
async def make_affiliate(item_id: int, _: str = Depends(auth)):
    from .packager import set_affiliate_link
    from .shopee_affiliate import (ShopeeAffiliateClient, build_an_redir,
                                   platform_sub_ids)
    c = conn()
    it = c.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not it:
        raise HTTPException(404, "item tidak ada")
    try:
        if settings.shopee_affiliate_app_id and settings.shopee_affiliate_secret:
            client = ShopeeAffiliateClient(settings.shopee_affiliate_app_id,
                                           settings.shopee_affiliate_secret)
            url, source = client.generate_link(
                it["product_url"], it["shop_id"], it["item_id"],
                platform_sub_ids("dashboard",
                                 settings.shopee_affiliate_sub_id))
        elif settings.shopee_affiliate_id:
            url = build_an_redir(
                it["product_url"], settings.shopee_affiliate_id,
                f"{settings.shopee_affiliate_sub_id}-dashboard")
            source = "an_redir"
        else:
            raise HTTPException(400, "link afiliasi belum dikonfigurasi: "
                                "isi SHOPEE_AFFILIATE_ID (atau AppId+Secret "
                                "API) di .env dulu")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"generate link gagal: {e}")
    set_affiliate_link(c, item_id, url, source)
    return JSONResponse({"ok": True, "id": item_id,
                         "affiliate_url": url, "affiliate_source": source})


@app.post("/api/items/{item_id}/review")
async def review(item_id: int, request: Request, _: str = Depends(auth)):
    body = await request.json()
    decision = body.get("decision")
    if decision not in ("approved", "rejected", "pending"):
        raise HTTPException(400, "decision tidak valid")
    c = conn()
    c.execute("UPDATE items SET review = ? WHERE id = ?", (decision, item_id))
    c.commit()
    return JSONResponse({"ok": True, "id": item_id, "review": decision})


PAGE = """
<!DOCTYPE html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deins Affiliate — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}
body{margin:0;font-family:Inter,system-ui,sans-serif;background:#f7f7f5;color:#171717;font-size:14px}
header{position:sticky;top:0;z-index:20;background:#fff;border-bottom:1px solid #e7e5e0;padding:13px 26px;display:flex;align-items:center;gap:26px;flex-wrap:wrap}
.logo{font-weight:800;font-size:17px;letter-spacing:-.02em}.logo span{color:#ee4d2d}
.stats{display:flex;gap:20px}
.stat b{font-size:16px;font-weight:700}
.stat span{display:block;font-size:10.5px;color:#8a8a85;text-transform:uppercase;letter-spacing:.06em}
.search{margin-left:auto;width:250px;padding:9px 12px;border:1px solid #e7e5e0;border-radius:10px;font:400 13.5px Inter;background:#fbfbfa}
.search:focus{outline:2px solid #ee4d2d;outline-offset:-1px}
.progwrap{background:#fff;border-bottom:1px solid #e7e5e0;padding:0 26px}
.prog{height:3px;background:#f0efec;border-radius:99px;overflow:hidden}
.prog i{display:block;height:100%;background:#ee4d2d;width:0%}
.bar{display:flex;align-items:center;gap:8px;padding:13px 26px 4px;flex-wrap:wrap;max-width:1460px;margin:0 auto}
.health{display:flex;gap:7px;align-items:center;padding:10px 26px 0;flex-wrap:wrap;max-width:1460px;margin:0 auto}
.hpill{display:flex;align-items:center;gap:6px;font-size:12px;background:#fff;border:1px solid #e7e5e0;border-radius:99px;padding:4px 11px}
.hpill .dot{width:8px;height:8px;border-radius:99px;background:#a3a39d}
.hpill .dot.ok{background:#16a34a}.hpill .dot.down{background:#dc2626}
.hpill .dot.degraded{background:#d97706}.hpill .dot.never{background:#a3a39d}
.hpill .tm{color:#8a8a85}
.card{position:relative}
.selbox{position:absolute;top:8px;left:8px;width:22px;height:22px;z-index:2;accent-color:#ee4d2d;cursor:pointer}
.card.selected{outline:2px solid #ee4d2d}
.bulkbar{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:#171717;color:#fff;border-radius:12px;padding:10px 14px;display:none;gap:10px;align-items:center;z-index:60;box-shadow:0 12px 32px rgba(0,0,0,.28)}
.bulkbar.show{display:flex}
.bulkbar button{padding:8px 14px;border-radius:8px;border:0;font:600 13px Inter;cursor:pointer}
.bulkbar .ok{background:#ee4d2d;color:#fff}.bulkbar .rj{background:#fff;color:#b91c1c}.bulkbar .ghost{background:transparent;color:#fff;border:1px solid #444}
.chip{border:1px solid #e7e5e0;background:#fff;color:#44443f;border-radius:99px;padding:6.5px 14px;font:500 13px Inter;cursor:pointer}
.chip:hover{border-color:#cfccc4}
.chip.on{background:#171717;border-color:#171717;color:#fff}
.chip .c{opacity:.65;font-size:12px;margin-left:3px}
.sep{width:1px;height:20px;background:#e0ded8;margin:0 4px}
.bar .info{margin-left:auto;font-size:12.5px;color:#8a8a85}
main{padding:16px 26px 40px;max-width:1460px;margin:0 auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(248px,1fr));gap:16px}
.card{background:#fff;border:1px solid #e9e7e2;border-radius:16px;overflow:hidden;cursor:pointer;transition:box-shadow .15s,border-color .15s}
.card:hover{box-shadow:0 10px 28px rgba(23,23,23,.09)}
.card img{width:100%;height:150px;object-fit:cover;display:block;background:#eee}
.ph{height:150px;display:flex;align-items:center;justify-content:center;background:#f1efe9;color:#b9b2a2;font-size:22px}
.cb{padding:12px 14px 14px}
.name{font-weight:600;font-size:13.5px;line-height:1.4;height:38px;overflow:hidden}
.meta{display:flex;gap:6px;align-items:center;margin:7px 0;font-size:11.5px;color:#8a8a85;flex-wrap:wrap}
.pill{font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:99px}
.pill.pending{background:#fef3c7;color:#92400e}.pill.approved{background:#dcfce7;color:#166534}.pill.rejected{background:#fee2e2;color:#991b1b}
.pill.my{background:#171717;color:#fbbf24}.pill.id{background:#f1f1ee;color:#6b6b66}
.cap{font-size:12.5px;color:#5c5c58;line-height:1.5;height:37px;overflow:hidden}
.cap.wait{color:#b45309}
.row{display:flex;gap:8px;margin-top:11px}
.row button{flex:1;padding:8px 0;border-radius:9px;border:1px solid #e7e5e0;background:#fff;font:600 13px Inter;cursor:pointer}
.row button.ok{background:#ee4d2d;border-color:#ee4d2d;color:#fff}
.row button.ok:hover{background:#d63f21}
.row button.rj:hover{background:#fef2f2;border-color:#fecaca}
.more{display:block;margin:22px auto 0;padding:10px 26px;border-radius:10px;border:1px solid #e7e5e0;background:#fff;font:600 13.5px Inter;cursor:pointer}
.empty{grid-column:1/-1;text-align:center;color:#8a8a85;padding:44px 0;line-height:1.7}
/* ---- drawer ---- */
.scrim{position:fixed;inset:0;background:rgba(20,18,14,.45);opacity:0;pointer-events:none;transition:opacity .2s;z-index:40}
.scrim.open{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;right:0;bottom:0;width:480px;max-width:94vw;background:#fff;z-index:50;transform:translateX(102%);transition:transform .24s ease;display:flex;flex-direction:column;box-shadow:-18px 0 44px rgba(0,0,0,.16)}
.drawer.open{transform:none}
.dhead{display:flex;align-items:center;gap:8px;padding:14px 18px;border-bottom:1px solid #efeeea}
.dhead .mono{font-size:12px;color:#8a8a85}
.dhead .x{margin-left:auto;border:0;background:#f4f4f2;width:32px;height:32px;border-radius:9px;font-size:15px;cursor:pointer}
.dbody{overflow:auto;padding:16px 18px;flex:1}
.dbody video{width:100%;max-height:52vh;background:#000;border-radius:12px}
.dname{font-size:19px;font-weight:700;letter-spacing:-.01em;line-height:1.3;margin:13px 0 4px}
.dsub{font-size:12.5px;color:#8a8a85}
.notice{background:#fffbeb;border:1px solid #fde68a;border-radius:11px;padding:10px 13px;font-size:13px;line-height:1.55;margin:12px 0;color:#78350f}
.linkbtn{display:inline-block;background:#171717;color:#fff;text-decoration:none;padding:8.5px 14px;border-radius:9px;font-weight:600;font-size:13px;margin:10px 0 2px}
.rename{margin:10px 0 2px}
.rename button{padding:7px 12px;border-radius:8px;border:1px solid #e7e5e0;background:#fff;font:600 12.5px Inter;cursor:pointer}
.rename input{width:100%;padding:8px 10px;border:1px solid #e7e5e0;border-radius:8px;font:400 13.5px Inter;margin-bottom:6px}
.analytics{margin:0 22px 4px;background:#fff;border:1px solid #eceae6;border-radius:14px;padding:14px 16px}
.analytics h3{margin:0 0 2px;font-size:15px}
.analytics .dsub{margin-bottom:10px}
.analytics table{width:100%;border-collapse:collapse;font-size:13px}
.analytics th{text-align:left;color:#8a8a85;font-weight:600;padding:4px 8px 4px 0;border-bottom:1px solid #efeeea}
.analytics td{padding:5px 8px 5px 0;border-bottom:1px solid #f4f4f2}
.analytics .big{font-size:21px;font-weight:700}
.analytics .cols{display:flex;gap:28px;flex-wrap:wrap}
.analytics .col{flex:1;min-width:230px}
.analytics select{padding:6px 8px;border:1px solid #e7e5e0;border-radius:8px;font:600 12.5px Inter;background:#fff}
.affbox{border:1px solid #e7e5e0;border-radius:11px;padding:11px 13px;margin:12px 0;background:#fbfbfa;word-break:break-all}
.affbox b{font-size:12.5px}
.affbox a{color:#c2410c;font-size:12.5px}
.affbtn{margin-top:8px;padding:8px 14px;border-radius:9px;border:0;background:#ee4d2d;color:#fff;font:600 13px Inter;cursor:pointer}
.tabs{display:flex;gap:3px;border-bottom:1px solid #e7e5e0;margin-top:14px}
.tab{border:0;background:none;padding:8px 11px;font:600 13px Inter;color:#8a8a85;cursor:pointer;border-bottom:2px solid transparent}
.tab.on{color:#171717;border-bottom-color:#ee4d2d}
.panel{padding:12px 2px;font-size:13.5px;line-height:1.65;color:#33332f}
.panel p{margin:0 0 9px}
.panel .ttl{font-weight:700;font-size:14.5px;color:#171717}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.tag{font-size:12px;background:#f1f1ee;border-radius:99px;padding:2.5px 9px}
.ccount{font-size:11.5px;color:#a3a39d;margin-top:8px}
.dacts{display:flex;gap:8px;padding:13px 18px;border-top:1px solid #efeeea;align-items:center}
.dacts button{flex:1;padding:11px;border-radius:10px;border:1px solid #e7e5e0;background:#fff;font:600 14px Inter;cursor:pointer}
.dacts button small{display:block;font-weight:400;font-size:10.5px;color:#a3a39d;margin-top:1px}
.dacts .ok{background:#ee4d2d;border-color:#ee4d2d;color:#fff}.dacts .ok small{color:#ffd9cf}
.dacts .rj{color:#b91c1c}
.dacts .pos{font-size:12px;color:#8a8a85;white-space:nowrap}
@media (max-width:700px){.stats{gap:13px}.search{width:100%;margin:8px 0 0}.bar,main{padding-left:14px;padding-right:14px}header{padding:12px 14px}}
</style></head><body>
<header>
 <div class="logo">Deins<span>·</span>Affiliate</div>
 <div class="stats">
  <div class="stat"><b id="s-total">–</b><span>total item</span></div>
  <div class="stat"><b id="s-pend">–</b><span>menunggu</span></div>
  <div class="stat"><b id="s-ok">–</b><span>disetujui</span></div>
  <div class="stat"><b id="s-no">–</b><span>ditolak</span></div>
 </div>
 <input class="search" id="q" type="search" placeholder="Cari produk atau channel…">
</header>
<div class="progwrap"><div class="prog"><i id="progbar"></i></div></div>
<div class="health" id="health"></div>
<section class="analytics" id="analytics"><div class="dsub">Memuat analitik…</div></section>
<section class="analytics" id="vgen"><div class="dsub">Memuat Video AI…</div></section>
<div class="bulkbar" id="bulkbar">
 <span id="bulkcount"></span>
 <button class="ok" data-bulk="approved">Setujui</button>
 <button class="rj" data-bulk="rejected">Tolak</button>
 <button class="ghost" data-bulk="clear">Batal</button>
</div>
<div class="bar" id="chips">
 <button class="chip on" data-grp="review" data-v="all">Semua</button>
 <button class="chip" data-grp="review" data-v="pending">Menunggu <span class="c" id="c-pending"></span></button>
 <button class="chip" data-grp="review" data-v="approved">Disetujui <span class="c" id="c-approved"></span></button>
 <button class="chip" data-grp="review" data-v="rejected">Ditolak <span class="c" id="c-rejected"></span></button>
 <span class="sep"></span>
 <button class="chip on" data-grp="region" data-v="all">Semua region</button>
 <button class="chip" data-grp="region" data-v="ID">Indonesia</button>
 <button class="chip" data-grp="region" data-v="MY">Malaysia</button>
 <span class="info" id="info"></span>
 <button class="chip" id="selall">Pilih semua di filter</button>
 <button class="chip" id="approveall">Setujui semua hasil filter</button>
</div>
<main>
 <div class="grid" id="grid"></div>
 <button class="more" id="more" style="display:none">Muat lebih banyak</button>
</main>
<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer"></aside>
<script>
const NL=String.fromCharCode(10);
const $=function(s){return document.querySelector(s)};
const grid=$('#grid'), drawer=$('#drawer'), scrim=$('#scrim');
const esc=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})};
let ITEMS=[], SHOWN=60, SEL=null, TAB='youtube';
let SEL_IDS=new Set();
function fmtTime(ts){if(!ts)return '—';return new Date(ts*1000).toLocaleString('id-ID',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}
function dotCls(st){return st==='ok'?'ok':st==='down'?'down':st==='degraded'?'degraded':'never'}
async function loadHealth(){
 try{
  const h=await api('/api/health');
  const pill=function(label,st,txt){return '<span class="hpill"><span class="dot '+dotCls(st)+'"></span>'+label+(txt?' <span class="tm">'+txt+'</span>':'')+'</span>'};
  $('#health').innerHTML=
   pill('Worker',h.worker,'terakhir '+fmtTime(h.worker_last_finish)+(h.worker_last_failed?(' · '+h.worker_last_failed+' gagal'):''))
   +pill('Router',h.router,h.router_detail||'')
   +pill('Ingest',h.ingest,'item terakhir '+fmtTime(h.ingest_last_item_at))
   +pill('Notifikasi Telegram',h.notifier_configured?'ok':'never',h.notifier_configured?'aktif':'belum dikonfigurasi');
 }catch(e){}
}
function renderBulk(){
 const b=$('#bulkbar');
 if(SEL_IDS.size){b.classList.add('show');$('#bulkcount').textContent=SEL_IDS.size+' item dipilih';}
 else b.classList.remove('show');
 document.querySelectorAll('.card').forEach(function(el){
   const id=Number(el.dataset.open);
   el.classList.toggle('selected',SEL_IDS.has(id));
   const cb=el.querySelector('.selbox'); if(cb)cb.checked=SEL_IDS.has(id);
 });
}
let F={review:'all',region:'all',q:''};
async function api(u,o){const r=await fetch(u,o);return r.json()}
function paras(t){return String(t||'').split(NL+NL).map(function(x){return '<p>'+esc(x).split(NL).join('<br>')+'</p>'}).join('')}
async function stats(){
 const s=await api('/api/stats');
 $('#s-total').textContent=s.total;
 $('#s-pend').textContent=s.by_review.pending||0;
 $('#s-ok').textContent=s.by_review.approved||0;
 $('#s-no').textContent=s.by_review.rejected||0;
 $('#c-pending').textContent=s.by_review.pending||0;
 $('#c-approved').textContent=s.by_review.approved||0;
 $('#c-rejected').textContent=s.by_review.rejected||0;
 const done=(s.by_review.approved||0)+(s.by_review.rejected||0);
 $('#progbar').style.width=(s.total?Math.round(done/s.total*100):0)+'%';
 $('#info').textContent=done+' dari '+s.total+' item sudah direview · '+(s.affiliate||0)+' sudah punya link afiliasi';
}
function cardHTML(it){
 const wait=it.status!=='packaged';
 return '<div class="card" data-open="'+it.id+'">'
 +'<input type="checkbox" class="selbox" data-sel="'+it.id+'">'
 +(it.has_thumb?'<img loading="lazy" src="/thumb/'+it.id+'" alt="">':'<div class="ph">▶</div>')
 +'<div class="cb"><div class="name">'+(esc(it.display_name)||'(nama belum terdeteksi)')+'</div>'
 +'<div class="meta"><span>#'+it.id+'</span><span>'+esc(it.channel)+'</span>'
 +'<span class="pill '+(it.region==='MY'?'my':'id')+'">'+(it.region||'')+'</span>'
 +(it.affiliate_url?'<span class="pill approved">link ✓</span>':'')
 +'<span class="pill '+it.review+'">'+it.review+'</span></div>'
 +(wait?'<div class="cap wait">Menunggu caption worker…</div>':'<div class="cap">'+esc(it.yt_title||'')+'</div>')
 +'<div class="row"><button class="ok" data-act="approved" data-id="'+it.id+'">Setujui</button>'
 +'<button class="rj" data-act="rejected" data-id="'+it.id+'">Tolak</button></div>'
 +'</div></div>';
}
function renderGrid(){
 const part=ITEMS.slice(0,SHOWN);
 grid.innerHTML=part.map(cardHTML).join('')||'<div class="empty">Tidak ada item yang cocok dengan filter ini.<br>Coba longgarkan filter atau kata kuncinya.</div>';
 $('#more').style.display=ITEMS.length>SHOWN?'block':'none';
 renderBulk();
}
async function bulkRev(decision,useFilter){
 let body;
 if(useFilter){body={decision:decision,filter:{review:F.review,region:F.region,q_text:F.q}};}
 else{body={decision:decision,ids:Array.from(SEL_IDS)};}
 const j=await api('/api/items/bulk-review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 SEL_IDS.clear();
 if(useFilter){await load();}
 else{await load();}
 stats();
}
async function load(){
 SEL_IDS.clear();
 const qs=new URLSearchParams({review:F.review,region:F.region,q_text:F.q});
 ITEMS=await api('/api/items?'+qs); SHOWN=60;
 if(SEL!=null&&!ITEMS.find(function(i){return i.id===SEL}))closeDrawer();
 renderGrid(); if(SEL!=null)renderDrawer();
}
async function rev(id,decision){
 await fetch('/api/items/'+id+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:decision})});
 const it=ITEMS.find(function(i){return i.id===id}); if(it)it.review=decision;
 stats();
 if(F.review!=='all'){await load();return}
 renderGrid(); if(SEL===id)renderDrawer();
}
function capText(it){
 const c=it.captions||{};
 if(TAB==='youtube'){const y=c.youtube||{};return '<div class="ttl">'+esc(y.title||'')+'</div>'+paras(y.description||'')}
 const v=c[TAB]||{};return paras(v.text||'(kosong)');
}
function renderDrawer(){
 const it=ITEMS.find(function(i){return i.id===SEL}); if(!it)return;
 const idx=ITEMS.indexOf(it), c=it.captions||{}, tags=(c.youtube&&c.youtube.tags)||[];
 const wait=it.status!=='packaged';
 let h='<div class="dhead"><span class="mono">ITEM #'+it.id+'</span>'
 +'<span class="pill '+it.review+'">'+it.review+'</span>'
 +'<span class="pill '+(it.region==='MY'?'my':'id')+'">'+(it.region==='MY'?'Malaysia':'Indonesia')+'</span>'
 +'<span class="mono">'+esc(it.created||'')+'</span>'
 +'<button class="x" data-close="1">✕</button></div><div class="dbody">'
 +(it.has_video?'<video controls preload="metadata" poster="'+(it.has_thumb?'/thumb/'+it.id:'')+'" src="/media/'+it.id+'"></video>':'')
 +'<div class="dname">'+(esc(it.display_name)||'Nama produk belum terdeteksi')+'</div>'
 +'<div class="dsub">dari channel <b>'+esc(it.channel)+'</b> · status paket: '+esc(it.status)+'</div>'
 +'<div class="rename" id="renamebox"><button data-rename="'+it.id+'">✏️ Ubah nama produk</button></div>'
 +'<a class="linkbtn" href="'+esc(it.product_url)+'" target="_blank" rel="noopener">Buka produk di Shopee ↗</a>'
 +'<div class="affbox"><b>Shortlink (yang dipasang di caption)</b>'
 +'<div><a href="'+esc(it.shortlink)+'" target="_blank" rel="noopener">'+esc(it.shortlink)+'</a></div>'
 +'<div class="dsub">'+it.clicks+' klik tercatat — setiap klik lewat link ini dicatat sebelum diteruskan ke link afiliasi.</div>'
 +'<button class="affbtn" data-copy="'+esc(it.shortlink)+'">Salin shortlink</button></div>'
 +'<div class="rename">Kategori: <select data-cat="'+it.id+'">'+['fashion','kecantikan','rumah','dapur','elektronik','kesehatan','anak & mainan','olahraga','makanan','lainnya'].map(function(x){return '<option value="'+x+'"'+(x===it.category?' selected':'')+'>'+x+'</option>'}).join('')+'</select> <span class="dsub">otomatis dari nama produk, bisa diubah.</span></div>'
 +'<div class="affbox"><b>Link afiliasi kamu</b>'
 +(it.affiliate_url?'<div><a href="'+esc(it.affiliate_url)+'" target="_blank" rel="noopener">'+esc(it.affiliate_url)+'</a></div><div class="dsub">sumber: '+esc(it.affiliate_source||'')+' — link inilah yang dipakai saat posting.</div>':'<div class="dsub">Belum ada — paket ini masih memakai link si pembagi channel.</div><button class="affbtn" data-aff="'+it.id+'">Buat link afiliasi</button>')
 +'</div>';
 if(wait)h+='<div class="notice"><b>Paket belum dibuat.</b> Item ini sudah terunduh dan menunggu giliran caption worker (jalan tiap 20 menit). Video dan caption akan muncul setelah paketnya jadi — review tetap bisa dilakukan dari sekarang.</div>';
 if(it.region==='MY')h+='<div class="notice"><b>Item Malaysia.</b> Videonya bisa dipakai, tapi link-nya masih menunjuk Shopee MY dan nama produk belum diketahui — item ini menunggu pemetaan link ke produk Shopee Indonesia sebelum siap posting.</div>';
 if(!wait){
  h+='<div class="tabs">'+['youtube','threads','facebook','shopee'].map(function(t){return '<button class="tab '+(TAB===t?'on':'')+'" data-tab="'+t+'">'+t[0].toUpperCase()+t.slice(1)+'</button>'}).join('')+'</div>'
  +'<div class="panel">'+capText(it)
  +(TAB==='youtube'&&tags.length?'<div class="tags">'+tags.map(function(t){return '<span class="tag">'+esc(t)+'</span>'}).join('')+'</div>':'')
  +'<div class="ccount">'+(TAB==='youtube'?((c.youtube||{}).description||'').length:((c[TAB]||{}).text||'').length)+' karakter</div></div>';
 }
 h+='</div><div class="dacts">'
 +'<button class="rj" data-act="rejected" data-id="'+it.id+'">Tolak<small>tombol X</small></button>'
 +'<button data-act="pending" data-id="'+it.id+'">Urungkan<small>tombol U</small></button>'
 +'<span class="pos">'+(idx+1)+' / '+ITEMS.length+'</span>'
 +'<button class="ok" data-act="approved" data-id="'+it.id+'">Setujui<small>tombol A</small></button></div>';
 drawer.innerHTML=h;
}
function openDrawer(id){SEL=id;renderDrawer();drawer.classList.add('open');scrim.classList.add('open')}
function closeDrawer(){SEL=null;drawer.classList.remove('open');scrim.classList.remove('open')}
document.addEventListener('change',function(e){
 const cs=e.target.closest('[data-cat]');
 if(!cs)return;
 fetch('/api/items/'+cs.dataset.cat+'/category',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:cs.value})})
  .then(function(r){return r.json()})
  .then(function(j){if(j.ok){const it=ITEMS.find(function(i){return i.id===Number(cs.dataset.cat)});if(it)it.category=j.category;analytics();}});
});
function analytics(){
 fetch('/api/stats/analytics').then(function(r){return r.json()}).then(function(a){
  const el=$('#analytics'); if(!el)return;
  let h='<h3>📊 Analitik</h3><div class="dsub">Klik shortlink per item + kategori produk yang paling laku. Views/likes platform muncul setelah ada video yang terposting (fitur posting).</div><div class="cols">';
  h+='<div class="col"><div class="big">'+a.clicks_30d+'</div><div class="dsub">klik 30 hari terakhir · total '+a.clicks_total+'</div>';
  if(a.top_items.length){h+='<table><tr><th>Item teratas</th><th>Klik</th></tr>'+a.top_items.map(function(t){return '<tr><td>'+esc(t.name||'(tanpa nama)')+'</td><td>'+t.clicks+'</td></tr>'}).join('')+'</table>';}
  else{h+='<div class="dsub">Belum ada klik — klik tercatat begitu shortlink dipakai di caption postingan.</div>';}
  h+='</div><div class="col"><table><tr><th>Kategori</th><th>Item</th><th>Klik</th><th>Rata2</th></tr>'+a.categories.map(function(x){return '<tr><td>'+esc(x.category)+'</td><td>'+x.items+'</td><td>'+x.clicks+'</td><td>'+x.avg+'</td></tr>'}).join('')+'</table>';
  const pf=a.platforms;
  if(Object.keys(pf).length){h+='<div class="dsub" style="margin-top:10px">Platform: '+Object.keys(pf).map(function(p){return p+' 👁 '+pf[p].views+' ♥ '+pf[p].likes}).join(' · ')+'</div>';}
  else{h+='<div class="dsub" style="margin-top:10px">Views/likes platform: belum terhubung (butuh akun posting YouTube/FB/Threads).</div>';}
  if(!a.shortlink_base){h+='<div class="notice"><b>Shortlink belum punya domain publik tetap.</b> Saat ini domain-nya ikut tunnel dashboard yang berubah tiap VM restart — set PUBLIC_BASE_URL di .env ke URL tunnel terbaru (atau domain sendiri nanti) supaya shortlink yang diposting tidak basi.</div>';}
  h+='</div></div>';
  el.innerHTML=h;
 });
}
document.addEventListener('click',function(e){
 const rn=e.target.closest('[data-rename]');
 if(rn){const box=$('#renamebox');
  const cur=ITEMS.find(function(i){return i.id===Number(rn.dataset.rename)});
  box.innerHTML='<input id="renameinput" value="'+esc(cur?cur.display_name:'')+'">'
   +'<button data-renamesave="'+rn.dataset.rename+'">Simpan nama</button>';
  const inp=$('#renameinput'); if(inp)inp.focus();
  return}
 const rns=e.target.closest('[data-renamesave]');
 if(rns){const id=Number(rns.dataset.renamesave);
  const val=$('#renameinput').value.trim();
  if(val.length<3){alert('Nama terlalu pendek');return}
  fetch('/api/items/'+id+'/rename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:val})})
   .then(function(r){return r.json()})
   .then(function(j){if(j.ok){const it=ITEMS.find(function(i){return i.id===id});
     if(it){it.display_name=j.name;it.name=j.name} renderDrawer(); renderGrid(); stats();}
     else alert(j.detail||'gagal menyimpan nama');});
  return}
 const cp=e.target.closest('[data-copy]');
 if(cp){navigator.clipboard.writeText(cp.dataset.copy);cp.textContent='Tersalin!';setTimeout(function(){cp.textContent='Salin shortlink'},1500);return}
 const sel=e.target.closest('[data-sel]');
 if(sel){const id=Number(sel.dataset.sel);
  if(sel.checked)SEL_IDS.add(id); else SEL_IDS.delete(id);
  renderBulk(); return}
 const bb=e.target.closest('[data-bulk]');
 if(bb){if(bb.dataset.bulk==='clear'){SEL_IDS.clear();renderBulk();} else bulkRev(bb.dataset.bulk,false); return}
 const aff=e.target.closest('[data-aff]');
 if(aff){const id=Number(aff.dataset.aff);
  fetch('/api/items/'+id+'/affiliate',{method:'POST'})
   .then(function(r){return r.json()})
   .then(function(j){
     if(j.affiliate_url){const it=ITEMS.find(function(i){return i.id===id});
       if(it){it.affiliate_url=j.affiliate_url;it.affiliate_source=j.affiliate_source}
       renderDrawer(); stats();
     } else {alert(j.detail||'gagal membuat link');}
   });
  return}
 const act=e.target.closest('[data-act]');
 if(act){e.stopPropagation();rev(Number(act.dataset.id),act.dataset.act);return}
 const tab=e.target.closest('[data-tab]'); if(tab){TAB=tab.dataset.tab;renderDrawer();return}
 if(e.target.closest('[data-close]')){closeDrawer();return}
 const card=e.target.closest('[data-open]'); if(card){openDrawer(Number(card.dataset.open));return}
});
scrim.addEventListener('click',closeDrawer);
$('#chips').addEventListener('click',function(e){
 const b=e.target.closest('.chip'); if(!b)return;
 document.querySelectorAll('.chip[data-grp="'+b.dataset.grp+'"]').forEach(function(x){x.classList.remove('on')});
 b.classList.add('on'); F[b.dataset.grp]=b.dataset.v; load();
});
let qt; $('#q').addEventListener('input',function(e){clearTimeout(qt);qt=setTimeout(function(){F.q=e.target.value;load()},220)});
$('#more').addEventListener('click',function(){SHOWN+=60;renderGrid()});
$('#selall').addEventListener('click',function(){
 ITEMS.slice(0,SHOWN).forEach(function(i){SEL_IDS.add(i.id)}); renderBulk();
});
$('#approveall').addEventListener('click',function(){
 if(confirm('Setujui '+ITEMS.length+' item yang cocok dengan filter saat ini?'))bulkRev('approved',true);
});
loadHealth(); setInterval(loadHealth,60000);
document.addEventListener('keydown',function(e){
 if(e.target.tagName==='INPUT')return;
 if(SEL==null)return;
 const idx=ITEMS.findIndex(function(i){return i.id===SEL});
 if(e.key==='Escape')closeDrawer();
 else if(e.key==='a'||e.key==='A'){const id=SEL;rev(id,'approved');const n=ITEMS.slice(idx+1).find(function(i){return i.review==='pending'})||ITEMS[idx+1];if(n&&F.review==='all')openDrawer(n.id)}
 else if(e.key==='x'||e.key==='X'){const id=SEL;rev(id,'rejected');const n=ITEMS.slice(idx+1).find(function(i){return i.review==='pending'})||ITEMS[idx+1];if(n&&F.review==='all')openDrawer(n.id)}
 else if(e.key==='u'||e.key==='U')rev(SEL,'pending');
 else if(e.key==='ArrowDown'){if(ITEMS[idx+1])openDrawer(ITEMS[idx+1].id)}
 else if(e.key==='ArrowUp'){if(ITEMS[idx-1])openDrawer(ITEMS[idx-1].id)}
});
stats(); load(); analytics(); vgen();
function vgen(){
 fetch('/api/video-jobs').then(function(r){return r.json()}).then(function(d){
  const el=$('#vgen'); if(!el)return;
  let h='<h3>🎬 Video AI</h3><div class="dsub">Cari produk terbaik (berdasarkan klik shortlink), generate script + video AI, lalu paket jadi masuk antrean approve seperti biasa. Backend: <b>Flow</b> (pakai kredit langganan Google AI Pro — gratis sampai kredit habis, butuh login Google sekali di browser server) atau <b>Veo API</b> (bayar per detik, butuh GEMINI_API_KEY). Script butuh router hidup. Estimasi kredit Flow bulan ini: <b>'+d.flow_credits_used+' / '+d.flow_credits_budget+'</b>.</div>'
   +'<div class="rename">Backend: <select id="vbackend"><option value="flow" selected>Flow (kredit Pro)</option><option value="veo">Veo API (bayar)</option></select> <span class="dsub">Job Flow berhenti di queued_flow — agen menjalankan langkah browser-nya.</span></div>';
  h+='<div class="cols"><div class="col"><b>Produk terbaik (klik terbanyak)</b><table><tr><th>Produk</th><th>Klik</th><th></th></tr>'
   +d.top_products.map(function(t){return '<tr><td>'+esc(t.name||'(tanpa nama)')+'</td><td>'+t.clicks+'</td><td><button data-vgen="'+t.item_id+'">🎬 Generate</button></td></tr>'}).join('')+'</table></div>';
  h+='<div class="col"><b>Produk baru (manual)</b><div class="rename"><input id="vurl" placeholder="Link produk Shopee"><input id="vname" placeholder="Nama produk"><button id="vcreate">Buat job video AI</button></div>';
  h+='<b>Antrean job</b> <button id="vrefresh">Muat ulang</button><table><tr><th>#</th><th>Produk</th><th>Backend</th><th>Status</th><th></th></tr>'
   +d.jobs.map(function(j){return '<tr><td>'+j.id+'</td><td>'+esc(j.product_name)+'</td><td>'+(j.backend||'flow')+(j.credits_used?' ('+j.credits_used+' kredit)':'')+'</td><td>'+j.status+(j.error?' — '+esc(j.error.slice(0,90)):'')+'</td><td>'
   +(j.status==='done'&&j.package_item_id?'<button data-open="'+j.package_item_id+'">Lihat di antrean</button>':(j.status==='failed'||j.status==='pending'?'<button data-vrun="'+j.id+'">Jalankan</button>':''))+'</td></tr>'}).join('')+'</table></div></div>';
  el.innerHTML=h;
  el.querySelectorAll('[data-vgen]').forEach(function(b){b.addEventListener('click',function(){
   const be=($('#vbackend')||{}).value||'flow';
   fetch('/api/video-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:Number(b.dataset.vgen),backend:be})}).then(function(){vgen()})})});
  const vc=$('#vcreate');
  if(vc)vc.addEventListener('click',function(){
   const url=$('#vurl').value.trim(), name=$('#vname').value.trim();
   if(!url||!name){alert('Isi link + nama produk');return}
   const be2=($('#vbackend')||{}).value||'flow';
   fetch('/api/video-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_url:url,product_name:name,backend:be2})}).then(function(){vgen()})});
  el.querySelectorAll('[data-vrun]').forEach(function(b){b.addEventListener('click',function(){
   fetch('/api/video-jobs/'+b.dataset.vrun+'/run',{method:'POST'}).then(function(){setTimeout(vgen,1500)})})});
  const vr=$('#vrefresh'); if(vr)vr.addEventListener('click',vgen);
 });
}
</script></body></html>
"""


@app.get("/mock/{name}", response_class=HTMLResponse)
def mock(name: str, _: str = Depends(auth)):
    f = ROOT / "src" / "mocks" / f"{name}.html"
    if name not in ("a", "b", "c") or not f.exists():
        raise HTTPException(404, "mock tidak ada")
    return f.read_text()


@app.get("/", response_class=HTMLResponse)
def home(_: str = Depends(auth)):
    return PAGE
