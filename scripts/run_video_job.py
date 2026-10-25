"""Run one video job synchronously (CLI alternative to the dashboard button).

Usage: python -m scripts.run_video_job <job_id>
Prints the final status + error (if any). Long-running: Veo clips take
minutes; prefer running this under nohup for real jobs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import db as dbmod  # noqa: E402
from src import video_gen as vg  # noqa: E402
from src.config import Settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m scripts.run_video_job <job_id>")
        return 2
    conn = dbmod.connect(ROOT / "storage" / "pipeline.db")
    job = vg.run_job(conn, Settings(), int(sys.argv[1]))
    print(f"job {job['id']}: {job['status']}"
          + (f" — {job['error']}" if job.get("error") else "")
          + (f" — paket item #{job['package_item_id']}"
             if job.get("package_item_id") else ""))
    return 0 if job["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
