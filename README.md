# Deins Affiliate Pipeline

Automation for a Shopee-affiliate content workflow:

**Telegram channels → download product videos → AI captions per platform →
auto-post to YouTube Shorts, Facebook Page Reels and Threads → ready-to-post
package for Shopee Video (manual final tap in the Shopee app).**

Shopee Video has no official upload API, so that last step stays manual by
design — everything before it is automated. YouTube, Facebook and Threads are
posted through their **official APIs**.

## Flow

```
[Telegram channels]
      │  Telethon listener (user account)
      ▼
[Ingest] dedupe by file hash + message id, save video + source post text
      ▼
[Link tools] extract Shopee URL from post text, resolve short links
             → canonical product URL (shop id / item id)
      ▼
[Caption AI] 9Router (deepseek-chat) writes a fresh caption per platform:
             YouTube title + description + tags · Threads post · FB caption
             (never a copy-paste of the source caption — avoids duplicate
             content detection and reads as original)
      ▼
[Packager] storage/ready/<slug>/  → video.mp4 · captions.json · links.txt
      ▼
[Publishers] per-platform status tracked in SQLite, retry with backoff
      ├─ YouTube Data API v3      → Shorts (affiliate link in description)
      ├─ Meta Graph API           → Facebook Page Reels (link in caption)
      ├─ Threads API              → video post (link in post / first reply)
      └─ Shopee Video             → package only; owner posts in-app (~1 min)
      ▼
[Notifier] Telegram bot message to the owner for every published/failed item
```

Item lifecycle in SQLite: `discovered → downloaded → captioned → packaged →
posted:<platform> / failed:<platform> (retry) → done`.

## Tech stack

| Layer           | Choice                                   | Why |
| --------------- | ---------------------------------------- | --- |
| Language        | Python 3.11+                             | Telethon + Google/Meta client ecosystem |
| Telegram ingest | Telethon (MTProto user client)           | Bot API cannot read arbitrary channels; a user session can |
| AI captions     | OpenAI-compatible client → own 9Router (`deepseek-chat`) | Already deployed; cheap Indonesian copywriting |
| Database        | SQLite (stdlib)                          | Queue, dedupe, per-platform status — zero extra infra |
| YouTube         | `google-api-python-client` + OAuth2      | Official Data API v3 upload |
| Facebook        | Meta Graph API via `httpx`               | Page video/Reels publishing endpoints |
| Threads         | Threads API via `httpx`                  | Official container → publish flow |
| HTTP            | `httpx`                                  | Proxy-aware; the sandbox requires an egress proxy |
| Config          | `.env` (secrets) + `config/channels.yaml` | Secrets never enter git |
| Runtime         | systemd service + restore script         | Matches the rest of this server's projects |

## Repository layout

```
config/channels.yaml     channels to watch, platform toggles, caption style
src/
  main.py                service entrypoint (ingest loop + scheduler)
  config.py              settings from .env / yaml
  db.py                  SQLite schema + item state machine
  telegram_ingest.py     Telethon listener, downloader, dedupe
  link_tools.py          Shopee URL extraction + short-link resolution
  caption_ai.py          per-platform caption/hashtag generation (9Router)
  packager.py            builds storage/ready/<slug>/ packages
  publishers/
    youtube.py           Data API v3 upload (quota-aware)
    facebook.py          Graph API Page Reels/video upload
    threads.py           Threads API video publishing
  notifier.py            Telegram Bot notifications to the owner
  scheduler.py           retry/backoff + quota-aware posting loop
scripts/
  telegram_login.py      one-time interactive Telegram login → session file
  youtube_auth.py        one-time Google OAuth → token file
storage/                 downloads/ · ready/ · posted/ (git-ignored content)
systemd/                 service unit template
```

## Setup checklist

1. `cp .env.example .env` and fill in secrets (see the file for where each
   value comes from).
2. Telegram: create an app at <https://my.telegram.org> → `TELEGRAM_API_ID` /
   `TELEGRAM_API_HASH`, list channels in `config/channels.yaml`, then run
   `scripts/telegram_login.py` once (phone + OTP) to create the session.
3. YouTube: Google Cloud project → enable YouTube Data API v3 → OAuth client
   → run `scripts/youtube_auth.py` once. Note: uploads from an unverified API
   project are locked to *private* until Google's compliance audit passes;
   default quota ≈ 6 uploads/day.
4. Facebook: a Facebook **Page** + Meta app → Page access token.
5. Threads: Threads account connected to the Meta app → user access token.
6. Shopee affiliate links: v1 keeps the canonical product URL in `links.txt`
   alongside the package; generating personal affiliate short links happens
   in the Shopee Affiliate portal (automating that portal is a possible v2).

## Honest scope notes

- Source videos belong to sellers/creators and are shared by the channels for
  reposting; captions are always rewritten by AI, never copied.
- Platforms' reused-content rules mainly affect *monetisation*; this pipeline
  is built as an affiliate-traffic engine (links in descriptions/posts).
