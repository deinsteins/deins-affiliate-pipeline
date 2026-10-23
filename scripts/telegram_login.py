"""One-time interactive Telegram login: phone number + OTP ->
creates the session file used by telegram_ingest. Run manually:
  python -m scripts.telegram_login
"""
from telethon import TelegramClient
import sys
sys.path.insert(0, ".")
from src.config import Settings

if __name__ == "__main__":
    s = Settings()
    with TelegramClient(s.telegram_session, s.telegram_api_id, s.telegram_api_hash) as c:
        print("Logged in as:", c.get_me().username)
