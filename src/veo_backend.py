"""Veo video backend (Google's video model — the same engine behind Flow).

Why Veo and not the Flow web app: Google Flow (labs.google/fx/flow)
has NO public API. Automating its web UI through a browser is possible
but flaky (login walls, minute-long generations, UI drift) and would
break the pipeline's unattended operation. Veo via the Gemini API is
the supported programmatic route to the same model family, with an
async operation pattern: submit prompt -> poll -> download.

Each clip is 8 seconds (Veo 3.1's fixed length), portrait 9:16 for
Shorts/Reels. A ~32s product video = 4 clips stitched by ffmpeg in
video_gen.assemble().

Needs GEMINI_API_KEY in .env + billing on the Google Cloud project.
Pricing is per video-second (check the current Gemini API pricing
page); the fast model below exists specifically to keep the cost of
a 4-clip video sane. Set VEO_MODEL=veo-3.1-generate-preview for the
higher-quality variant.
"""

import time
from pathlib import Path

DEFAULT_MODEL = "veo-3.1-fast-generate-preview"


class VeoError(Exception):
    pass


def generate_clip(api_key: str, prompt: str, out_path: Path,
                  model: str = DEFAULT_MODEL,
                  timeout_s: int = 600) -> Path:
    """Generate one 8s 9:16 clip; blocks (polls) until done or timeout."""
    if not api_key:
        raise VeoError("GEMINI_API_KEY belum diisi di .env — "
                       "video AI belum bisa di-generate.")
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)
    try:
        operation = client.models.generate_videos(
            model=model, prompt=prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio="9:16",
                person_generation="allow_adult",
            ),
        )
    except Exception as e:  # noqa: BLE001 - wrapped with context
        raise VeoError(f"Veo submit gagal: {e}") from e
    deadline = time.time() + timeout_s
    while not operation.done:
        if time.time() > deadline:
            raise VeoError(f"Veo timeout {timeout_s}s untuk prompt: "
                           f"{prompt[:80]}")
        time.sleep(10)
        try:
            operation = client.operations.get(operation)
        except Exception as e:  # noqa: BLE001
            raise VeoError(f"Veo poll gagal: {e}") from e
    videos = (operation.response.generated_videos
              if operation.response else [])
    if not videos:
        raise VeoError("Veo selesai tanpa video (kemungkinan ditolak "
                       "filter keamanan — coba ubah prompt scenenya).")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    client.files.download(file=videos[0].video, destination=str(out_path))
    return out_path
