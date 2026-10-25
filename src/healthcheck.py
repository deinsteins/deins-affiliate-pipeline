"""Periodic healthcheck: probe the router, evaluate worker/ingest
staleness, and send a Telegram alarm ONLY on state transitions
(down -> alert, down -> ok = recovery note). A single failed probe
marks the router "degraded" without alerting; two in a row = down.

Runs as a systemd timer (every 10 min). State: storage/health.json.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import health as H  # noqa: E402
from src.config import Settings  # noqa: E402
from src.notifier import send_telegram  # noqa: E402


def alert(settings: Settings, text: str) -> None:
    ok, detail = send_telegram(settings.notify_bot_token,
                               settings.notify_chat_id, text)
    print(f"[healthcheck] alarm -> telegram: ok={ok} ({detail})", flush=True)
    if not ok:
        print("[healthcheck] ALARM TIDAK TERKIRIM (cek token/chat id):",
              text, flush=True)


def main() -> int:
    settings = Settings()
    prev = H.read_health()
    prev_states = prev.get("states", {})

    # --- router: live probe ---
    ok, detail = H.check_router(settings)
    fails = 0 if ok else prev.get("router_fails_in_a_row", 0) + 1
    router_state = H.router_status(ok, H.now_ts(), fails)
    # --- worker: heartbeat staleness ---
    worker_state = H.worker_status(prev.get("worker_last_finish"))
    # --- ingest: service alive? ---
    ingest_state = ("ok" if H.service_active("affiliate-pipeline.service")
                    else "down")

    states = {"router": router_state, "worker": worker_state,
              "ingest": ingest_state}
    H.write_health(states=states, router_last_probe=H.now_ts(),
                   router_ok=ok, router_detail=detail,
                   router_fails_in_a_row=fails)

    labels = {"router": "Router (LLM caption)", "worker": "Worker caption",
              "ingest": "Ingest Telegram"}
    for comp, state in states.items():
        old = prev_states.get(comp)
        if state == "down" and old != "down":
            alert(settings,
                  f"🚨 Deins Affiliate: {labels[comp]} DOWN.\n"
                  f"Detail: {detail if comp == 'router' else state}\n"
                  f"Cek dashboard untuk status terbaru.")
        elif state == "ok" and old == "down":
            alert(settings,
                  f"✅ Deins Affiliate: {labels[comp]} pulih kembali.")
    print(f"[healthcheck] states={states} router_detail={detail}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
