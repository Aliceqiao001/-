"""Stage 4: seek-based keyframe extraction + Gemini vision analysis.

Runs standalone: `python stage4_visual.py`
Reads:  config.KEYFRAME_TS_PATH (outputs/03_keyframe_timestamps.json)
Writes: config.VISUAL_EVIDENCE_PATH (outputs/04_visual_evidence.json)
        list[{timestamp, frame_path, text_context, vlm_description, triple}]
        frame images -> config.FRAMES_DIR

Frames are pulled with ffmpeg's `-ss` placed *before* `-i` (see
utils.video_utils.extract_frame_at), which seeks to the nearest keyframe
instead of decoding every preceding frame - the only way seeking dozens of
timestamps out of a multi-minute video stays cheap.

Each frame's prompt is built from that timestamp's own text evidence/triple
so Gemini is asked a specific verification question (e.g. "does the image
support this claim about gasket thickness / material / placement") instead
of a generic "describe this image".
"""
from __future__ import annotations

import base64
from pathlib import Path

import config
from utils.io_utils import load_json, save_json
from utils.llm_client import call_with_retries, get_gemini_client
from utils.video_utils import extract_frame_at

logger = config.setup_logging("stage4_visual")

SYSTEM_PROMPT = """You are a visual verification assistant for a materials-science / electrochemistry experiment video. You are shown one frame plus the narrator's spoken claim at that exact moment.

Do not give a generic caption. Answer specifically with respect to the claim:
1. Does the image support this specific claim? What visual evidence do you see for or against it?
2. Describe the object/material/component named in the claim: its color, shape, texture, position, and any visually-assessable detail relevant to the stated relation. If the claim is a measurement (thickness, size, loading amount) you cannot measure precisely from a photo - describe its visual scale/appearance instead. If it's about material composition or a state change, describe color/texture/opacity. If it's about an action or placement, describe the component's position and assembly state.

Keep the answer to 2-4 concrete sentences. Avoid generic phrases like "there is an object on a table"."""


def _build_user_text(keyframe: dict) -> str:
    triple = keyframe.get("triple")
    triple_line = f"Extracted fact: {tuple(triple)}" if triple else "Extracted fact: (none extracted for this moment)"
    return (
        f"Narrator's claim at t={keyframe['timestamp']}s:\n\"{keyframe['text_evidence']}\"\n"
        f"{triple_line}\n\nAnalyze the image with respect to this claim."
    )


def _analyze_frame(client, frame_path: Path, keyframe: dict) -> str:
    b64 = base64.b64encode(frame_path.read_bytes()).decode("utf-8")
    response = call_with_retries(
        client.chat.completions.create,
        model=config.GEMINI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _build_user_text(keyframe)},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            },
        ],
        max_tokens=500,
        what=f"Gemini vision analysis at t={keyframe['timestamp']}s",
    )
    return (response.choices[0].message.content or "").strip()


def run(video_path: Path | None = None) -> list[dict]:
    video_path = video_path or config.VIDEO_PATH
    keyframes = load_json(config.KEYFRAME_TS_PATH)
    client = get_gemini_client()

    results = []
    for kf in keyframes:
        ts = kf["timestamp"]
        frame_path = config.FRAMES_DIR / f"frame_{ts:07.2f}.jpg"
        logger.info("Extracting frame at t=%.2fs -> %s", ts, frame_path.name)
        extract_frame_at(video_path, ts, frame_path)

        logger.info("Analyzing frame with Gemini...")
        description = _analyze_frame(client, frame_path, kf)

        results.append({
            "timestamp": ts,
            "frame_path": str(frame_path.relative_to(config.PROJECT_ROOT)).replace("\\", "/"),
            "text_context": kf["text_evidence"],
            "vlm_description": description,
            "triple": kf.get("triple"),
        })

    save_json(results, config.VISUAL_EVIDENCE_PATH)
    logger.info("Saved %d visual evidence entries -> %s", len(results), config.VISUAL_EVIDENCE_PATH)

    logger.info("--- Sample visual evidence ---")
    for r in results[:5]:
        logger.info("[%6.2f] %s | %s", r["timestamp"], r["triple"], r["vlm_description"][:80])

    return results


if __name__ == "__main__":
    run()
