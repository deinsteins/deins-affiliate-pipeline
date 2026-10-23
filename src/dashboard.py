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
def items(review: str = "all", region: str = "all", q_text: str = "",
          _: str = Depends(auth)):
    c = conn()
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
<title>Konsol Review — Deins Affiliate Pipeline</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--ink:#17130c;--ink2:#241d13;--paper:#faf9f6;--surface:#ffffff;--line:#e8e4dc;
--txt:#211d16;--mut:#7a7263;--acc:#e8490f;--acc-soft:#fdeee6;--ok:#177245;--ok-soft:#e3f2e9;
--bad:#c0362c;--bad-soft:#fbeae8;--warn:#a86a12;--warn-soft:#fbf0da;--rad:10px}
*{box-sizing:border-box} html,body{height:100%}
body{margin:0;font-family:Inter,system-ui,sans-serif;background:var(--paper);color:var(--txt);font-size:14px}
.app{display:grid;grid-template-columns:248px 400px 1fr;height:100vh}
/* ---------- sidebar ---------- */
.side{background:var(--ink);color:#efe9dc;display:flex;flex-direction:column;padding:20px 18px;gap:22px;overflow:auto}
.brand .mark{font-family:"Space Grotesk";font-weight:700;font-size:19px;letter-spacing:-.02em}
.brand .mark em{font-style:normal;color:var(--acc)}
.brand .sub{font-size:12px;color:#a89e8a;margin-top:2px}
.blok .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:#a89e8a;margin-bottom:8px}
.nums{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.num{background:var(--ink2);border:1px solid #372d1d;border-radius:var(--rad);padding:9px 11px}
.num b{font-family:"IBM Plex Mono";font-weight:500;font-size:19px;display:block}
.num span{font-size:11.5px;color:#a89e8a}
.bar{height:6px;background:#372d1d;border-radius:99px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--acc);width:0%}
.prog-txt{font-size:12px;color:#a89e8a;margin-top:6px}
.fbtn{display:flex;justify-content:space-between;align-items:center;width:100%;text-align:left;background:none;border:0;color:#efe9dc;padding:7px 9px;border-radius:8px;font:500 13.5px Inter;cursor:pointer}
.fbtn:hover{background:var(--ink2)} .fbtn.on{background:var(--acc);color:#fff}
.fbtn .c{font-family:"IBM Plex Mono";font-size:12px;opacity:.75}
.fsec{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:#a89e8a;margin:14px 0 5px}
.side-foot{margin-top:auto;font-size:12px;color:#a89e8a;line-height:1.7}
.dot{display:inline-block;width:7px;height:7px;border-radius:99px;background:#3ecf6f;margin-right:6px}
/* ---------- queue ---------- */
.queue{display:flex;flex-direction:column;border-right:1px solid var(--line);background:var(--paper);min-height:0}
.qhead{padding:14px 14px 10px;border-bottom:1px solid var(--line)}
.qhead h2{font-family:"Space Grotesk";font-size:16px;margin:0 0 8px}
.search{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--surface);font:400 13.5px Inter}
.search:focus{outline:2px solid var(--acc);outline-offset:-1px}
.qcount{font-size:12px;color:var(--mut);margin-top:7px}
.list{overflow:auto;flex:1;padding:10px;display:flex;flex-direction:column;gap:8px}
.row{display:grid;grid-template-columns:96px 1fr;gap:11px;padding:9px;border:1px solid var(--line);border-radius:12px;cursor:pointer;background:var(--surface)}
.row:hover{border-color:#d8d0bf}.row.sel{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
.row .thumb{width:96px;height:72px;object-fit:cover;border-radius:8px;background:#ece7da;display:block}
.row .thumb.ph{display:flex;align-items:center;justify-content:center;color:#b3a88f;font-size:19px;background:#f0ebdf}
.row video{width:96px;height:72px;object-fit:cover;border-radius:8px;background:#000}
.rname{font-weight:600;font-size:13px;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.rmeta{font-size:11.5px;color:var(--mut);margin-top:3px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.ryt{font-size:12px;color:#57534a;margin-top:3px;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
.pill{font-size:10.5px;font-weight:600;padding:1.5px 7px;border-radius:99px;letter-spacing:.02em}
.pill.pending{background:var(--warn-soft);color:var(--warn)}
.pill.approved{background:var(--ok-soft);color:var(--ok)}
.pill.rejected{background:var(--bad-soft);color:var(--bad)}
.pill.my{background:var(--ink);color:#ffd9a8}
.pill.id{background:#ece7da;color:#57534a}
/* ---------- detail ---------- */
.detail{overflow:auto;padding:22px 26px;min-height:0}
.detail .empty{max-width:420px;margin:9vh auto;text-align:center;color:var(--mut);line-height:1.7}
.detail .empty b{color:var(--txt);font-family:"Space Grotesk";font-size:17px;display:block;margin-bottom:6px}
.kbd{font-family:"IBM Plex Mono";font-size:11px;background:#ece7da;border:1px solid var(--line);border-bottom-width:2px;border-radius:5px;padding:1px 5px}
.dhead{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.dhead .mono{font-family:"IBM Plex Mono";font-size:12.5px;color:var(--mut)}
h2.dname{font-family:"Space Grotesk";font-size:23px;letter-spacing:-.01em;margin:8px 0 4px;line-height:1.25}
.dsub{color:var(--mut);font-size:13px}
.player{margin:16px 0;display:flex;justify-content:center}
.player video{max-height:56vh;max-width:100%;border-radius:12px;box-shadow:0 10px 34px rgba(20,16,8,.22);background:#000}
.notice{background:var(--warn-soft);border:1px solid #ecd9ae;border-radius:var(--rad);padding:10px 13px;font-size:13px;line-height:1.55;margin:12px 0}
.linkrow{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
.linkbtn{display:inline-block;background:var(--ink);color:#fff;text-decoration:none;padding:8px 13px;border-radius:8px;font-weight:500;font-size:13px}
.linkbtn.ghost{background:var(--surface);color:var(--txt);border:1px solid var(--line)}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-top:18px}
.tab{border:0;background:none;padding:8px 12px;font:600 13px Inter;color:var(--mut);cursor:pointer;border-bottom:2px solid transparent}
.tab.on{color:var(--txt);border-bottom-color:var(--acc)}
.panel{padding:13px 2px;font-size:14px;line-height:1.65;max-width:720px}
.panel p{margin:0 0 10px}
.panel .ttl{font-weight:600;font-size:15px}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.tag{font-size:12px;background:#ece7da;border-radius:99px;padding:2.5px 9px}
.charcount{font-size:11.5px;color:var(--mut);margin-top:8px;font-family:"IBM Plex Mono"}
.actions{position:sticky;bottom:0;background:var(--paper);border-top:1px solid var(--line);padding:13px 0 6px;display:flex;gap:9px;align-items:stretch;max-width:720px}
.abtn{flex:1;padding:12px;border-radius:10px;border:1px solid var(--line);font:600 14px Inter;cursor:pointer;background:var(--surface)}
.abtn small{display:block;font-weight:400;font-size:11px;color:var(--mut);margin-top:1px}
.abtn.ok{background:var(--ok);border-color:var(--ok);color:#fff}.abtn.ok small{color:#cdeeda}
.abtn.rj{color:var(--bad)} .abtn.rj:hover{background:var(--bad-soft)}
.pos{font-family:"IBM Plex Mono";font-size:12px;color:var(--mut);align-self:center;white-space:nowrap}
@media (max-width:1020px){.app{grid-template-columns:212px 330px 1fr}}
@media (max-width:760px){
 .app{grid-template-columns:1fr;height:auto}
 .side{flex-direction:row;flex-wrap:wrap;align-items:center;padding:12px 14px;gap:12px}
 .side .blok.prog,.side nav,.side-foot{display:none}
 .nums{display:flex}.num{padding:5px 9px}.num b{font-size:15px}
 .queue{border-right:0}
 .list{max-height:52vh}
 .detail{padding:16px}
}
</style></head><body>
<div class="app">
 <aside class="side">
  <div class="brand"><div class="mark">Deins<em>·</em>Affiliate</div><div class="sub">Konsol review pipeline konten</div></div>
  <div class="blok"><div class="lbl">Ringkasan</div>
   <div class="nums">
    <div class="num"><b id="s-total">–</b><span>total item</span></div>
    <div class="num"><b id="s-pend">–</b><span>menunggu</span></div>
    <div class="num"><b id="s-ok">–</b><span>disetujui</span></div>
    <div class="num"><b id="s-no">–</b><span>ditolak</span></div>
   </div></div>
  <div class="blok prog"><div class="lbl">Progres review</div>
   <div class="bar"><i id="bar"></i></div><div class="prog-txt" id="bar-txt">–</div></div>
  <nav>
   <div class="fsec">Status review</div>
   <button class="fbtn on" data-k="review" data-v="all">Semua status <span class="c" id="c-all"></span></button>
   <button class="fbtn" data-k="review" data-v="pending">Menunggu <span class="c" id="c-pending"></span></button>
   <button class="fbtn" data-k="review" data-v="approved">Disetujui <span class="c" id="c-approved"></span></button>
   <button class="fbtn" data-k="review" data-v="rejected">Ditolak <span class="c" id="c-rejected"></span></button>
   <div class="fsec">Region</div>
   <button class="fbtn on" data-k="region" data-v="all">Semua region</button>
   <button class="fbtn" data-k="region" data-v="ID">Indonesia</button>
   <button class="fbtn" data-k="region" data-v="MY">Malaysia · perlu remap</button>
  </nav>
  <div class="side-foot"><span class="dot"></span>Ingest Telegram aktif<br>Worker caption jalan tiap jam</div>
 </aside>
 <main class="queue">
  <div class="qhead"><h2>Antrian item</h2>
   <input class="search" id="q" type="search" placeholder="Cari produk atau channel…  ( / )">
   <div class="qcount" id="qcount"></div></div>
  <div class="list" id="list"></div>
 </main>
 <section class="detail" id="detail"></section>
</div>
<script>
let ITEMS=[], SEL=null, F={review:'all',region:'all',q:''}, TAB='youtube';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function api(u,o){const r=await fetch(u,o);return r.json()}
async function stats(){
 const s=await api('/api/stats');
 $('#s-total').textContent=s.total;
 $('#s-pend').textContent=s.by_review.pending||0;
 $('#s-ok').textContent=s.by_review.approved||0;
 $('#s-no').textContent=s.by_review.rejected||0;
 const done=(s.by_review.approved||0)+(s.by_review.rejected||0);
 $('#bar').style.width=(s.total?Math.round(done/s.total*100):0)+'%';
 $('#bar-txt').textContent=done+' dari '+s.total+' item sudah direview';
 $('#c-all').textContent=s.total; $('#c-pending').textContent=s.by_review.pending||0;
 $('#c-approved').textContent=s.by_review.approved||0; $('#c-rejected').textContent=s.by_review.rejected||0;
}
function visible(){return ITEMS}
async function load(){
 const q=new URLSearchParams({review:F.review,region:F.region,q_text:F.q});
 ITEMS=await api('/api/items?'+q);
 $('#qcount').textContent=ITEMS.length+' item cocok dengan filter';
 if(SEL!=null && !ITEMS.find(i=>i.id===SEL)) SEL=null;
 if(SEL==null && ITEMS.length) SEL=ITEMS[0].id;
 renderList(); renderDetail();
}
function renderList(){
 $('#list').innerHTML=ITEMS.map(it=>`
  <div class="row ${it.id===SEL?'sel':''}" data-id="${it.id}" onclick="pick(${it.id})">
   ${it.has_thumb?`<img class="thumb" loading="lazy" src="/thumb/${it.id}" alt="">`:it.has_video?`<video muted preload="metadata" src="/media/${it.id}#t=0.6"></video>`:'<div class="thumb ph">▶</div>'}
   <div><div class="rname">${esc(it.display_name)||'(nama belum terdeteksi)'}</div>
   <div class="rmeta"><span>#${it.id}</span><span>${esc(it.channel)}</span>
   <span class="pill ${it.region==='MY'?'my':'id'}">${it.region||'?'}</span>
   <span class="pill ${it.review}">${it.review}</span></div>
   <div class="ryt">${esc(it.yt_title)}</div></div></div>`).join('')
  || '<p style="padding:16px;color:var(--mut)">Antrian bersih — tidak ada item yang cocok dengan filter ini.</p>';
}
function paras(t){var NL=String.fromCharCode(10);return String(t||'').split(NL+NL).map(function(x){return '<p>'+esc(x).split(NL).join('<br>')+'</p>'}).join('')}
function capText(it){
 const c=it.captions||{};
 if(TAB==='youtube'){const y=c.youtube||{};return '<div class="ttl">'+esc(y.title||'')+'</div>'+paras(y.description||'')}
 const v=c[TAB]||{};return paras(v.text||'(kosong)');
}
function renderDetail(){
 const it=ITEMS.find(i=>i.id===SEL), d=$('#detail');
 if(!it){d.innerHTML='<div class="empty"><b>Belum ada item dipilih</b>Pilih item dari antrian untuk menonton videonya dan membaca caption-nya.<br><br><span class="kbd">↓</span> <span class="kbd">↑</span> berpindah item · <span class="kbd">A</span> setujui · <span class="kbd">X</span> tolak · <span class="kbd">U</span> urungkan</div>';return}
 const idx=ITEMS.indexOf(it), c=it.captions||{};
 const tags=(c.youtube&&c.youtube.tags)||[];
 if(it.status!=='packaged'){
  d.innerHTML='<div class="dhead"><span class="mono">ITEM #'+it.id+'</span>'
  +' <span class="pill '+it.review+'">'+it.review+'</span>'
  +' <span class="pill '+(it.region==='MY'?'my':'id')+'">'+(it.region==='MY'?'Malaysia':'Indonesia')+'</span>'
  +' <span class="mono">'+esc(it.created||'')+'</span></div>'
  +'<h2 class="dname">'+(esc(it.display_name)||'Nama produk belum terdeteksi')+'</h2>'
  +'<div class="dsub">dari channel <b>'+esc(it.channel)+'</b> · status paket: '+esc(it.status)+'</div>'
  +'<div class="notice"><b>Paket belum dibuat.</b> Item ini sudah terunduh dan menunggu giliran caption worker (jalan tiap jam). Thumbnail, video, dan caption akan muncul di sini setelah paketnya jadi — kamu tetap bisa menyetujui atau menolaknya dari sekarang.</div>'
  +(it.region==='MY'?'<div class="notice"><b>Item Malaysia.</b> Link-nya masih menunjuk Shopee MY dan akan menunggu pemetaan ke produk Shopee Indonesia.</div>':'')
  +'<div class="linkrow"><a class="linkbtn" href="'+esc(it.product_url)+'" target="_blank" rel="noopener">Buka produk di Shopee ↗</a></div>'
  +'<div class="actions">'
  +'<button class="abtn rj" data-d="rejected" onclick="rev(this.dataset.d)">Tolak<small>tombol X</small></button>'
  +'<button class="abtn" data-d="pending" onclick="rev(this.dataset.d)">Urungkan<small>tombol U</small></button>'
  +'<span class="pos">'+(idx+1)+' / '+ITEMS.length+'</span>'
  +'<button class="abtn ok" data-d="approved" onclick="rev(this.dataset.d)">Setujui<small>tombol A</small></button>'
  +'</div>';
  d.scrollTop=0; return;
 }
 const poster=it.has_thumb?('/thumb/'+it.id):'';
 d.innerHTML=
  '<div class="dhead"><span class="mono">ITEM #'+it.id+'</span>'
  +' <span class="pill '+it.review+'">'+it.review+'</span>'
  +' <span class="pill '+(it.region==='MY'?'my':'id')+'">'+(it.region==='MY'?'Malaysia':'Indonesia')+'</span>'
  +' <span class="mono">'+esc(it.created||'')+'</span></div>'
  +'<h2 class="dname">'+(esc(it.display_name)||'Nama produk belum terdeteksi')+'</h2>'
  +'<div class="dsub">dari channel <b>'+esc(it.channel)+'</b> · status paket: '+esc(it.status)+'</div>'
  +(it.has_video?'<div class="player"><video controls preload="metadata" poster="'+poster+'" src="/media/'+it.id+'"></video></div>':'')
  +(it.region==='MY'?'<div class="notice"><b>Item Malaysia.</b> Videonya bisa dipakai, tapi nama produk belum diketahui dan link-nya masih menunjuk Shopee MY. Item ini menunggu pemetaan link ke produk Shopee Indonesia sebelum siap posting.</div>':'')
  +'<div class="linkrow"><a class="linkbtn" href="'+esc(it.product_url)+'" target="_blank" rel="noopener">Buka produk di Shopee ↗</a></div>'
  +'<div class="tabs">'+['youtube','threads','facebook','shopee'].map(function(t){return '<button class="tab '+(TAB===t?'on':'')+'" data-t="'+t+'" onclick="setTab(this.dataset.t)">'+t[0].toUpperCase()+t.slice(1)+'</button>'}).join('')+'</div>'
  +'<div class="panel">'+capText(it)
  +(TAB==='youtube'&&tags.length?'<div class="tags">'+tags.map(function(t){return '<span class="tag">'+esc(t)+'</span>'}).join('')+'</div>':'')
  +'<div class="charcount">'+(TAB==='youtube'?((c.youtube||{}).description||'').length:((c[TAB]||{}).text||'').length)+' karakter</div></div>'
  +'<div class="actions">'
  +'<button class="abtn rj" data-d="rejected" onclick="rev(this.dataset.d)">Tolak<small>tombol X</small></button>'
  +'<button class="abtn" data-d="pending" onclick="rev(this.dataset.d)">Urungkan<small>tombol U</small></button>'
  +'<span class="pos">'+(idx+1)+' / '+ITEMS.length+'</span>'
  +'<button class="abtn ok" data-d="approved" onclick="rev(this.dataset.d)">Setujui<small>tombol A — lanjut ke item berikutnya</small></button>'
  +'</div>';
 d.scrollTop=0;
}
function pick(id){SEL=id;renderList();renderDetail()}
function setTab(t){TAB=t;renderDetail()}
async function rev(decision){
 const it=ITEMS.find(i=>i.id===SEL); if(!it)return;
 const idx=ITEMS.indexOf(it);
 await fetch('/api/items/'+it.id+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision})});
 it.review=decision; stats();
 if(decision!=='pending'){
   const nxt=ITEMS.slice(idx+1).find(i=>i.review==='pending')||ITEMS[idx+1];
   if(F.review==='all'&&nxt) SEL=nxt.id;
 }
 if(F.review!=='all'){await load()} else {renderList();renderDetail()}
}
document.querySelectorAll('.fbtn').forEach(b=>b.addEventListener('click',()=>{
 document.querySelectorAll(`.fbtn[data-k="${b.dataset.k}"]`).forEach(x=>x.classList.remove('on'));
 b.classList.add('on'); F[b.dataset.k]=b.dataset.v; load();
}));
let qt; $('#q').addEventListener('input',e=>{clearTimeout(qt);qt=setTimeout(()=>{F.q=e.target.value;load()},220)});
document.addEventListener('keydown',e=>{
 if(e.target.tagName==='INPUT')return;
 const idx=ITEMS.findIndex(i=>i.id===SEL);
 if(e.key==='ArrowDown'||e.key==='j'){e.preventDefault();if(ITEMS[idx+1])pick(ITEMS[idx+1].id)}
 else if(e.key==='ArrowUp'||e.key==='k'){e.preventDefault();if(ITEMS[idx-1])pick(ITEMS[idx-1].id)}
 else if(e.key==='a'||e.key==='A')rev('approved');
 else if(e.key==='x'||e.key==='X')rev('rejected');
 else if(e.key==='u'||e.key==='U')rev('pending');
 else if(e.key==='/'){e.preventDefault();$('#q').focus()}
});
stats(); load();
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
