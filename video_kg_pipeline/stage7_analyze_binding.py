"""Stage 7 (offline analysis, not part of the per-video pipeline): re-classify
the image/text binding quality of every node already produced in
outputs_batch/<label>/05_knowledge_graph.json across all batch-processed
videos.

Does NOT call any API and does NOT re-run ASR/extraction/VLM - it only reads
the JSON that stages 1-6 already wrote to disk, so it runs in well under a
second for 25 videos.

Why not just use the existing `conflict` boolean?
Stage 5's conflict flag conflates several different situations: a genuine
text/image contradiction, a VLM description that simply can't verify a
number or chemical composition, a keyframe that landed slightly before/after
the action it's meant to illustrate, and (in a handful of nodes) a
vlm_description that got truncated in storage before it ever stated a
verdict. This script re-derives a 4-way judgement per node by pattern-
matching the actual vlm_description text instead of trusting that flag:

    confirmed        - vlm_description clearly and completely describes a
                        visual feature matching the triple (shape/color/
                        structure/visible state change), not truncated.
    unverifiable      - the triple is a number/material/chemical spec a still
                        photo can never confirm, and the VLM said so. Not a
                        conflict, just a hard limit of the method.
    narration_lag      - the described action/state is adjacent in time to
                        what the frame shows (about to happen / just
                        happened), i.e. a keyframe-timing issue, not a
                        content contradiction.
    needs_review       - either the vlm_description contradicts the triple
                        with a specific counter-observation, or the
                        description is missing/too short/cut off before
                        stating any verdict. Both cases need a human to look
                        at the source video; they're kept together because
                        the automatic distinction between "real conflict"
                        and "unreadable description" isn't reliable enough
                        to make unsupervised.

This is a heuristic text classifier, not a ground-truth labeller - the
`needs_review` bucket exists precisely to catch what the heuristic can't
resolve on its own.

Usage:
    python stage7_analyze_binding.py
    python stage7_analyze_binding.py --outputs-batch-dir path/to/outputs_batch
"""
from __future__ import annotations

import argparse
import re
from html import escape as html_escape
from pathlib import Path
from typing import Any

import config
from utils.io_utils import load_json

logger = config.setup_logging("stage7_analyze_binding")

CATEGORIES = ["confirmed", "unverifiable", "narration_lag", "needs_review"]
CATEGORY_LABEL = {
    "confirmed": "Confirmed",
    "unverifiable": "Unverifiable",
    "narration_lag": "Narration Lag",
    "needs_review": "Needs Review",
}

UNVERIFIABLE_PATTERNS = [
    r"cannot (?:be )?(?:directly )?(?:visually )?(?:verif\w*|confirm\w*|assess\w*|determin\w*|measur\w*)",
    r"not (?:possible|able) to (?:visually )?(?:verify|confirm|measure|assess)",
    r"neither support\w* nor refut\w*",
    r"does not (?:support or refute|directly support or refute|provide (?:visual )?evidence to (?:confirm or contradict|support or refute))",
    r"cannot (?:directly )?(?:confirm or deny|support or refute)",
    r"not (?:visually )?(?:discernible|verifiable|ascertainable)",
    r"gases? (?:are|is) (?:generally )?invisible",
    r"cannot be visually assessed",
    r"quantitative measurement",
    r"chemical composition cannot",
    r"precise (?:measurement|thickness|dimension|concentration)s? (?:cannot|can(?:'|no)?t)",
    r"is a limitation, not a contradiction",
    r"cannot be (?:precisely )?verified from",
    r"no visible liquid electrolyte" ,
]

LAG_PATTERNS = [
    r"not yet",
    r"prior to",
    r"about to",
    r"poised (?:to|as if)",
    r"has not (?:been|occurred)",
    r"not currently (?:occurring|taking place)",
    r"no assembly is taking place",
    r"not actively",
    r"currently being handled",
]

CONFIRM_PATTERNS = [
    r"strongly supports",
    r"^yes,? the image",
    r"clearly (?:shows|displays|visible)",
    r"directly supports",
    r"confirms the claim",
]

NEGATED_SUPPORT_PATTERNS = [
    r"does not (?:visually )?support",
    r"doesn.t support",
    r"cannot support",
    r"^no,? the image",
]

