"""Service entrypoint: run ingest + scheduler concurrently."""
import asyncio

from .config import Settings
from .telegram_ingest import run_ingest
from .scheduler import run_scheduler

DB = "storage/pipeline.db"


async def main() -> None:
    settings = Settings()
    await asyncio.gather(run_ingest(settings, DB), run_scheduler(settings, DB))


if __name__ == "__main__":
    asyncio.run(main())
