"""YouTube Data API v3 upload (Shorts: vertical video, title <= 100 chars).

Quota: an upload costs ~1600 units of the default 10,000/day.
Unverified API projects upload as PRIVATE until Google's compliance
audit passes — surface that state instead of pretending it's public.
"""
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def upload_short(package_dir, caption: dict, privacy: str = "public") -> str:
    """Upload video.mp4 from the package; return the YouTube video URL."""
    # TODO: credentials from storage/youtube-token.json (scripts/youtube_auth.py)
    #       body: snippet{title, description, tags}, status{privacyStatus}
    #       description gets the affiliate/product link + hashtags
    ...