POSITIVE_SUPPORT_PATTERNS = [
    r"support(?:s)? (?:this |the )?(?:specific )?claim",
    r"the image (?:strongly |visually |directly |also )?supports",
    r"visually supports",
]

MIN_COMPLETE_LEN = 20


def _first_point(desc: str) -> str:
    """Stage4's VLM prompt asks for a numbered answer ("1. does the image
    support this claim? ... 2. describe the object ..."). Point 1 is the
    verdict we actually need to classify on; point 2 (free description) is
    the part most often truncated in storage, so isolating point 1 lets us
    classify correctly even when point 2 got cut off."""
    if not desc:
        return ""
    m = re.search(r"1\.\s*(.*?)(?=\n\s*2\.|\Z)", desc, re.S)
    text = m.group(1) if m else desc
    return text.strip()


def _is_incomplete(point1: str) -> bool:
    if not point1 or len(point1) < MIN_COMPLETE_LEN:
        return True
    return not re.search(r'[.!?"”]\s*$', point1)


def _matches_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def classify_node(entry: dict) -> tuple[str, str]:
    """Priority: try to read a verdict off whatever text is actually present
    FIRST; only fall back to needs_review for truncation once no keyword
    pattern matched anywhere in the available text. Stage 4 caps the VLM
    call at max_tokens=500, so a large fraction of descriptions get cut off
    mid-sentence - but most of them state their verdict ("does not support
    the claim that X is a quantitative measurement...") before the cutoff,
    so truncation alone must not short-circuit classification, or almost
    everything ends up misfiled as needs_review."""
    img = entry.get("image_evidence") or {}
    desc = (img.get("vlm_description") or "").strip()
    conflict = bool(entry.get("conflict", False))
    conflict_explanation = (entry.get("conflict_explanation") or "").strip()

    point1 = _first_point(desc)
    combined = f"{point1} {conflict_explanation}".strip()

    if not point1 or len(point1) < MIN_COMPLETE_LEN:
        return "needs_review", "vlm_description 缺失或过短,看不出支持还是反对立场"

    if _matches_any(LAG_PATTERNS, combined):
        return "narration_lag", "描述指向动作发生前/后的相邻时刻,是关键帧定位的时间差,非内容矛盾"

    if _matches_any(UNVERIFIABLE_PATTERNS, combined):
        return "unverifiable", "三元组内容是数值/材质/化学成分等静态画面本就无法判断的信息"

    if _matches_any(CONFIRM_PATTERNS, combined):
        return "confirmed", "vlm_description 明确、完整地描述了与三元组一致的可视化特征"

    if not _matches_any(NEGATED_SUPPORT_PATTERNS, combined) and _matches_any(POSITIVE_SUPPORT_PATTERNS, combined):
        return "confirmed", "vlm_description 明确表示画面支持该主张,即使后续细节描述被截断"

    if re.search(r"partially support", combined, re.IGNORECASE):
        return "unverifiable", "图像只能部分印证,细节(数值/材质等)仍无法验证"

    if conflict:
        return "needs_review", "vlm_description 与三元组存在具体分歧,需人工核对原始画面"

    if _is_incomplete(point1):
        return "needs_review", "vlm_description 在给出明确立场前被截断,看不出支持还是反对"

    if len(point1) > 40:
        return "confirmed", "vlm_description 给出具体、完整的可视化描述,与三元组内容一致"

    return "needs_review", "证据描述过短或含糊,难以判断支持/反对"


def analyze_video(label: str, kg_path: Path) -> dict[str, Any]:
    nodes = load_json(kg_path)
    counts = {c: 0 for c in CATEGORIES}
    review_items: list[dict] = []

    for entry in nodes:
        category, reason = classify_node(entry)
        counts[category] += 1
        if category == "needs_review":
            img = entry.get("image_evidence") or {}
            review_items.append({
                "video": label,
                "triple": entry.get("triple"),
                "text_evidence": entry.get("text_evidence", ""),
                "vlm_description": img.get("vlm_description", ""),
                "frame_path": img.get("frame_path", ""),
                "reason": reason,
            })

    return {
        "label": label,
        "total": len(nodes),
        "counts": counts,
        "review_items": review_items,
    }


