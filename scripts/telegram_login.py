"""Two-phase Telegram login (run from the project root):
  TG_PHONE=+62... python -m scripts.telegram_login send     -> sends OTP
  python -m scripts.telegram_login verify <code>             -> finishes login
  python -m scripts.telegram_login verify-pw <password>     -> if 2FA is on
The session lands in storage/telegram.session and is reused forever after.
"""
import asyncio, json, os, sys
from urllib.parse import urlparse

sys.path.insert(0, ".")
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from src.config import Settings

PENDING = "storage/.login-pending.json"


def proxy_from_env():
    raw = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not raw:
        return None
    from python_socks import ProxyType
    u = urlparse(raw)
    return (ProxyType.HTTP, u.hostname, u.port, True, u.username, u.password)


def make_client(s: Settings) -> TelegramClient:
    return TelegramClient(s.telegram_session, s.telegram_api_id,
                          s.telegram_api_hash, proxy=proxy_from_env())


async def phase_send() -> None:
    s = Settings()
    client = make_client(s)
    await client.connect()
    phone = os.environ["TG_PHONE"]
    sent = await client.send_code_request(phone)
    json.dump({"phone": phone, "hash": sent.phone_code_hash}, open(PENDING, "w"))
    print("CODE_SENT")
    await client.disconnect()


async def phase_verify(code: str) -> None:
    s = Settings()
    client = make_client(s)
    await client.connect()
    p = json.load(open(PENDING))
    try:
        await client.sign_in(p["phone"], code, phone_code_hash=p["hash"])
    except SessionPasswordNeededError:
        print("NEED_2FA_PASSWORD")
        await client.disconnect()
        return
    me = await client.get_me()
    print("LOGGED_IN:", me.username or me.first_name, "| id:", me.id)
    await client.disconnect()


async def phase_verify_pw(password: str) -> None:
    s = Settings()
    client = make_client(s)
    await client.connect()
    await client.sign_in(password=password)
    me = await client.get_me()
    print("LOGGED_IN:", me.username or me.first_name, "| id:", me.id)
    await client.disconnect()


if __name__ == "__main__":
    phase = sys.argv[1]
    if phase == "send":
        asyncio.run(phase_send())
    elif phase == "verify":
        asyncio.run(phase_verify(sys.argv[2]))
    elif phase == "verify-pw":
        asyncio.run(phase_verify_pw(sys.argv[2]))
