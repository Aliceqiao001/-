"""Stage 6 (optional): turn the flat triple list into an actual graph and
visualize it.

Runs standalone: `python stage6_visualize_kg.py`
Reads:  config.KNOWLEDGE_GRAPH_PATH (outputs/05_knowledge_graph.json)
Writes: config.KG_PNG_PATH  (outputs/knowledge_graph.png)  - static overview
        config.KG_HTML_PATH (outputs/knowledge_graph.html) - interactive, draggable

Nodes are entity strings (subject/object) - the same string always maps to
the same node, so repeated entities (e.g. "cathode gasket" appearing in
several triples) collapse naturally instead of duplicating.

`conflict: true` edges are NOT styled as errors. Per the pipeline's own
findings, the flagged conflicts are narration-precedes-action lag (the
narrator describes a step slightly before/after the frame that got sampled
for it), not real text/image contradictions - so they get a neutral dashed
style with a plain annotation instead of warning colors.
"""
from __future__ import annotations

import math
import re
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
import networkx as nx
from pyvis.network import Network

import config
from utils.io_utils import load_json

logger = config.setup_logging("stage6_visualize_kg")

CATEGORY_COLORS = {
    "cathode": "#4C72B0",
    "anode": "#DD8452",
    "middle_chamber": "#55A868",
    "gas_param": "#8172B2",
    "other": "#B0B0B0",
}
CATEGORY_LABELS = {
    "cathode": "阴极相关",
    "anode": "阳极相关",
    "middle_chamber": "中间腔室相关",
    "gas_param": "气体/参数值",
    "other": "其他",
}

MIDDLE_KEYWORDS = ["middle chamber", "electrolyte", "resin", "particle size"]
GAS_PARAM_KEYWORDS = [
    "gas", "hydrogen", "newton", "micrometer", "milligram", "centimeter",
    "loading", "actual area", "%",
]

CONFLICT_NOTE = "narration precedes/follows action (not a data conflict)"


def _classify(entity: str) -> str:
    lower = entity.lower()
    if "cathode" in lower:
        return "cathode"
    if "anode" in lower:
        return "anode"
    if any(k in lower for k in MIDDLE_KEYWORDS):
        return "middle_chamber"
    if any(k in lower for k in GAS_PARAM_KEYWORDS) or re.search(r"\d", lower):
        return "gas_param"
    return "other"


def _wrap(text: str, width: int = 16) -> str:
    return "\n".join(textwrap.wrap(text, width=width)) or text


def build_graph(kg_nodes: list[dict]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for node in kg_nodes:
        subj, rel, obj = node["triple"]
        for entity in (subj, obj):
            if entity not in graph:
                graph.add_node(entity, category=_classify(entity))
        graph.add_edge(
            subj, obj,
            relation=rel,
            confidence=node["confidence"],
            conflict=node["conflict"],
            timestamp=node["timestamp"],
            text_evidence=node["text_evidence"],
            image_evidence=node.get("image_evidence"),
        )
    return graph


def _layout_by_component(graph: nx.MultiDiGraph, cell_size: float = 4.2) -> dict:
    """This knowledge graph is highly fragmented (most triples are isolated
    subject->object pairs sharing no entities with other triples), so a
    single force-directed layout over the whole graph either crushes
    everything into one clump or flings disconnected pairs to random
    distances - neither is readable. Laying out each connected component on
    its own and then tiling the components on a grid keeps every component
    internally well-spaced and guarantees components never overlap.
    """
    components = sorted(nx.weakly_connected_components(graph), key=len, reverse=True)
    n_cols = max(1, math.ceil(math.sqrt(len(components))))

    pos: dict = {}
    for i, comp_nodes in enumerate(components):
        sub = graph.subgraph(comp_nodes)
        if len(comp_nodes) == 1:
            local_pos = {next(iter(comp_nodes)): (0.0, 0.0)}
        else:
            local_pos = nx.spring_layout(sub, k=2.4 / (len(comp_nodes) ** 0.5), iterations=300, seed=3)

        xs = [p[0] for p in local_pos.values()]
        ys = [p[1] for p in local_pos.values()]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        # bigger components get proportionally more room instead of being
        # squeezed into the same footprint as an isolated 2-node pair
        scale = 0.8 * math.sqrt(len(comp_nodes))

        scaled = {n: ((x - cx) / span * scale, (y - cy) / span * scale) for n, (x, y) in local_pos.items()}
        scaled = _resolve_overlaps(scaled, min_dist=0.9)

        row, col = divmod(i, n_cols)
        offset_x, offset_y = col * cell_size, -row * cell_size
        for node, (x, y) in scaled.items():
            pos[node] = (x + offset_x, y + offset_y)
    return pos


def _resolve_overlaps(pos: dict, min_dist: float, iterations: int = 80) -> dict:
    """Force-directed layouts can converge with two connected "hub" nodes
    sitting almost on top of each other when their neighbors pull evenly
    from both sides. Nudge any pair closer than `min_dist` apart along the
    line between them until everything clears the minimum spacing.
    """
    nodes = list(pos.keys())
    coords = {n: list(p) for n, p in pos.items()}
    for _ in range(iterations):
        moved = False
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                dx = coords[b][0] - coords[a][0]
                dy = coords[b][1] - coords[a][1]
                dist = math.hypot(dx, dy) or 1e-6
                if dist < min_dist:
                    moved = True
                    push = (min_dist - dist) / 2
                    ux, uy = dx / dist, dy / dist
                    coords[a][0] -= ux * push
                    coords[a][1] -= uy * push
                    coords[b][0] += ux * push
                    coords[b][1] += uy * push
        if not moved:
            break
    return {n: tuple(p) for n, p in coords.items()}


def _confidence_color(confidence: float) -> tuple:
    # low confidence -> light gray, high confidence -> solid dark blue
    cmap = plt.get_cmap("Blues")
    return cmap(0.3 + 0.6 * confidence)


def draw_static_png(graph: nx.MultiDiGraph, path) -> None:
    plt.figure(figsize=(26, 20))
    pos = _layout_by_component(graph)

    for category, color in CATEGORY_COLORS.items():
        nodes = [n for n, d in graph.nodes(data=True) if d["category"] == category]
        if nodes:
            nx.draw_networkx_nodes(graph, pos, nodelist=nodes, node_color=color, node_size=2200, alpha=0.9)

    for u, v, key, data in graph.edges(keys=True, data=True):
        color = _confidence_color(data["confidence"])
        width = 1.0 + data["confidence"] * 3.0
        style = "dashed" if data["conflict"] else "solid"
        nx.draw_networkx_edges(
            graph, pos, edgelist=[(u, v)], width=width, edge_color=[color],
            style=style, arrows=True, arrowsize=18, connectionstyle="arc3,rad=0.08",
            min_source_margin=25, min_target_margin=25,
        )

    label_bbox = dict(facecolor="white", edgecolor="none", alpha=0.75, boxstyle="round,pad=0.15")
    nx.draw_networkx_labels(
        graph, pos,
        labels={n: _wrap(n) for n in graph.nodes()},
        font_size=9, font_family="sans-serif", bbox=label_bbox,
    )

    edge_labels = {}
    for u, v, data in graph.edges(data=True):
        label = _wrap(data["relation"], width=20)
        if data["conflict"]:
            label += "\n(narration lag)"
        edge_labels[(u, v)] = label
    nx.draw_networkx_edge_labels(
        graph, pos, edge_labels=edge_labels, font_size=7, font_color="#444444",
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.65, boxstyle="round,pad=0.1"),
    )

    legend_handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=color, markersize=14, label=CATEGORY_LABELS[cat])
        for cat, color in CATEGORY_COLORS.items()
    ]
    legend_handles.append(plt.Line2D([0], [0], color="gray", lw=2, linestyle="dashed", label="narration lag (not a real conflict)"))
    plt.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=11, framealpha=0.9)

    plt.title("反应釜装配知识图谱 (edge width/color = confidence)", fontsize=16)
    plt.axis("off")
    plt.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()


