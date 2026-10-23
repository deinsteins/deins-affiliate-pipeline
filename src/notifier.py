"""Owner notifications via a Telegram bot (BotFather token):
new package ready, per-platform publish success/failure, daily digest.
"""
import httpx


async def notify(bot_token: str, chat_id: str, text: str) -> None:
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                     json={"chat_id": chat_id, "text": text})