def format_triple(triple) -> str:
    if isinstance(triple, list) and len(triple) == 3:
        return f"[{triple[0]}] --{triple[1]}--> [{triple[2]}]"
    return str(triple)


def compute_stats(results: list[dict]) -> dict[str, Any]:
    """Shared aggregation used by both the markdown and HTML report builders,
    so the two outputs can never silently drift apart."""
    processed = [r for r in results if r["total"] > 0]
    skipped = [r for r in results if r["total"] == 0]
    total_nodes = sum(r["total"] for r in processed)
    global_counts = {c: sum(r["counts"][c] for r in processed) for c in CATEGORIES}
    all_review = [item for r in results for item in r["review_items"]]
    dominant = max(CATEGORIES, key=lambda c: global_counts[c]) if total_nodes else None
    return {
        "processed": processed,
        "skipped": skipped,
        "total_nodes": total_nodes,
        "global_counts": global_counts,
        "all_review": all_review,
        "dominant": dominant,
    }


def build_report(results: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# 图文绑定质量分析报告")
    lines.append("")
    lines.append("由 `stage7_analyze_binding.py` 生成,读取各视频已有的 "
                  "`05_knowledge_graph.json`,对每条知识节点重新判定图文绑定"
                  "属于四类之一:Confirmed / Unverifiable / Narration Lag / "
                  "Needs Review(定义见脚本 docstring)。不重新调用任何 API。")
    lines.append("")
    lines.append("## 1. 按视频统计")
    lines.append("")
    lines.append("| 视频 | 总节点数 | Confirmed | Unverifiable | Narration Lag | Needs Review |")
    lines.append("|---|---:|---:|---:|---:|---:|")

    stats = compute_stats(results)
    processed, skipped = stats["processed"], stats["skipped"]

    for r in results:
        c = r["counts"]
        if r["total"] == 0:
            lines.append(f"| {r['label']} | 0 | - | - | - | - |")
        else:
            lines.append(
                f"| {r['label']} | {r['total']} | {c['confirmed']} | "
                f"{c['unverifiable']} | {c['narration_lag']} | {c['needs_review']} |"
            )

    lines.append("")
    if skipped:
        skipped_names = "、".join(r["label"] for r in skipped)
        lines.append(f"（0 节点视频已跳过分类,不计入下方全局占比:{skipped_names}）")
        lines.append("")

    lines.append("## 2. 全局统计")
    lines.append("")
    total_nodes = stats["total_nodes"]
    global_counts = stats["global_counts"]

    if total_nodes == 0:
        lines.append("没有可分析的知识节点。")
    else:
        lines.append(f"25 段视频中有 {len(processed)} 段产出了知识节点,合计 "
                      f"**{total_nodes}** 条,分类占比如下:")
        lines.append("")
        for cat in CATEGORIES:
            n = global_counts[cat]
            pct = n / total_nodes * 100
            lines.append(f"- **{CATEGORY_LABEL[cat]}**:{n} 条,占 {pct:.1f}%")
    lines.append("")

    lines.append("## 3. Needs Review 清单(需人工复核)")
    lines.append("")
    all_review = stats["all_review"]
    if not all_review:
        lines.append("无需要人工复核的条目。")
    else:
        lines.append(f"共 {len(all_review)} 条,按视频顺序列出:")
        lines.append("")
        for i, item in enumerate(all_review, 1):
            lines.append(f"### {i}. {item['video']}")
            lines.append("")
            lines.append(f"- **三元组**:{format_triple(item['triple'])}")
            lines.append(f"- **原文讲解**:{item['text_evidence']}")
            lines.append(f"- **图像描述**:{item['vlm_description']}")
            lines.append(f"- **关键帧路径**:`{item['frame_path']}`")
            lines.append(f"- **判定原因**:{item['reason']}")
            lines.append("")

    lines.append("## 4. 总体结论")
    lines.append("")
    if total_nodes > 0:
        dominant = stats["dominant"]
        dominant_pct = global_counts[dominant] / total_nodes * 100
        lines.append(
            f"这批 {total_nodes} 条知识节点里,**{CATEGORY_LABEL[dominant]}** "
            f"占比最高({dominant_pct:.1f}%)。整体来看,这套图文绑定流程能可靠"
            f"验证的是画面里**看得见的定性物理状态**——形状、颜色、结构、"
            f"积水/变色/撕裂这类肉眼可判断的现象;验证不了的是**定量数值和"
            f"化学成分**——厚度、载量、膜型号这类信息,静态画面天然给不出"
            f"答案,这不是流程缺陷,是方法本身的能力边界。Narration Lag 反映"
            f"的是关键帧定位与讲解存在几秒级的时间差,本质是抽帧时机问题,"
            f"不是内容错误。真正值得警惕的是 Needs Review 里的条目——要么"
            f"VLM 明确给出了和文本相悖的具体观察,要么证据描述本身缺失或被"
            f"截断到无法判断,这两种都需要人工对照原始视频画面复核。"
        )
    lines.append("")
    return "\n".join(lines)


CATEGORY_CSS_CLASS = {
    "confirmed": "cat-confirmed",
    "unverifiable": "cat-unverifiable",
    "narration_lag": "cat-lag",
    "needs_review": "cat-review",
}

HTML_HEAD = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>图文绑定质量分析报告</title>
<style>
  :root {
    --bg: #f1f4ef; --surface: #ffffff; --surface-2: #e9efe6;
    --ink: #17211c; --ink-soft: #4c5850; --ink-faint: #7c8880;
    --line: #d7ded2;
    --accent: #2f7c68; --accent-ink: #1e5747; --accent-soft: #e2efe8;
    --warn: #b1592c; --warn-soft: #f7e6d9; --warn-ink: #7a3a1a;
    --neutral-soft: #eceee9;
    --font-display: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
    --font-body: "Iowan Old Style", Palatino, "Palatino Linotype", Georgia, serif;
    --font-ui: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    --font-mono: "SF Mono", SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
  }
  :root[data-theme="dark"] {
    --bg: #0e1512; --surface: #141d18; --surface-2: #1a251f;
    --ink: #e6ede7; --ink-soft: #a3b3a8; --ink-faint: #6d7d73;
    --line: #263229;
    --accent: #5cbfa0; --accent-ink: #8fdcc2; --accent-soft: #1b2e27;
    --warn: #e2914f; --warn-soft: #33251a; --warn-ink: #f0b787;
    --neutral-soft: #1b2420;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0e1512; --surface: #141d18; --surface-2: #1a251f;
      --ink: #e6ede7; --ink-soft: #a3b3a8; --ink-faint: #6d7d73;
      --line: #263229;
      --accent: #5cbfa0; --accent-ink: #8fdcc2; --accent-soft: #1b2e27;
      --warn: #e2914f; --warn-soft: #33251a; --warn-ink: #f0b787;
      --neutral-soft: #1b2420;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--font-body); line-height: 1.6; -webkit-font-smoothing: antialiased; }
  .page { max-width: 960px; margin: 0 auto; padding: 3.5rem 1.5rem 5rem; }
  .eyebrow { font-family: var(--font-ui); font-size: .72rem; letter-spacing: .14em; text-transform: uppercase; color: var(--accent-ink); font-weight: 600; }
  h1 { font-family: var(--font-display); font-weight: 500; font-size: clamp(1.6rem, 4vw, 2.3rem); margin: .5rem 0 .6rem; text-wrap: balance; }
  .subtitle { color: var(--ink-soft); font-size: 1.02rem; max-width: 68ch; }
  .meta-row { display: flex; flex-wrap: wrap; gap: .5rem 1.6rem; margin-top: 1.6rem; padding-top: 1.4rem; border-top: 1px solid var(--line); font-family: var(--font-ui); }
  .meta-item { display: flex; flex-direction: column; gap: .15rem; }
  .meta-num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; font-size: 1.35rem; }
  .meta-label { font-size: .66rem; letter-spacing: .07em; text-transform: uppercase; color: var(--ink-faint); }
  section { margin-top: 3.4rem; }
  h2 { font-family: var(--font-display); font-weight: 500; font-size: 1.4rem; margin: 0 0 .3rem; }
  .section-note { color: var(--ink-soft); font-size: .93rem; max-width: 70ch; margin: 0 0 1.4rem; }
  .table-scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; }
  table { border-collapse: collapse; width: 100%; font-size: .85rem; min-width: 640px; }
  thead th { position: sticky; top: 0; background: var(--surface-2); font-family: var(--font-ui); font-weight: 600; font-size: .66rem; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-soft); text-align: left; padding: .55rem .75rem; border-bottom: 1px solid var(--line); white-space: nowrap; }
  td { padding: .48rem .75rem; border-bottom: 1px solid var(--line); background: var(--surface); vertical-align: middle; white-space: nowrap; }
  tbody tr:last-child td { border-bottom: none; }
  td.num, th.num { text-align: right; font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
  tr.skipped td { color: var(--ink-faint); font-style: italic; }
  .bar-row { display: flex; gap: 2px; width: 120px; height: 9px; border-radius: 3px; overflow: hidden; margin-left: auto; background: var(--neutral-soft); }
  .bar-seg { height: 100%; }
  .cat-confirmed { background: var(--accent); }
  .cat-unverifiable { background: var(--ink-faint); }
  .cat-lag { background: #7893c4; }
  .cat-review { background: var(--warn); }
  .legend { display: flex; flex-wrap: wrap; gap: 1.1rem; font-family: var(--font-ui); font-size: .78rem; color: var(--ink-soft); margin: .9rem 0 1.5rem; }
  .legend-item { display: flex; align-items: center; gap: .4rem; }
  .legend-dot { width: .6rem; height: .6rem; border-radius: 2px; display: inline-block; }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .8rem; margin-top: 1rem; }
  .stat-card { border: 1px solid var(--line); border-radius: 8px; padding: .9rem 1rem; background: var(--surface); }
  .stat-card .n { font-family: var(--font-mono); font-variant-numeric: tabular-nums; font-size: 1.5rem; }
  .stat-card .l { font-family: var(--font-ui); font-size: .72rem; letter-spacing: .05em; text-transform: uppercase; color: var(--ink-faint); margin-top: .2rem; }
  .stat-card .p { font-family: var(--font-ui); font-size: .8rem; color: var(--ink-soft); }
  .stat-card.confirmed .n { color: var(--accent-ink); }
  .stat-card.needs_review .n { color: var(--warn-ink); }
  .review-card { border: 1px solid var(--line); border-left: 3px solid var(--warn); background: var(--surface); border-radius: 0 8px 8px 0; padding: .95rem 1.1rem; margin-bottom: .8rem; }
  .review-head { display: flex; align-items: center; gap: .6rem; font-family: var(--font-ui); font-size: .78rem; margin-bottom: .5rem; }
  .review-idx { font-family: var(--font-mono); color: var(--ink-faint); }
  .review-video { font-weight: 600; color: var(--accent-ink); }
  .review-triple { font-family: var(--font-mono); font-size: .86rem; margin-bottom: .5rem; }
  .review-field { font-size: .87rem; margin: .3rem 0; }
  .review-field .k { font-family: var(--font-ui); font-size: .64rem; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-faint); display: block; margin-bottom: .12rem; }
  .review-frame { font-family: var(--font-mono); font-size: .76rem; color: var(--ink-faint); word-break: break-all; }
  .review-reason { font-size: .82rem; color: var(--warn-ink); margin-top: .5rem; }
  .prose p { max-width: 70ch; margin: 0 0 1rem; }
  .prose strong { color: var(--accent-ink); font-weight: 600; }
  footer { margin-top: 3.5rem; padding-top: 1.2rem; border-top: 1px solid var(--line); color: var(--ink-faint); font-family: var(--font-ui); font-size: .78rem; }
