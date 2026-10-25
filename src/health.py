"""Health signals for the affiliate pipeline.

Three components, each with its own honest signal:
- worker: heartbeat timestamps written by src.worker on every run.
  Stale = the timer died (as it did across VM replacements) or runs
  keep failing. Threshold 45 min: the timer fires every 20 min, so
  two missed runs + slack.
- router: a LIVE probe, never a TCP connect alone. Lesson 2026-10-25:
  the router accepted TCP yet returned empty HTTP replies, and a
  "reachable" verdict from a socket test was wrong. The probe is a
  real 1-token chat completion through the same OpenAI client the
  worker uses.
- ingest: the systemd service state + last item timestamp. Item
  staleness alone never raises an alarm (channels post in bursts and
  can go quiet); a dead service does.

State lives in storage/health.json. Pure helpers (worker_status,
router_status) take explicit timestamps so they are unit-testable
without touching disk.
"""

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEALTH_FILE = ROOT / "storage" / "health.json"
WORKER_STALE_SECS = 45 * 60


def now_ts() -> int:
    return int(time.time())


def read_health() -> dict:
    try:
        return json.loads(HEALTH_FILE.read_text())
    except Exception:
        return {}


def write_health(**fields) -> dict:
    data = read_health()
    data.update(fields)
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(data, indent=2))
    return data


def service_active(name: str) -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", name],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "active"
    except Exception:
        return False


def worker_status(last_finish: int | None, now: int | None = None) -> str:
    """ok / down / never — pure function of the heartbeat age."""
    if not last_finish:
        return "never"
    now = now if now is not None else now_ts()
    return "ok" if now - last_finish <= WORKER_STALE_SECS else "down"


def router_status(last_probe_ok: bool | None, last_probe_at: int | None,
                  fails_in_a_row: int, now: int | None = None) -> str:
    """ok until two consecutive probe failures (one blip != an alarm)."""
    if last_probe_at is None:
        return "never"
    if last_probe_ok:
        return "ok"
    return "down" if fails_in_a_row >= 2 else "degraded"


def check_router(settings, timeout: float = 30.0) -> tuple[bool, str]:
    """Definitive probe: a real 1-token completion via the worker's path."""
    try:
        from openai import OpenAI
        cl = OpenAI(api_key=settings.router_api_key,
                    base_url=settings.router_base_url, timeout=timeout)
        cl.chat.completions.create(
            model=settings.router_model,
            messages=[{"role": "user", "content": "jawab: ok"}],
            max_tokens=1)
        return True, "probe ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:140]}"


def bulk_review(conn, decision: str, ids: list[int] | None = None,
                filt: dict | None = None) -> int:
    """Set review for many items at once. Returns the updated count.

    Either an explicit id list (cap 500) or the same filter the
    dashboard list endpoint uses (review/region/q_text)."""
    if decision not in ("approved", "rejected", "pending"):
        raise ValueError("decision tidak valid")
    if ids:
        ids = [int(i) for i in ids][:500]
        q = (f"UPDATE items SET review = ? WHERE id IN "
             f"({','.join('?' * len(ids))})")
        cur = conn.execute(q, [decision, *ids])
    else:
        filt = filt or {}
        q = ("UPDATE items SET review = ? WHERE status IN "
             "('packaged','downloaded')")
        args: list = [decision]
        if filt.get("review") and filt["review"] != "all":
            q += " AND review = ?"
            args.append(filt["review"])
        if filt.get("region") and filt["region"] != "all":
            q += " AND region = ?"
            args.append(filt["region"])
        if filt.get("q_text"):
            q += " AND (product_name LIKE ? OR channel LIKE ?)"
            args += [f"%{filt['q_text']}%", f"%{filt['q_text']}%"]
        cur = conn.execute(q, args)
    conn.commit()
    return cur.rowcount
