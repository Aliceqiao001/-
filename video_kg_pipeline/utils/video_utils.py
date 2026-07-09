"""ffmpeg-backed audio extraction and seek-based frame grabbing.

Uses the static ffmpeg binary bundled by imageio-ffmpeg so nothing needs to
be installed system-wide or added to PATH. All video paths are passed
straight to subprocess as a single argv element (no shell=True), so spaces
and Chinese characters in Windows paths are handled correctly.
"""
import re
import subprocess
from pathlib import Path
from typing import Optional

import imageio_ffmpeg

_FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def _run(args: list[str]) -> str:
    proc = subprocess.run(
        [_FFMPEG_EXE, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = proc.stdout or ""
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}):\n{output[-2000:]}")
    return output


def get_video_duration_seconds(video_path: Path) -> float:
    """Parses the Duration line ffmpeg prints when given no output file."""
    proc = subprocess.run(
        [_FFMPEG_EXE, "-i", str(video_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = _DURATION_RE.search(proc.stdout or "")
    if not match:
        raise RuntimeError(f"Could not parse duration from ffmpeg output for {video_path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def extract_audio(
    video_path: Path,
    output_path: Path,
    start: Optional[float] = None,
    duration: Optional[float] = None,
    sample_rate: int = 16000,
) -> Path:
    """Extracts mono audio as an mp3 (small file size for ASR upload limits).

    `start`/`duration` (seconds) let callers pull just a test clip without
    decoding the whole file - placing -ss before -i makes ffmpeg seek instead
    of decoding-and-discarding every preceding frame.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = ["-y"]
    if start is not None:
        args += ["-ss", str(start)]
    args += ["-i", str(video_path)]
    if duration is not None:
        args += ["-t", str(duration)]
    args += ["-vn", "-ac", "1", "-ar", str(sample_rate), "-b:a", "64k", str(output_path)]
    _run(args)
    return output_path


def extract_frame_at(video_path: Path, timestamp: float, output_path: Path) -> Path:
    """Seek-based single-frame grab: -ss before -i uses fast keyframe seeking
    instead of linear decoding, which is what makes this viable for pulling
    dozens of frames out of a long video.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-y",
        "-ss", str(max(timestamp, 0.0)),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    _run(args)
    return output_path
