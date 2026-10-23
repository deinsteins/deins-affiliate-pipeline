"""Settings loader: secrets from .env, behaviour from config/channels.yaml."""

import os as _os
# The sandbox exports a no_proxy list with bracketed IPv6 entries ([::1])
# that crash httpx/urllib proxy parsing — sanitise before anything else.
_os.environ["no_proxy"] = "localhost,127.0.0.1"
_os.environ["NO_PROXY"] = "localhost,127.0.0.1"
from pathlib import Path
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session: str = "storage/telegram.session"
    router_base_url: str = ""
    router_api_key: str = ""
    router_model: str = "deepseek-chat"
    youtube_client_secret_file: str = "credentials-youtube.json"
    youtube_token_file: str = "storage/youtube-token.json"
    fb_page_id: str = ""
    fb_page_access_token: str = ""
    threads_user_id: str = ""
    threads_access_token: str = ""
    notify_bot_token: str = ""
    notify_chat_id: str = ""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")


def load_channels() -> dict:
    with open(ROOT / "config" / "channels.yaml") as f:
        return yaml.safe_load(f)


import os
from urllib.parse import urlparse


def proxy_from_env():
    """Telethon/httpx proxy tuple from the sandbox egress proxy env."""
    raw = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not raw:
        return None
    from python_socks import ProxyType
    u = urlparse(raw)
    return (ProxyType.HTTP, u.hostname, u.port, True, u.username, u.password)


def make_client(settings: "Settings") -> "TelegramClient":
    from telethon import TelegramClient
    return TelegramClient(settings.telegram_session, settings.telegram_api_id,
                          settings.telegram_api_hash, proxy=proxy_from_env())
