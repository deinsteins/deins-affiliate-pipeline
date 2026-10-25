"""YouTube Data API v3 upload (Shorts: vertical video, title <= 100 chars).

Quota: an upload costs ~1600 units of the default 10,000/day.
Unverified API projects upload as PRIVATE until Google's compliance
audit passes — surface that state instead of pretending it's public.

Link hygiene (important): captions generated earlier embed the
CHANNEL SHARER's product link in the YouTube description. The uploader
replaces every shopee URL in the description with the owner's
trackable shortlink (public_link), and appends it when no link is
present — otherwise clicks bypass measurement AND commissions leak
to the sharer.
"""

import re
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

ROOT = Path(__file__).resolve().parent.parent.parent
TOKEN = ROOT / "storage" / "youtube-token.json"


class QuotaExceeded(Exception):
    """YouTube daily quota hit — scheduler must back off, not retry now."""


class CredentialsError(Exception):
    """Token missing/invalid — re-run scripts/youtube_auth.py."""


def load_service(token_path: Path = TOKEN):
    if not token_path.exists():
        raise CredentialsError(
            f"token YouTube tidak ada: {token_path} — "
            "jalankan scripts/youtube_auth.py dulu.")
    creds = Credentials.from_authorized_user_file(str(token_path))
    return build("youtube", "v3", credentials=creds)


def build_description(caption: dict, shortlink: str) -> str:
    """Caption description with the sharer's link swapped for ours."""
    desc = (caption.get("description") or "").strip()
    desc = re.sub(r"https?://[^\s]+", shortlink, desc)
    if shortlink not in desc:
        desc = (desc + f"\n\nLink produk: {shortlink}").strip()
    return desc


def build_body(caption: dict, shortlink: str, privacy: str) -> dict:
    title = (caption.get("title") or "Produk pilihan")[:100]
    tags = list(caption.get("tags") or [])
    # YouTube caps tags at 500 chars total.
    total, kept = 0, []
    for t in tags:
        if total + len(t) + 1 > 500:
            break
        kept.append(t)
        total += len(t) + 1
    return {
        "snippet": {
            "title": title,
            "description": build_description(caption, shortlink),
            "tags": kept,
            "categoryId": "26",  # Howto & Style — closest fit for product demos
        },
        "status": {"privacyStatus": privacy},
    }


def upload_short(package_dir, caption: dict, shortlink: str,
                 privacy: str = "private") -> str:
    """Upload video.mp4 from the package; return the Shorts URL.

    Default privacy is private: the first real upload should be
    inspected before anything goes public, and unverified projects
    are forced private by YouTube anyway.
    """
    package_dir = Path(package_dir)
    video = package_dir / "video.mp4"
    if not video.exists():
        raise FileNotFoundError(f"video tidak ada: {video}")
    service = load_service()
    body = build_body(caption, shortlink, privacy)
    media = MediaFileUpload(str(video), chunksize=1024 * 1024,
                            resumable=True, mimetype="video/mp4")
    try:
        request = service.videos().insert(
            part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()
    except HttpError as e:
        detail = ""
        try:
            detail = e.error_details[0].get("reason", "")  # type: ignore
        except Exception:
            detail = str(e)
        if "quotaExceeded" in detail or "quota" in str(e).lower():
            raise QuotaExceeded(
                "kuota harian YouTube habis — coba lagi besok") from e
        if e.resp.status in (401, 403):
            raise CredentialsError(
                f"token ditolak YouTube ({e.resp.status}) — "
                "jalankan ulang scripts/youtube_auth.py") from e
        raise
    video_id = response["id"]
    return f"https://youtube.com/shorts/{video_id}"
