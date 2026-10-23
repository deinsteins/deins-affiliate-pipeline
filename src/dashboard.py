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

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

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
        "posts": [list(r) for r in c.execute(
            "SELECT platform, status, COUNT(*) FROM posts "
            "GROUP BY platform, status").fetchall()],
    }
    return out


@app.get("/api/items")
def items(review: str = "all", region: str = "all", _: str = Depends(auth)):
    c = conn()
    q = "SELECT * FROM items WHERE status IN ('packaged','downloaded')"
    args = []
    if review != "all":
        q += " AND review = ?"
        args.append(review)
    if region != "all":
        q += " AND region = ?"
        args.append(region)
    q += " ORDER BY id DESC LIMIT 300"
    result = []
    for it in c.execute(q, args).fetchall():
        pkg = package_dir(it["id"], it["slug"])
        caps = {}
        if pkg and (pkg / "captions.json").exists():
            try:
                caps = json.loads((pkg / "captions.json").read_text())
            except Exception:
                caps = {}
        result.append({
            "id": it["id"], "name": it["product_name"], "channel": it["channel"],
            "region": it["region"], "status": it["status"],
            "review": it["review"] or "pending",
            "product_url": it["product_url"],
            "has_video": pkg is not None and (pkg / "video.mp4").exists(),
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


PAGE = """<!DOCTYPE html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deins Affiliate Pipeline — Dashboard</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#faf7f2;color:#1c1917}
header{background:#7c2d12;color:#fff;padding:14px 18px}
header h1{font-size:18px;margin:0}
.stats{display:flex;gap:8px;flex-wrap:wrap;padding:12px 18px}
.chip{background:#fff;border:1px solid #e7ddd0;border-radius:999px;padding:5px 12px;font-size:13px;cursor:pointer}
.chip.on{background:#7c2d12;color:#fff;border-color:#7c2d12}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;padding:6px 18px 30px}
.card{background:#fff;border:1px solid #e7ddd0;border-radius:12px;overflow:hidden}
.card video{width:100%;aspect-ratio:16/9;background:#000;object-fit:contain}
.body{padding:10px 12px}
.name{font-weight:600;font-size:14px}
.meta{font-size:12px;color:#78716c;margin:2px 0 6px}
.yt{font-size:13px;margin:6px 0}
details{font-size:12.5px;margin-top:6px} summary{cursor:pointer;color:#7c2d12}
.cap{white-space:pre-wrap;background:#faf7f2;border-radius:8px;padding:7px;margin:4px 0}
.btns{display:flex;gap:8px;margin-top:10px}
button{flex:1;padding:8px;border-radius:8px;border:0;font-size:14px;cursor:pointer}
.ok{background:#15803d;color:#fff}.no{background:#e7e5e4}.rj{background:#b91c1c;color:#fff}
.badge{font-size:11px;padding:2px 8px;border-radius:999px;background:#fef3c7}
.badge.approved{background:#dcfce7}.badge.rejected{background:#fee2e2}
a{color:#c2410c}
</style></head><body>
<header><h1>🎬 Deins Affiliate Pipeline</h1><div id="sub" style="font-size:13px;opacity:.85">memuat…</div></header>
<div class="stats" id="filters">
 <span class="chip on" data-r="all">Semua</span>
 <span class="chip" data-r="pending">⏳ Menunggu review</span>
 <span class="chip" data-r="approved">✅ Disetujui</span>
 <span class="chip" data-r="rejected">❌ Ditolak</span>
 <span class="chip" data-r="all" data-g="MY">🇲🇾 Item MY</span>
</div>
<div class="grid" id="grid"></div>
<script>
let F={review:'all',region:'all'};
const grid=document.getElementById('grid');
async function stats(){
 const s=await (await fetch('/api/stats')).json();
 document.getElementById('sub').textContent=
  `${s.total} item · ${s.by_review.pending||0} menunggu · ${s.by_review.approved||0} disetujui · ${s.by_review.rejected||0} ditolak`;
}
async function load(){
 const q=new URLSearchParams(F);
 const data=await (await fetch('/api/items?'+q)).json();
 grid.innerHTML=data.map(it=>{
  const caps=Object.entries(it.captions||{}).map(([k,v])=>{
   const txt = k==='youtube' ? (v.description||'') : (v.text||'');
   return `<details><summary>${k}</summary><div class="cap">${(k==='youtube'?'<b>'+(v.title||'')+'</b>\n':'')+txt}</div></details>`}).join('');
  return `<div class="card">
   ${it.has_video?`<video controls preload="metadata" src="/media/${it.id}"></video>`:''}
   <div class="body">
    <div class="name">#${it.id} ${it.name||'(produk MY — nama belum diketahui)'}</div>
    <div class="meta">${it.channel} · region ${it.region||'-'} · <span class="badge ${it.review}">${it.review}</span></div>
    <div class="yt">🎬 ${it.yt_title||''}</div>
    <a href="${it.product_url}" target="_blank" rel="noopener">link produk ↗</a>
    ${caps}
    <div class="btns">
      <button class="ok" onclick="rev(${it.id},'approved')">✅ Setujui</button>
      <button class="rj" onclick="rev(${it.id},'rejected')">Tolak</button>
      <button class="no" onclick="rev(${it.id},'pending')">Reset</button>
    </div>
   </div></div>`}).join('') || '<p style="padding:0 18px">Tidak ada item untuk filter ini.</p>';
}
async function rev(id,decision){
 await fetch('/api/items/'+id+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision})});
 stats(); load();
}
document.getElementById('filters').addEventListener('click',e=>{
 const el=e.target.closest('.chip'); if(!el) return;
 document.querySelectorAll('.chip').forEach(c=>c.classList.remove('on')); el.classList.add('on');
 F={review:el.dataset.r, region:el.dataset.g||'all'}; load();
});
stats(); load();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home(_: str = Depends(auth)):
    return PAGE
