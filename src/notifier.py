"""Owner notifications via a Telegram bot (BotFather token).

Delivery is best-effort and never raises: every sender returns
(ok, detail) so a dead token or missing chat id degrades to a log
line instead of crashing the caller. (Lesson 2026-10-25: the stored
bot token had died with a 404 — alerts must surface that state
instead of silently failing.)
"""

import httpx


def send_telegram(bot_token: str, chat_id: str, text: str,
                  timeout: float = 20.0) -> tuple[bool, str]:
    """Send one Telegram message. Returns (ok, detail)."""
    if not bot_token or not chat_id:
        return False, "not configured (token/chat id kosong)"
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text}, timeout=timeout)
        d = r.json()
        if d.get("ok"):
            return True, "sent"
        return False, f"Telegram API: {d.get('description', '?')}"[:140]
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


async def notify(bot_token: str, chat_id: str, text: str):
    """Async wrapper kept for older call sites."""
    import asyncio
    return await asyncio.to_thread(send_telegram, bot_token, chat_id, text)
