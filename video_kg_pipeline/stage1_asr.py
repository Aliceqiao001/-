"""Stage 1: extract audio from the source video and transcribe it with
timestamps.

Runs standalone: `python stage1_asr.py`
Reads:  config.VIDEO_PATH
Writes: config.TRANSCRIPT_PATH  (outputs/01_transcript.json)
        list[{index, text, start_ts, end_ts}], seconds.

Long videos are split into CHUNK_SECONDS-long audio chunks before upload
(ASR APIs typically cap uploads around 25MB) via seek-based ffmpeg extraction
so we never decode the whole file just to slice it. Each chunk's segment
timestamps are offset by the chunk's start time so the final list is
continuous across the whole video.
"""
from __future__ import annotations

from pathlib import Path

import config
from utils.io_utils import save_json
from utils.llm_client import call_with_retries, get_asr_client
from utils.video_utils import extract_audio, get_video_duration_seconds

logger = config.setup_logging("stage1_asr")

CHUNK_SECONDS = 900.0  # 15 min per chunk, comfortably under typical 25MB ASR upload limits


def _transcribe_chunk(client, audio_path: Path) -> list[dict]:
    with open(audio_path, "rb") as f:
        result = call_with_retries(
            client.audio.transcriptions.create,
            model=config.ASR_MODEL,
            file=f,
            response_format="verbose_json",
            what=f"ASR transcription of {audio_path.name}",
        )

    segments = getattr(result, "segments", None)
    if not segments:
        # Some relay/proxy backends ignore verbose_json and just return text.
        # Fall back to one whole-chunk pseudo-segment rather than crashing -
        # timestamps will be coarse but the text isn't lost.
        text = getattr(result, "text", "") or ""
        logger.warning(
            "%s: backend did not return segment-level timestamps; "
            "falling back to a single whole-chunk segment.",
            audio_path.name,
        )
        return [{"start": 0.0, "end": None, "text": text}]

    parsed = []
    for seg in segments:
        start = getattr(seg, "start", None) if not isinstance(seg, dict) else seg.get("start")
        end = getattr(seg, "end", None) if not isinstance(seg, dict) else seg.get("end")
        text = getattr(seg, "text", None) if not isinstance(seg, dict) else seg.get("text")
        parsed.append({"start": float(start or 0.0), "end": float(end) if end is not None else None, "text": (text or "").strip()})
    return parsed


def run(video_path: Path | None = None, test_mode: bool | None = None) -> list[dict]:
    video_path = video_path or config.VIDEO_PATH
    test_mode = config.TEST_MODE if test_mode is None else test_mode

    total_duration = get_video_duration_seconds(video_path)
    target_duration = min(total_duration, config.TEST_CLIP_SECONDS) if test_mode else total_duration
    logger.info(
        "Video duration=%.1fs, transcribing %.1fs (%s)",
        total_duration, target_duration, "TEST MODE" if test_mode else "FULL RUN",
    )

    client = get_asr_client()
    all_segments: list[dict] = []
    chunk_start = 0.0
    while chunk_start < target_duration:
        chunk_len = min(CHUNK_SECONDS, target_duration - chunk_start)
        chunk_audio_path = config.AUDIO_CACHE_DIR / f"chunk_{int(chunk_start):06d}.mp3"
        logger.info("Extracting audio chunk [%.1f, %.1f)s -> %s", chunk_start, chunk_start + chunk_len, chunk_audio_path.name)
        extract_audio(video_path, chunk_audio_path, start=chunk_start, duration=chunk_len)

        logger.info("Transcribing chunk %s (%.1f KB)...", chunk_audio_path.name, chunk_audio_path.stat().st_size / 1024)
        chunk_segments = _transcribe_chunk(client, chunk_audio_path)

        for seg in chunk_segments:
            all_segments.append({
                "text": seg["text"],
                "start_ts": round(chunk_start + seg["start"], 2),
                "end_ts": round(chunk_start + seg["end"], 2) if seg["end"] is not None else None,
            })

        chunk_start += chunk_len

    # Fill in any missing end_ts using the next segment's start (fallback backend case).
    for i, seg in enumerate(all_segments):
        if seg["end_ts"] is None:
            seg["end_ts"] = all_segments[i + 1]["start_ts"] if i + 1 < len(all_segments) else target_duration

    transcript = [
        {"index": i, "text": seg["text"], "start_ts": seg["start_ts"], "end_ts": seg["end_ts"]}
        for i, seg in enumerate(all_segments)
        if seg["text"]
    ]

    save_json(transcript, config.TRANSCRIPT_PATH)
    logger.info("Saved %d transcript segments -> %s", len(transcript), config.TRANSCRIPT_PATH)

    logger.info("--- Sanity check: first 5 segments ---")
    for seg in transcript[:5]:
        logger.info("[%6.2f - %6.2f] %s", seg["start_ts"], seg["end_ts"], seg["text"])

    return transcript


if __name__ == "__main__":
    run()
