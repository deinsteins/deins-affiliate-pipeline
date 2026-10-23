"""One-time Google OAuth for YouTube uploads -> storage/youtube-token.json
Run manually in a browser-capable environment:
  python -m scripts.youtube_auth
"""
# TODO: InstalledAppFlow.from_client_secrets_file(...).run_local_server()
#       scopes: youtube.upload (+ youtube.readonly for channel check)
