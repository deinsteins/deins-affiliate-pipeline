"""Meta Graph API: publish the video to the owner's Facebook Page
(resumable video upload / Reels endpoint). Page token required —
personal profiles cannot publish via API.
Caption link: public_link(item, PUBLIC_BASE_URL) — the trackable
shortlink (see src/analytics.py), never the raw affiliate URL.
"""
import httpx

GRAPH = "https://graph.facebook.com/v21.0"


async def publish_reel(package_dir, caption: dict, page_id: str, token: str) -> str:
    """Upload + publish; return the permalink URL."""
    # TODO: POST /{page_id}/videos (upload) or Reels 3-step flow
    #       (start -> upload -> finish with description incl. link)
    ...
