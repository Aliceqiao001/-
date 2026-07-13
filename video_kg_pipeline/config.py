"""Central configuration for the video-to-knowledge-graph pipeline.

Loads secrets from the repo-root .env (D:\\视频解析\\.env) and exposes
everything else (paths, model names, retry policy) as plain constants so
changing behavior never requires touching the stage scripts.
"""
import logging
from pathlib import Path

from dotenv import load_dotenv
import os

PROJECT_ROOT = Path(__file__).resolve().parent          # .../video_kg_pipeline
REPO_ROOT = PROJECT_ROOT.parent                          # .../视频解析

load_dotenv(REPO_ROOT / ".env")

# --------------------------------------------------------------------------
# API credentials (never hardcode these - always read from environment)
# --------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ASR_API_KEY = os.getenv("ASR_API_KEY", "")

# Base URLs. Default to each vendor's official endpoint; override in .env
# (OPENAI_BASE_URL / GEMINI_BASE_URL / ASR_BASE_URL) if these keys turn out
# to belong to a relay/proxy platform instead.
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
ASR_BASE_URL = os.getenv("ASR_BASE_URL", "https://api.openai.com/v1")

# --------------------------------------------------------------------------
# Models (confirmed with user 2026-07-08)
# --------------------------------------------------------------------------
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")          # stage2 triple extraction
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")  # stage4 visual understanding
ASR_MODEL = os.getenv("ASR_MODEL", "whisper-1")              # stage1 transcription

# --------------------------------------------------------------------------
# Input / output paths
# --------------------------------------------------------------------------
VIDEO_PATH = Path(os.getenv(
    "VIDEO_PATH",
    str(REPO_ROOT / "LRV_20260628_182829_01_070 - 副本.mp4"),
))

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(PROJECT_ROOT / "outputs")))
FRAMES_DIR = OUTPUT_DIR / "frames"
AUDIO_CACHE_DIR = OUTPUT_DIR / "audio"

TRANSCRIPT_PATH = OUTPUT_DIR / "01_transcript.json"
TRANSCRIPT_CORRECTED_PATH = OUTPUT_DIR / "01b_transcript_corrected.json"
TERMINOLOGY_DICT_PATH = PROJECT_ROOT / "terminology" / "terminology_dict.json"
TRIPLES_PATH = OUTPUT_DIR / "02_triples.json"
KEYFRAME_TS_PATH = OUTPUT_DIR / "03_keyframe_timestamps.json"
VISUAL_EVIDENCE_PATH = OUTPUT_DIR / "04_visual_evidence.json"
KNOWLEDGE_GRAPH_PATH = OUTPUT_DIR / "05_knowledge_graph.json"
KG_PNG_PATH = OUTPUT_DIR / "knowledge_graph.png"
KG_HTML_PATH = OUTPUT_DIR / "knowledge_graph.html"

for d in (OUTPUT_DIR, FRAMES_DIR, AUDIO_CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Test-clip mode: run the whole pipeline on just the first N seconds first
# --------------------------------------------------------------------------
TEST_MODE = os.getenv("TEST_MODE", "1") == "1"
TEST_CLIP_SECONDS = float(os.getenv("TEST_CLIP_SECONDS", "120"))

# --------------------------------------------------------------------------
# Retry / network policy for all LLM/VLM/ASR calls
# --------------------------------------------------------------------------
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))
RETRY_BACKOFF_SECONDS = float(os.getenv("RETRY_BACKOFF_SECONDS", "2.0"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60"))


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(name)
