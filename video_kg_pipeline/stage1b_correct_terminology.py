"""Stage 1b: apply a hand-maintained terminology/unit dictionary to the ASR
transcript, between stage 1 (ASR) and stage 2 (triple extraction).

Runs standalone: `python stage1b_correct_terminology.py`
Reads:  config.TRANSCRIPT_PATH        (outputs/01_transcript.json)
        config.TERMINOLOGY_DICT_PATH  (terminology/terminology_dict.json)
Writes: config.TRANSCRIPT_CORRECTED_PATH (outputs/01b_transcript_corrected.json)
        same shape as the input, plus `original_text` (pre-correction ASR text)

Dictionary format (terminology/terminology_dict.json) - append entries here,
never edit this script, to teach it about a new recurring ASR mistake:

    "corrections": [{"wrong": "...", "correct": "...", "category": "..."}]
        Proper-noun / spelling fixes. Matched case-insensitively; if no exact
        match is found, falls back to a fuzzy word-window match (difflib)
        since ASR rarely misspells the same term identically twice.

    "unit_corrections": [{"context_hint": "...", "wrong_unit": "...", "correct_unit": "..."}]
        Only fires near `context_hint` (e.g. "gasket thickness"), and only
        on the wrong_unit occurrence that comes AFTER the hint - not any
        wrong_unit anywhere in the transcript. This matters: this video also
        says "3 micrometer per centimeter square" for an unrelated catalyst
        loading value, and "particle size ... 600 to 800 micrometer" is
        already correct - a blanket micrometer->millimeter replace would
        have corrupted both. Whisper also frequently splits a sentence like
        "the gasket thickness / is 0.2 micrometer" across two segments, so
        the unit is looked for in the current segment first, then the next
        one.
"""
from __future__ import annotations

import difflib
import re

import config
from utils.io_utils import load_json, save_json

logger = config.setup_logging("stage1b_correct_terminology")

FUZZY_THRESHOLD = 0.82


def _find_exact(text: str, phrase: str) -> re.Match | None:
    return re.search(re.escape(phrase), text, re.IGNORECASE)


def _find_fuzzy(text: str, phrase: str) -> tuple[int, int] | None:
    """Slides a window the same word-length as `phrase` over `text` and
    returns the (start, end) span of the best fuzzy match, if it clears
    FUZZY_THRESHOLD. Catches ASR misspellings that don't exactly match the
    dictionary's "wrong" string (e.g. "Levin 117" instead of "Leven 117")."""
    words = list(re.finditer(r"\S+", text))
    n = len(phrase.split())
    best_span, best_ratio = None, 0.0
    for i in range(len(words) - n + 1):
        start, end = words[i].start(), words[i + n - 1].end()
        ratio = difflib.SequenceMatcher(None, text[start:end].lower(), phrase.lower()).ratio()
        if ratio > best_ratio:
            best_ratio, best_span = ratio, (start, end)
    return best_span if best_ratio >= FUZZY_THRESHOLD else None


def _apply_terminology_corrections(text: str, rules: list[dict], seg_index: int, log: list[dict]) -> str:
    for rule in rules:
        wrong, correct, category = rule["wrong"], rule["correct"], rule.get("category", "")
        match = _find_exact(text, wrong)
        match_kind = "exact"
        if not match:
            span = _find_fuzzy(text, wrong)
            if not span:
                continue
            match_kind = "fuzzy"
            matched_text, start, end = text[span[0]:span[1]], span[0], span[1]
        else:
            matched_text, start, end = text[match.start():match.end()], match.start(), match.end()

        text = text[:start] + correct + text[end:]
        log.append({
            "segment_index": seg_index, "type": "terminology", "category": category,
            "matched_text": matched_text, "wrong": wrong, "correct": correct, "match_kind": match_kind,
        })
    return text


def _apply_unit_corrections(segments: list[dict], rules: list[dict], log: list[dict]) -> None:
    n = len(segments)
    for i, seg in enumerate(segments):
        for rule in rules:
            hint, wrong_unit, correct_unit = rule["context_hint"], rule["wrong_unit"], rule["correct_unit"]
            hint_pos = seg["text"].lower().find(hint.lower())
            if hint_pos == -1:
                continue

            pattern = re.compile(r"\b" + re.escape(wrong_unit) + r"\b", re.IGNORECASE)
            target_seg, match = seg, pattern.search(seg["text"], hint_pos + len(hint))
            if not match and i + 1 < n:
                # Whisper often splits "<parameter> thickness / is <value> <unit>"
                # across two segments - keep looking in the next one.
                target_seg, match = segments[i + 1], pattern.search(segments[i + 1]["text"])
            if not match:
                continue

            matched_text = target_seg["text"][match.start():match.end()]
            target_seg["text"] = target_seg["text"][:match.start()] + correct_unit + target_seg["text"][match.end():]
            log.append({
                "segment_index": target_seg["index"], "type": "unit", "context_hint": hint,
                "matched_text": matched_text, "wrong_unit": wrong_unit, "correct_unit": correct_unit,
            })


def run() -> list[dict]:
    transcript = load_json(config.TRANSCRIPT_PATH)
    terminology = load_json(config.TERMINOLOGY_DICT_PATH)

    log: list[dict] = []
    corrected = []
    for seg in transcript:
        original_text = seg["text"]
        new_text = _apply_terminology_corrections(original_text, terminology.get("corrections", []), seg["index"], log)
        corrected.append({**seg, "text": new_text, "original_text": original_text})

    _apply_unit_corrections(corrected, terminology.get("unit_corrections", []), log)

    save_json(corrected, config.TRANSCRIPT_CORRECTED_PATH)
    logger.info("Applied %d correction(s) across %d segments -> %s", len(log), len(corrected), config.TRANSCRIPT_CORRECTED_PATH)
    for entry in log:
        target = entry.get("correct", entry.get("correct_unit"))
        logger.info("  seg %d [%s/%s]: %r -> %r", entry["segment_index"], entry["type"],
                    entry.get("category") or entry.get("context_hint"), entry["matched_text"], target)

    return corrected


if __name__ == "__main__":
    run()
