"""Stage 3: locate keyframe timestamps by information density instead of
uniform sampling.

Runs standalone: `python stage3_keyframes.py`
Reads:  config.TRANSCRIPT_PATH, config.TRIPLES_PATH
Writes: config.KEYFRAME_TS_PATH (outputs/03_keyframe_timestamps.json)

Candidates come from three sources, then nearby candidates (within
MERGE_WINDOW_SECONDS) are merged into a single keyframe point so stage 4
doesn't pull near-duplicate frames:

1. "triple"         - every stage-2 triple's timestamp range is inherently an
                       information-dense moment. Anchor = midpoint of the range.
2. "keyword"        - transcript segments containing action/state-change words
                       (start, appear, become, place, form, ...). Anchor =
                       segment start.
3. "semantic_shift"  (optional, embedding-based) - a big drop in cosine
                       similarity between consecutive segments suggests a
                       topic/action change worth a frame. Anchor = later
                       segment's start. Degrades gracefully (skipped, not
                       fatal) if the embedding call fails.
"""
from __future__ import annotations

import re

import numpy as np

import config
from utils.io_utils import load_json, save_json
from utils.llm_client import call_with_retries, get_openai_client

logger = config.setup_logging("stage3_keyframes")

MERGE_WINDOW_SECONDS = 3.0
EMBEDDING_MODEL = "text-embedding-3-small"
SEMANTIC_SHIFT_THRESHOLD = 0.55  # cosine similarity below this = a shift worth flagging

STATE_CHANGE_KEYWORDS = [
    "start", "begin", "appear", "become", "turn into", "stop", "form",
    "place", "insert", "attach", "connect", "assemble", "change",
    "complete", "remove", "open", "close", "flow", "release", "produce",
]
_KEYWORD_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in STATE_CHANGE_KEYWORDS) + r")\w*\b", re.IGNORECASE)


def _triple_candidates(triples: list[dict]) -> list[dict]:
    candidates = []
    for t in triples:
        start, end = t["timestamp"]
        candidates.append({
            "timestamp": round((start + end) / 2, 2),
            "sources": ["triple"],
            "triple": t["triple"],
            "text_evidence": t["text_evidence"],
            "matched_keywords": [],
        })
    return candidates


def _keyword_candidates(transcript: list[dict], triples: list[dict]) -> list[dict]:
    candidates = []
    for seg in transcript:
        matches = sorted(set(m.group(0).lower() for m in _KEYWORD_RE.finditer(seg["text"])))
        if not matches:
            continue
        overlapping_triple = next(
            (t["triple"] for t in triples if t["timestamp"][0] <= seg["start_ts"] <= t["timestamp"][1]),
            None,
        )
        candidates.append({
            "timestamp": seg["start_ts"],
            "sources": ["keyword"],
            "triple": overlapping_triple,
            "text_evidence": seg["text"],
            "matched_keywords": matches,
        })
    return candidates


def _embed_texts(client, texts: list[str]) -> np.ndarray | None:
    try:
        response = call_with_retries(
            client.embeddings.create,
            model=EMBEDDING_MODEL,
            input=texts,
            what="segment embeddings for semantic-shift detection",
            max_retries=2,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Semantic-shift detection skipped, embedding call failed: %s", exc)
        return None
    return np.array([d.embedding for d in response.data])


def _semantic_shift_candidates(client, transcript: list[dict]) -> list[dict]:
    if len(transcript) < 2:
        return []
    vectors = _embed_texts(client, [seg["text"] for seg in transcript])
    if vectors is None:
        return []

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    normed = vectors / np.clip(norms, 1e-8, None)
    sims = np.sum(normed[:-1] * normed[1:], axis=1)

    candidates = []
    for i, sim in enumerate(sims):
        if sim < SEMANTIC_SHIFT_THRESHOLD:
            later = transcript[i + 1]
            candidates.append({
                "timestamp": later["start_ts"],
                "sources": ["semantic_shift"],
                "triple": None,
                "text_evidence": f"{transcript[i]['text']} || {later['text']}",
                "matched_keywords": [],
                "similarity": round(float(sim), 3),
            })
    return candidates


def _merge_candidates(candidates: list[dict]) -> list[dict]:
    candidates = sorted(candidates, key=lambda c: c["timestamp"])
    merged: list[dict] = []
    for c in candidates:
        if merged and c["timestamp"] - merged[-1]["timestamp"] <= MERGE_WINDOW_SECONDS:
            prev = merged[-1]
            prev["sources"] = sorted(set(prev["sources"]) | set(c["sources"]))
            prev["matched_keywords"] = sorted(set(prev["matched_keywords"]) | set(c["matched_keywords"]))
            if not prev.get("triple") and c.get("triple"):
                prev["triple"] = c["triple"]
            if c["text_evidence"] not in prev["text_evidence"]:
                prev["text_evidence"] = prev["text_evidence"] + " || " + c["text_evidence"]
        else:
            merged.append(dict(c))
    return merged


def run(use_semantic_shift: bool = True) -> list[dict]:
    transcript = load_json(config.TRANSCRIPT_PATH)
    triples = load_json(config.TRIPLES_PATH)

    candidates = _triple_candidates(triples) + _keyword_candidates(transcript, triples)
    logger.info("Triple candidates + keyword candidates: %d", len(candidates))

    if use_semantic_shift:
        client = get_openai_client()
        shift_candidates = _semantic_shift_candidates(client, transcript)
        logger.info("Semantic-shift candidates: %d", len(shift_candidates))
        candidates += shift_candidates

    keyframes = _merge_candidates(candidates)
    logger.info("Merged into %d keyframe timestamps (merge window=%.1fs)", len(keyframes), MERGE_WINDOW_SECONDS)

    save_json(keyframes, config.KEYFRAME_TS_PATH)
    logger.info("Saved -> %s", config.KEYFRAME_TS_PATH)

    logger.info("--- Sample keyframes ---")
    for k in keyframes[:10]:
        logger.info("[%6.2f] sources=%s triple=%s", k["timestamp"], k["sources"], k["triple"])

    return keyframes


if __name__ == "__main__":
    run()