def _truncate(text: str, n: int = 160) -> str:
    return text if len(text) <= n else text[: n - 3] + "..."


def build_interactive_html(graph: nx.MultiDiGraph, path) -> None:
    net = Network(height="900px", width="100%", directed=True, notebook=False,
                  cdn_resources="in_line", bgcolor="#ffffff", font_color="#222222")
    net.barnes_hut(gravity=-6000, spring_length=180, spring_strength=0.02, damping=0.25)

    for n, data in graph.nodes(data=True):
        net.add_node(
            n, label=n, color=CATEGORY_COLORS[data["category"]],
            title=f"<b>{n}</b><br>类别: {CATEGORY_LABELS[data['category']]}",
            shape="dot", size=18,
        )

    for u, v, data in graph.edges(data=True):
        frame_path = (data.get("image_evidence") or {}).get("frame_path", "N/A")
        title = (
            f"<b>{data['relation']}</b><br>"
            f"confidence: {data['confidence']}<br>"
            f"timestamp: {data['timestamp']}<br>"
            f"evidence: {_truncate(data['text_evidence'])}<br>"
            f"frame: {frame_path}"
        )
        if data["conflict"]:
            title += f"<br><i>note: {CONFLICT_NOTE}</i>"
        net.add_edge(
            u, v, label=data["relation"], title=title,
            color=f"rgba(70,70,70,{0.3 + 0.6 * data['confidence']:.2f})",
            width=1 + data["confidence"] * 3,
            dashes=bool(data["conflict"]),
            arrows="to",
        )

    # net.write_html() opens the file with the OS default encoding (gbk on
    # Chinese Windows), which chokes on the bundled vis.js license text when
    # cdn_resources="in_line". Generate the HTML ourselves and write it as
    # utf-8 explicitly.
    html = net.generate_html(notebook=False)
    path.write_text(html, encoding="utf-8")


def run() -> nx.MultiDiGraph:
    kg_nodes = load_json(config.KNOWLEDGE_GRAPH_PATH)
    graph = build_graph(kg_nodes)

    logger.info("Graph built: %d nodes, %d edges", graph.number_of_nodes(), graph.number_of_edges())

    draw_static_png(graph, config.KG_PNG_PATH)
    logger.info("Saved static PNG -> %s", config.KG_PNG_PATH)

    build_interactive_html(graph, config.KG_HTML_PATH)
    logger.info("Saved interactive HTML -> %s", config.KG_HTML_PATH)

    return graph


if __name__ == "__main__":
    run()
