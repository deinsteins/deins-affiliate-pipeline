"""Posting loop: pick packaged items, publish per enabled platform,
record results in db.posts, retry failures with exponential backoff,
respect the YouTube daily quota counter. Shopee rows are created as
'package_only' and never auto-posted (no official API exists).
"""

BACKOFF_MIN = [5, 30, 120, 720]  # minutes per attempt


async def run_scheduler(settings, db_path: str) -> None:
    # TODO: loop over pending posts -> dispatch to publishers -> update db
    ...
