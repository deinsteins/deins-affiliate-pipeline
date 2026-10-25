"""SQLite item store + lifecycle state machine.

Item: one product video discovered in a Telegram channel.
Status: discovered -> downloaded -> captioned -> packaged -> done
Per-platform post results live in `posts`.
"""
import hashlib
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  channel TEXT, message_id INTEGER,
  file_hash TEXT UNIQUE,
  video_path TEXT, source_text TEXT,
  product_url TEXT, product_name TEXT,
  region TEXT, shop_id TEXT, item_id TEXT,
  slug TEXT, status TEXT DEFAULT 'discovered',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS posts (
  item_id INTEGER, platform TEXT,
  status TEXT DEFAULT 'pending',
  remote_url TEXT, error TEXT,
  attempts INTEGER DEFAULT 0,
  PRIMARY KEY (item_id, platform)
);
CREATE TABLE IF NOT EXISTS clicks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER, ts TEXT,
  referer TEXT, device TEXT
);
CREATE TABLE IF NOT EXISTS platform_stats (
  item_id INTEGER, platform TEXT,
  post_id TEXT, post_url TEXT,
  views INTEGER DEFAULT 0, likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0, shares INTEGER DEFAULT 0,
  fetched_at TEXT,
  PRIMARY KEY (item_id, platform)
);
"""


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(items)")]
    if "name_source" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN name_source TEXT")
        conn.commit()
    if "affiliate_url" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN affiliate_url TEXT")
        conn.execute("ALTER TABLE items ADD COLUMN affiliate_source TEXT")
        conn.commit()
    if "review" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN review TEXT "
                     "DEFAULT 'pending'")
        conn.commit()
    if "category" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN category TEXT")
        conn.commit()
    return conn


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def insert_item(conn, **fields) -> int | None:
    """Insert an item; return its id, or None when the hash is a dupe."""
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    try:
        cur = conn.execute(f"INSERT INTO items ({cols}) VALUES ({marks})",
                           tuple(fields.values()))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def items_by_status(conn, status: str):
    return conn.execute("SELECT * FROM items WHERE status = ? ORDER BY id",
                        (status,)).fetchall()
