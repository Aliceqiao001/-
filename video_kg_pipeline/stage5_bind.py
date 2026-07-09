"""Stage 5: bind stage-2 text triples to stage-4 visual evidence by
timestamp, and flag genuine text/image conflicts.

Runs standalone: `python stage5_bind.py`
Reads:  config.TRIPLES_PATH, config.VISUAL_EVIDENCE_PATH
Writes: config.KNOWLEDGE_GRAPH_PATH (outputs/05_knowledge_graph.json)

Matching strategy (best available match, never dropped):
1. exact       - the visual-evidence entry was generated from this exact
                  triple in stage 3/4 (provenance preserved end-to-end)
2. within_range - no exact link, but some frame's timestamp falls inside
                  this triple's [start, end] window
3. nearest      - fallback: closest frame by timestamp distance

Conflict detection is a dedicated GPT-4o call per node rather than string
matching on the vision description, because "the photo can't confirm a
micrometer measurement" must NOT be flagged as a conflict - only a genuine
contradiction (different color/material/state named) should be.
"""
from __future__ import annotations

import json

import config
from utils.io_utils import load_json, save_json
from utils.llm_client import call_with_retries, get_openai_client

logger = config.setup_logging("stage5_bind")

CONFLICT_SYSTEM_PROMPT = """You compare a text claim (extracted from experiment narration) against an independently generated visual description of the corresponding video frame.

Decide if they are in direct CONFLICT - i.e. the visual description states something that contradicts the text claim (a different color, a different material state, a component absent when text says present, a different shape/quantity, etc).

Do NOT count these as conflicts:
- The image simply cannot verify a precise measurement (thickness, micrometer-scale size, exact temperature) - that is a limitation, not a contradiction.
- The visual description adds detail the text didn't mention.

Respond with strict JSON only: {"conflict": true/false, "explanation": "one short sentence, empty string if no conflict"}
"""

CONFIDENCE_BY_MATCH = {"exact": 0.9, "within_range": 0.75, "nearest": 0.5}
CONFIDENCE_IF_CONFLICT = 0.3


def _find_visual_match(triple_entry: dict, visual_evidence: list[dict]) -> tuple[dict | None, str]:
    if not visual_evidence:
        return None, "none"

    exact = [v for v in visual_evidence if v.get("triple") == triple_entry["triple"]]
    if exact:
        return exact[0], "exact"

    start, end = triple_entry["timestamp"]
    within = [v for v in visual_evidence if start <= v["timestamp"] <= end]
    if within:
        mid = (start + end) / 2
        return min(within, key=lambda v: abs(v["timestamp"] - mid)), "within_range"

    mid = (start + end) / 2
    return min(visual_evidence, key=lambda v: abs(v["timestamp"] - mid)), "nearest"


def _check_conflict(client, triple_entry: dict, visual_match: dict) -> dict:
    user_content = (
        f"Text claim (triple): {tuple(triple_entry['triple'])}\n"
        f"Text evidence: {triple_entry['text_evidence']}\n"
        f"Visual description: {visual_match['vlm_description']}"
    )
    response = call_with_retries(
        client.chat.completions.create,
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": CONFLICT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=200,
        what=f"conflict check for triple {triple_entry['triple']}",
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Conflict-check returned non-JSON, assuming no conflict: %r", raw[:200])
        return {"conflict": False, "explanation": ""}
    return {"conflict": bool(parsed.get("conflict", False)), "explanation": parsed.get("explanation", "")}


def run() -> list[dict]:
    triples = load_json(config.TRIPLES_PATH)
    visual_evidence = load_json(config.VISUAL_EVIDENCE_PATH)
    client = get_openai_client()

    nodes = []
    for t in triples:
        visual_match, match_kind = _find_visual_match(t, visual_evidence)

        node = {
            "triple": t["triple"],
            "text_evidence": t["text_evidence"],
            "image_evidence": (
                {"frame_path": visual_match["frame_path"], "vlm_description": visual_match["vlm_description"]}
                if visual_match else None
            ),
            "timestamp": t["timestamp"],
            "confidence": CONFIDENCE_BY_MATCH.get(match_kind, 0.5),
            "conflict": False,
            "conflict_explanation": "",
        }

        if visual_match:
            logger.info("Checking conflict for triple %s (match=%s)...", t["triple"], match_kind)
            conflict_result = _check_conflict(client, t, visual_match)
            node["conflict"] = conflict_result["conflict"]
            node["conflict_explanation"] = conflict_result["explanation"]
            if conflict_result["conflict"]:
                node["confidence"] = CONFIDENCE_IF_CONFLICT
                logger.warning("CONFLICT for %s: %s", t["triple"], conflict_result["explanation"])
        else:
            logger.warning("No visual evidence at all could be matched for triple %s", t["triple"])

        nodes.append(node)

    save_json(nodes, config.KNOWLEDGE_GRAPH_PATH)
    logger.info("Saved %d knowledge-graph nodes -> %s", len(nodes), config.KNOWLEDGE_GRAPH_PATH)

    n_conflicts = sum(1 for n in nodes if n["conflict"])
    logger.info("--- Summary: %d nodes, %d conflicts flagged ---", len(nodes), n_conflicts)
    for n in nodes:
        flag = "CONFLICT" if n["conflict"] else "ok"
        logger.info("[%s] %s (confidence=%.2f)", flag, n["triple"], n["confidence"])

    return nodes


if __name__ == "__main__":
    run()