</style>
</head>
<body>
<div class="page">
"""

HTML_TAIL = """
</div>
</body>
</html>
"""


def _bar_segments(counts: dict[str, int]) -> str:
    total = sum(counts.values())
    if total == 0:
        return ""
    segs = []
    for cat in CATEGORIES:
        n = counts[cat]
        if n <= 0:
            continue
        pct = n / total * 100
        segs.append(f'<div class="bar-seg {CATEGORY_CSS_CLASS[cat]}" style="width:{pct:.2f}%" title="{CATEGORY_LABEL[cat]}: {n}"></div>')
    return f'<div class="bar-row">{"".join(segs)}</div>'


def build_html_report(results: list[dict]) -> str:
    stats = compute_stats(results)
    total_nodes = stats["total_nodes"]
    global_counts = stats["global_counts"]
    all_review = stats["all_review"]
    skipped = stats["skipped"]

    out = [HTML_HEAD]
    out.append('<p class="eyebrow">stage7_analyze_binding.py &middot; offline re-classification</p>')
    out.append("<h1>图文绑定质量分析报告</h1>")
    out.append(
        '<p class="subtitle">读取 25 段视频已有的 <code>05_knowledge_graph.json</code>,'
        "对每条知识节点重新判定图文绑定属于四类之一,不重新调用任何 API。</p>"
    )

    out.append('<div class="meta-row">')
    out.append(f'<div class="meta-item"><span class="meta-num">{total_nodes}</span><span class="meta-label">nodes classified</span></div>')
    out.append(f'<div class="meta-item"><span class="meta-num">{len(stats["processed"])}</span><span class="meta-label">videos with nodes</span></div>')
    out.append(f'<div class="meta-item"><span class="meta-num">{len(skipped)}</span><span class="meta-label">videos skipped (0 nodes)</span></div>')
    out.append(f'<div class="meta-item"><span class="meta-num">{len(all_review)}</span><span class="meta-label">needs review</span></div>')
    out.append("</div>")

    # ---- section 1: per-video table ----
    out.append("<section>")
    out.append("<h2>1. 按视频统计</h2>")
    out.append('<p class="section-note">彩条从左到右依次为 Confirmed / Unverifiable / Narration Lag / '
                "Needs Review 四类占该视频节点数的比例,颜色定义见下方图例。</p>")
    out.append('<div class="legend">')
    for cat in CATEGORIES:
        out.append(f'<span class="legend-item"><span class="legend-dot {CATEGORY_CSS_CLASS[cat]}"></span>{CATEGORY_LABEL[cat]}</span>')
    out.append("</div>")

    out.append('<div class="table-scroll"><table><thead><tr>')
    out.append("<th>视频</th><th class=\"num\">总节点数</th><th class=\"num\">Confirmed</th>"
                "<th class=\"num\">Unverifiable</th><th class=\"num\">Narration Lag</th>"
                "<th class=\"num\">Needs Review</th><th>分布</th></tr></thead><tbody>")
    for r in results:
        c = r["counts"]
        if r["total"] == 0:
            out.append(f'<tr class="skipped"><td>{html_escape(r["label"])}</td><td class="num">0</td>'
                        '<td class="num">-</td><td class="num">-</td><td class="num">-</td>'
                        '<td class="num">-</td><td>&mdash;</td></tr>')
        else:
            out.append(
                f'<tr><td>{html_escape(r["label"])}</td><td class="num">{r["total"]}</td>'
                f'<td class="num">{c["confirmed"]}</td><td class="num">{c["unverifiable"]}</td>'
                f'<td class="num">{c["narration_lag"]}</td><td class="num">{c["needs_review"]}</td>'
                f'<td>{_bar_segments(c)}</td></tr>'
            )
    out.append("</tbody></table></div>")
    out.append("</section>")

    # ---- section 2: global stats ----
    out.append("<section>")
    out.append("<h2>2. 全局统计</h2>")
    out.append(f'<p class="section-note">25 段视频中有 {len(stats["processed"])} 段产出了知识节点,'
                f'合计 {total_nodes} 条。</p>')
    out.append('<div class="stat-grid">')
    for cat in CATEGORIES:
        n = global_counts.get(cat, 0)
        pct = (n / total_nodes * 100) if total_nodes else 0
        out.append(
            f'<div class="stat-card {cat}"><div class="n">{n}</div>'
            f'<div class="l">{CATEGORY_LABEL[cat]}</div><div class="p">{pct:.1f}%</div></div>'
        )
    out.append("</div>")
    out.append("</section>")

    # ---- section 3: needs review ----
    out.append("<section>")
    out.append("<h2>3. Needs Review 清单(需人工复核)</h2>")
    out.append(f'<p class="section-note">共 {len(all_review)} 条,按视频顺序列出,可对照“关键帧路径”打开原始截图核实。</p>')
    if not all_review:
        out.append("<p>无需要人工复核的条目。</p>")
    else:
        for i, item in enumerate(all_review, 1):
            out.append('<div class="review-card">')
            out.append(
                f'<div class="review-head"><span class="review-idx">#{i}</span>'
                f'<span class="review-video">{html_escape(item["video"])}</span></div>'
            )
            out.append(f'<div class="review-triple">{html_escape(format_triple(item["triple"]))}</div>')
            out.append(f'<div class="review-field"><span class="k">原文讲解</span>{html_escape(item["text_evidence"])}</div>')
            out.append(f'<div class="review-field"><span class="k">图像描述</span>{html_escape(item["vlm_description"])}</div>')
            out.append(f'<div class="review-field review-frame"><span class="k">关键帧路径</span>{html_escape(item["frame_path"])}</div>')
            out.append(f'<div class="review-reason">{html_escape(item["reason"])}</div>')
            out.append("</div>")
    out.append("</section>")

    # ---- section 4: conclusion ----
    out.append("<section>")
    out.append("<h2>4. 总体结论</h2>")
    out.append('<div class="prose">')
    if total_nodes > 0:
        dominant = stats["dominant"]
        dominant_pct = global_counts[dominant] / total_nodes * 100
        out.append(
            f"<p>这批 {total_nodes} 条知识节点里,<strong>{CATEGORY_LABEL[dominant]}</strong> "
            f"占比最高({dominant_pct:.1f}%)。整体来看,这套图文绑定流程能可靠验证的是画面里"
            f"<strong>看得见的定性物理状态</strong>——形状、颜色、结构、积水/变色/撕裂这类肉眼可"
            f"判断的现象;验证不了的是<strong>定量数值和化学成分</strong>——厚度、载量、膜型号这类"
            f"信息,静态画面天然给不出答案,这不是流程缺陷,是方法本身的能力边界。"
            f"Narration Lag 反映的是关键帧定位与讲解存在几秒级的时间差,本质是抽帧时机问题,不是"
            f"内容错误。真正值得警惕的是 Needs Review 里的条目——要么 VLM 明确给出了和文本相悖的"
            f"具体观察,要么证据描述本身缺失或被截断到无法判断,这两种都需要人工对照原始视频画面"
            f"复核。</p>"
        )
    out.append("</div>")
    out.append("</section>")

    out.append('<footer>生成脚本:stage7_analyze_binding.py &middot; 数据来源:outputs_batch/*/05_knowledge_graph.json &middot; 不调用任何 API</footer>')
    out.append(HTML_TAIL)
    return "\n".join(out)


def run(outputs_batch_dir: Path) -> None:
    video_dirs = sorted(
        p for p in outputs_batch_dir.iterdir()
        if p.is_dir() and (p / "05_knowledge_graph.json").exists()
    )
    logger.info("Found %d video output directories under %s", len(video_dirs), outputs_batch_dir)

    results = []
    for video_dir in video_dirs:
        kg_path = video_dir / "05_knowledge_graph.json"
        result = analyze_video(video_dir.name, kg_path)
        logger.info(
            "%s: total=%d confirmed=%d unverifiable=%d narration_lag=%d needs_review=%d",
            result["label"], result["total"], result["counts"]["confirmed"],
            result["counts"]["unverifiable"], result["counts"]["narration_lag"],
            result["counts"]["needs_review"],
        )
        results.append(result)

    report = build_report(results)
    out_path = outputs_batch_dir / "binding_analysis_summary.md"
    out_path.write_text(report, encoding="utf-8")
    logger.info("Saved report -> %s", out_path)

    html_report = build_html_report(results)
    html_path = outputs_batch_dir / "binding_analysis_summary.html"
    html_path.write_text(html_report, encoding="utf-8")
    logger.info("Saved report -> %s", html_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze image/text binding quality across all batch-processed videos")
    parser.add_argument(
        "--outputs-batch-dir", type=Path,
        default=config.PROJECT_ROOT / "outputs_batch",
        help="Directory containing one subfolder per video, each with 05_knowledge_graph.json",
    )
    args = parser.parse_args()
    run(args.outputs_batch_dir)


if __name__ == "__main__":
    main()
