"""Service entrypoint: Telegram ingest (backfill + live listener).
Caption/packaging run as a separate worker step (src.worker) so ingest
never blocks on the LLM; publishers join once platform accounts connect.
"""
import asyncio

from .config import Settings
from .telegram_ingest import run_ingest

DB = "storage/pipeline.db"


async def main() -> None:
    settings = Settings()
    await run_ingest(settings, DB)


if __name__ == "__main__":
    asyncio.run(main())
