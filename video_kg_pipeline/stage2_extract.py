"""Stage 2: extract (subject, relation, object) triples from the ASR
transcript using GPT-4o.

Runs standalone: `python stage2_extract.py`
Reads:  config.TRANSCRIPT_PATH   (outputs/01_transcript.json)
Writes: config.TRIPLES_PATH      (outputs/02_triples.json)
        list[{triple: [s, r, o], text_evidence, timestamp: [start, end]}]

Whisper segments are short and often cut mid-sentence (see stage1 output),
so segments are grouped into windows before extraction to give GPT-4o
enough context to resolve a complete subject/relation/object (and pronouns
like "it" referring back to the previous sentence). GPT is asked to cite
which segment indices support each triple rather than re-quoting text, so
`text_evidence`/`timestamp` are reconstructed from the original transcript
- keeping evidence text hallucination-free.
"""
from __future__ import annotations

import json

import config
from utils.io_utils import load_json, save_json
from utils.llm_client import call_with_retries, get_openai_client

logger = config.setup_logging("stage2_extract")

WINDOW_SIZE = 5  # transcript segments per GPT call

SYSTEM_PROMPT = """You are extracting structured knowledge from the spoken narration of a materials-science / electrochemistry experiment (reactor assembly and testing).

For the transcript segments given (each tagged with a segment index), extract every meaningful (subject, relation, object) triple you can find, covering relation types such as:
- condition/parameter setting (e.g. temperature, thickness, size, concentration, material spec)
- operation/action performed (e.g. assembly step, coating, placing a component)
- material state change (e.g. color change, phase change, precipitate formation)
- observation/phenomenon (e.g. appearance, behavior noticed during the experiment)

Rules:
- Only extract what is explicitly stated in the text. Do not infer or invent values.
- subject/object should be concise noun phrases (e.g. "cathode gasket", "80°C"), not full sentences.
- Resolve pronouns using the surrounding segments (e.g. "it" -> the component named in the previous sentence).
- For each triple, list the segment_indices (integers) whose text directly supports it. Usually 1-2 segments.
- If a window has no meaningful triples, return an empty list.

Respond with strict JSON only, matching this shape:
{"triples": [{"subject": "...", "relation": "...", "object": "...", "segment_indices": [0]}]}
"""


def _build_window_text(segments: list[dict]) -> str:
    lines = [f"[{s['index']}] ({s['start_ts']}-{s['end_ts']}s): {s['text']}" for s in segments]
    return "\n".join(lines)


def _extract_from_window(client, segments: list[dict]) -> list[dict]:
    window_text = _build_window_text(segments)
    response = call_with_retries(
        client.chat.completions.create,
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": window_text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=1500,
        what=f"triple extraction for segments {segments[0]['index']}-{segments[-1]['index']}",
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Model returned non-JSON output, skipping window: %r", raw[:300])
        return []
    return parsed.get("triples", [])


def run() -> list[dict]:
    # Prefer the terminology-corrected transcript (stage 1b) when it exists,
    # so a fixed "Leven 117" -> "Nafion 117" etc. actually reaches extraction
    # instead of silently continuing to use the raw ASR text.
    transcript_path = config.TRANSCRIPT_CORRECTED_PATH if config.TRANSCRIPT_CORRECTED_PATH.exists() else config.TRANSCRIPT_PATH
    logger.info("Reading transcript from %s", transcript_path.name)
    transcript = load_json(transcript_path)
    by_index = {seg["index"]: seg for seg in transcript}

    client = get_openai_client()
    results: list[dict] = []

    for start in range(0, len(transcript), WINDOW_SIZE):
        window = transcript[start:start + WINDOW_SIZE]
        logger.info("Extracting triples from segments %d-%d...", window[0]["index"], window[-1]["index"])
        raw_triples = _extract_from_window(client, window)

        for t in raw_triples:
            subj, rel, obj = t.get("subject"), t.get("relation"), t.get("object")
            seg_indices = t.get("segment_indices") or []
            if not (subj and rel and obj) or not seg_indices:
                logger.warning("Skipping malformed triple: %s", t)
                continue
            cited_segments = [by_index[i] for i in seg_indices if i in by_index]
            if not cited_segments:
                logger.warning("Triple cites unknown segment indices %s, skipping: %s", seg_indices, t)
                continue
            text_evidence = " ".join(s["text"] for s in cited_segments)
            start_ts = min(s["start_ts"] for s in cited_segments)
            end_ts = max(s["end_ts"] for s in cited_segments)
            results.append({
                "triple": [subj, rel, obj],
                "text_evidence": text_evidence,
                "timestamp": [start_ts, end_ts],
            })

    save_json(results, config.TRIPLES_PATH)
    logger.info("Saved %d triples -> %s", len(results), config.TRIPLES_PATH)

    logger.info("--- Sample triples ---")
    for t in results[:10]:
        logger.info("%s | [%.2f-%.2f] %s", t["triple"], t["timestamp"][0], t["timestamp"][1], t["text_evidence"][:60])

    return results


if __name__ == "__main__":
    run()
