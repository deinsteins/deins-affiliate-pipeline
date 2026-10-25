"""One-time Google OAuth for YouTube uploads -> storage/youtube-token.json

The VM has no user-facing browser for Google's consent screen, so the
flow is split in two steps (run on the server, approve on your phone):

  1. python -m scripts.youtube_auth --url
     Prints an authorization URL. Open it on your own device, sign in
     to the YouTube channel's Google account, approve, and copy the
     authorization code Google shows you.
  2. python -m scripts.youtube_auth --code <CODE>
     Exchanges the code for tokens, saves them to
     storage/youtube-token.json, and verifies the channel
     (prints the channel title it will upload to).

Prerequisites (one-time, in Google Cloud Console):
  - A project with the YouTube Data API v3 enabled.
  - OAuth consent screen (External, app in Testing is fine) with scope
    https://www.googleapis.com/auth/youtube.upload added.
  - An OAuth client ID of type "Desktop app"; its JSON goes to
    storage/youtube-client-secrets.json (never committed — gitignored).

Caveat: while the consent-screen app is in Testing (unverified),
uploads land as PRIVATE and the daily quota is ~6 uploads/day
(1 upload ~= 1600 of 10,000 units). Google verification lifts both.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "storage" / "youtube-client-secrets.json"
TOKEN = ROOT / "storage" / "youtube-token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]


def _flow():
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not SECRETS.exists():
        raise SystemExit(
            f"client secrets tidak ada: {SECRETS}\n"
            "Download JSON OAuth client (Desktop app) dari Google Cloud "
            "Console dan simpan ke path itu.")
    return InstalledAppFlow.from_client_secrets_file(str(SECRETS), SCOPES)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="store_true",
                    help="cetak authorization URL untuk dibuka di device kamu")
    ap.add_argument("--code", default="",
                    help="kode otorisasi dari Google untuk ditukar token")
    ap.add_argument("--local", action="store_true",
                    help="flow lokal (butuh browser di mesin ini)")
    args = ap.parse_args()
    flow = _flow()
    if args.local:
        creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json())
        print(f"token tersimpan: {TOKEN}")
        return 0
    if args.url:
        url, _ = flow.authorization_url(prompt="consent",
                                        access_type="offline")
        print("Buka URL ini di device kamu, approve, lalu salin kodenya:\n")
        print(url)
        print("\nLalu jalankan: python -m scripts.youtube_auth --code <KODE>")
        return 0
    if args.code:
        flow.fetch_token(code=args.code)
        creds = flow.credentials
        TOKEN.write_text(creds.to_json())
        print(f"token tersimpan: {TOKEN}")
        # Verify: which channel will uploads go to?
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", credentials=creds)
        res = yt.channels().list(part="snippet", mine=True).execute()
        items = res.get("items", [])
        if items:
            print("channel terverifikasi:", items[0]["snippet"]["title"])
        else:
            print("PERINGATAN: akun ini belum punya channel YouTube — "
                  "buat channel dulu sebelum upload.")
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
