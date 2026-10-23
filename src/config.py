"""Settings loader: secrets from .env, behaviour from config/channels.yaml."""
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
