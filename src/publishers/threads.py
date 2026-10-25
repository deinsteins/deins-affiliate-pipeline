"""Threads API: create a video media container, poll processing,
then publish. Link goes in the post text (and optionally first reply).
Link: public_link(item, PUBLIC_BASE_URL) — the trackable shortlink.
"""
import httpx

THREADS = "https://graph.threads.net/v1.0"


async def publish_video(package_dir, caption: dict, user_id: str, token: str) -> str:
    """Two-step container -> publish; return the post URL."""
    # TODO: POST /{user_id}/threads (media_type=VIDEO, video_url public host)
    #       NOTE: Threads API needs a publicly reachable video_url —
    #       serve storage/ready via a temporary public link or Meta upload.
    ...
