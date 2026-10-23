"""SQLite item store + lifecycle state machine.

Item: one product video discovered in a Telegram channel.
Status: discovered -> downloaded -> captioned -> packaged -> done
Per-platform post results live in `posts` (pending/posted/failed + url).
"""
import sqlite3, hashlib
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  channel TEXT, message_id INTEGER,
  file_hash TEXT UNIQUE,            -- dedupe across channels/reposts
  video_path TEXT, source_text TEXT,
  product_url TEXT,                 -- canonical shopee.co.id product URL
  slug TEXT, status TEXT DEFAULT 'discovered',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS posts (
  item_id INTEGER, platform TEXT,   -- youtube | facebook | threads | shopee
  status TEXT DEFAULT 'pending',    -- pending | posted | failed
  remote_url TEXT, error TEXT,
  attempts INTEGER DEFAULT 0,
  PRIMARY KEY (item_id, platform)
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
