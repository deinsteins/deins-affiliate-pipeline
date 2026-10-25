"""Google Flow web backend: spend the owner's Pro subscription credits.

How it differs from the Veo API backend: Flow has no public API, so
clips are produced by driving the Flow web app (labs.google/fx/tools/
flow, redirects to flow.google.com) in the server browser. That makes
this backend asynchronous in a different way:

  1. run_job() writes a worklist (scene prompts) and parks the job at
     status 'queued_flow' — it does NOT block waiting for the browser.
  2. The agent (or a future cron) picks the worklist up and runs a
     browser task with build_browser_assignment(): check login first,
     then one text-to-video generation per scene (model = flow_model,
     portrait 9:16), downloading each clip.
  3. collect_flow_clips() verifies all 4 scene clips, records the
     estimated credits spent, and continues the job (assemble ->
     package -> done) via continue_flow_job().

Prerequisites (one-time, by the owner):
  - Google account logged in to the server browser (Flow shows the
    account, not a login wall). Without it the browser task reports
    LOGIN_NEEDED and nothing is generated or spent.
  - Enough Flow credits: fast = 20/clip, lite = 10, quality = 100.
    A 4-scene video costs 80 (fast) / 40 (lite) / 400 (quality).
    Credit use is estimated from the model, not read from Flow's UI,
    and tracked per calendar month against flow_credits_budget
    (default 1000 = Google AI Pro).

Hard rules for the browser task: never log in on the owner's behalf,
never solve a captcha, never generate more than the 4 listed scenes,
and stop (don't spend) if Flow reports insufficient credits.
"""

import json
from pathlib import Path

FLOW_URL = "https://labs.google/fx/tools/flow"
CREDITS_PER_CLIP = {"lite": 10, "fast": 20, "quality": 100}

ROOT = Path(__file__).resolve().parent.parent


def workdir(job_id: int) -> Path:
    d = ROOT / "storage" / "video_jobs" / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_worklist(job: dict, script: dict) -> Path:
    """Scene prompts for the browser task, saved next to the job."""
    wl = {
        "job_id": job["id"],
        "product": job["product_name"],
        "model": job.get("flow_model", "fast"),
        "aspect": "9:16",
        "scenes": [
            {"scene": i, "visual_prompt": s["visual_prompt"],
             "narration": s.get("narration", ""),
             "onscreen_text": s.get("onscreen_text", "")}
            for i, s in enumerate(script["scenes"])
        ],
    }
    path = workdir(job["id"]) / "flow_worklist.json"
    path.write_text(json.dumps(wl, ensure_ascii=False, indent=2))
    return path


def build_browser_assignment(job: dict, script: dict,
                             flow_model: str = "fast") -> str:
    """Self-contained task text for the browser agent.

    The browser agent cannot see this conversation, so everything it
    needs — URLs, prompts, stop conditions — is in this string."""
    scenes = "\n".join(
        f"SCENE {i}: {s['visual_prompt']} "
        f"(Vertical 9:16 product video, bright, clean, realistic, "
        f"no text overlays.)"
        for i, s in enumerate(script["scenes"]))
    return f"""You are generating product video clips in Google Flow for an
affiliate marketing video. Work ONLY in the Flow web app at
{FLOW_URL} (it may redirect to flow.google.com — that is the same app).

FIRST, CHECK LOGIN: open {FLOW_URL} and look at whether a Google
account is signed in (avatar/profile visible, workspace accessible).
If Flow shows a login/sign-in wall, STOP IMMEDIATELY and report
"LOGIN_NEEDED" — do NOT attempt to log in, do NOT enter any
credentials, do NOT generate anything.

IF LOGGED IN, generate exactly 4 clips, one per scene below, using
text-to-video with model "Veo 3.1 {flow_model.capitalize()}" and
portrait 9:16 aspect. Generate the scenes one at a time; wait for each
clip to finish before starting the next. Download each finished clip
and name the downloads scene0.mp4, scene1.mp4, scene2.mp4, scene3.mp4
in that order (rename after download if Flow names them differently).

STOP CONDITIONS (report and stop, do not spend further):
- Flow reports insufficient credits: report "CREDIT_LOW" and stop.
- A captcha/slider challenge appears: mark that scene FAILED (captcha)
  and continue with the next scene; never attempt to solve it.
- Any scene fails twice: mark it FAILED and continue with the next.

DO NOT buy anything, change account settings, or generate anything
beyond these 4 scenes. When finished, REPORT BACK for each scene:
SCENE <n>: OK (<downloaded filename>) or SCENE <n>: FAILED (<reason>),
plus the credit balance Flow shows if visible.

{scenes}
"""


def credits_for(model: str, n_clips: int = 4) -> int:
    return CREDITS_PER_CLIP.get(model, 20) * n_clips


def credits_used_this_month(conn) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(credits_used), 0) FROM video_jobs "
        "WHERE backend = 'flow' AND strftime('%Y-%m', created_at) = "
        "strftime('%Y-%m', 'now')").fetchone()
    return row[0] if row else 0
