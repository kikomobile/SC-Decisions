"""Interactive pyvis visualization with Louvain community detection coloring."""

import io
import json
import math

import networkx as nx
from pyvis.network import Network

from .appointed_by import PRESIDENT_COLORS, FALLBACK_COLOR


BG_COLOR = "#111111"

# 12 bright colors optimized for dark backgrounds
COMMUNITY_COLORS = [
    "#ff4d6a",  # neon pink-red
    "#4dff91",  # neon green
    "#4d8bff",  # neon blue
    "#ffaa33",  # neon orange
    "#bb66ff",  # neon purple
    "#33eeff",  # neon cyan
    "#ff55cc",  # neon magenta
    "#ccff44",  # neon lime
    "#ff88aa",  # neon rose
    "#44ddaa",  # neon teal
    "#cc99ff",  # neon lavender
    "#ffcc44",  # neon gold
]


def _format_label(name: str, max_line_len: int = 14) -> str:
    """Insert a line break for names longer than max_line_len characters."""
    if len(name) <= max_line_len:
        return name
    mid = len(name) // 2
    hyphen_positions = [i for i, c in enumerate(name) if c == '-']
    if hyphen_positions:
        best = min(hyphen_positions, key=lambda p: abs(p - mid))
        return name[:best + 1] + "\n" + name[best + 1:]
    space_positions = [i for i, c in enumerate(name) if c == ' ']
    if space_positions:
        best = min(space_positions, key=lambda p: abs(p - mid))
        return name[:best] + "\n" + name[best + 1:]
    return name


def _darken_hex(hex_color: str, factor: float = 0.3) -> str:
    """Darken a hex color by the given factor (0-1)."""
    hex_color = hex_color.lstrip('#')
    r = int(int(hex_color[0:2], 16) * (1 - factor))
    g = int(int(hex_color[2:4], 16) * (1 - factor))
    b = int(int(hex_color[4:6], 16) * (1 - factor))
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color to (r, g, b) tuple."""
    hex_color = hex_color.lstrip('#')
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def _resolve_node_colors(
    G: nx.Graph,
    node_community: dict,
    color_mode: str,
    appointed_by_map: dict | None,
) -> tuple[dict, dict, list]:
    """Resolve per-node color and group label based on color mode.

    Returns:
        node_color: {node: hex_color}
        node_group_label: {node: str} — community index or president name
        legend_entries: [(label, hex_color), ...] sorted for legend display
    """
    node_color = {}
    node_group_label = {}

    if color_mode == "appointed_by" and appointed_by_map:
        for node in G.nodes:
            president = appointed_by_map.get(node, "Unknown")
            color = PRESIDENT_COLORS.get(president, FALLBACK_COLOR)
            node_color[node] = color
            node_group_label[node] = president

        # Legend: presidents actually present, sorted by frequency
        from collections import Counter
        counts = Counter(node_group_label.values())
        legend_entries = [
            (pres, PRESIDENT_COLORS.get(pres, FALLBACK_COLOR))
            for pres, _ in counts.most_common()
        ]
    else:
        for node in G.nodes:
            comm = node_community.get(node, 0)
            color = COMMUNITY_COLORS[comm % len(COMMUNITY_COLORS)]
            node_color[node] = color
            node_group_label[node] = str(comm)

        # Legend: communities sorted by size
        from collections import Counter
        counts = Counter(node_group_label.values())
        legend_entries = [
            (f"Community {c} ({cnt})", COMMUNITY_COLORS[int(c) % len(COMMUNITY_COLORS)])
            for c, cnt in counts.most_common(8)
        ]

    return node_color, node_group_label, legend_entries


def _compute_community_positions(
    G: nx.Graph, communities: list, width: float = 1000, height: float = 700,
) -> dict:
    """Compute node positions with community-clustered starting points.

    Places community centroids on a circle, jitters members around each,
    then refines with spring_layout. Returns {node: (x, y)} in pixel coords.
    """
    n_comm = len(communities)
    initial_pos = {}
    radius = 3.0
    for i, comm in enumerate(communities):
        angle = 2 * math.pi * i / max(n_comm, 1)
        cx = math.cos(angle) * radius
        cy = math.sin(angle) * radius
        for j, node in enumerate(sorted(comm)):
            jitter_angle = 2 * math.pi * j / max(len(comm), 1)
            initial_pos[node] = (
                cx + math.cos(jitter_angle) * 0.5,
                cy + math.sin(jitter_angle) * 0.5,
            )

    pos = nx.spring_layout(
        G, pos=initial_pos,
        k=2.0 / math.sqrt(max(G.number_of_nodes(), 1)),
        iterations=150, seed=42, weight="weight",
    )

    pad = 80
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_range = x_max - x_min or 1
    y_range = y_max - y_min or 1
    return {
        node: (
            int(pad + (x - x_min) / x_range * (width - 2 * pad)),
            int(pad + (y - y_min) / y_range * (height - 2 * pad)),
        )
        for node, (x, y) in pos.items()
    }


def build_pyvis_html(
    G: nx.Graph,
    edge_threshold: int = 0,
    node_size_by: str = "weighted_degree",
    curved_edges: bool = True,
    opacity_scaling: bool = True,
    layout_mode: str = "community",
    graph_height: int = 700,
    color_mode: str = "community",
    appointed_by_map: dict | None = None,
) -> str:
    """Build an interactive pyvis HTML string from a NetworkX graph.

    Args:
        G: Justice co-voting graph with 'weight' edge attr and 'case_count' node attr.
        edge_threshold: Only display edges with weight >= this value.
        node_size_by: One of "weighted_degree", "case_count", "uniform".
        curved_edges: Use curved edges to reduce overlap.
        opacity_scaling: Scale edge opacity by weight.
        layout_mode: "community" for pre-computed clustered layout, "physics" for interactive.
        graph_height: Height of the graph canvas in pixels.
        color_mode: "community" for Louvain coloring, "appointed_by" for president coloring.
        appointed_by_map: {node_name: president_name} for appointed_by mode.

    Returns:
        HTML string suitable for st.components.v1.html().
    """
    if G.number_of_nodes() == 0:
        return f"<p style='color:#ccc;background:{BG_COLOR}'>No nodes in graph.</p>"

    # --- Community detection ---
    communities = nx.community.louvain_communities(G, weight="weight", seed=42)
    node_community = {}
    for idx, comm in enumerate(communities):
        for node in comm:
            node_community[node] = idx

    # --- Resolve colors ---
    node_color, node_group_label, _ = _resolve_node_colors(
        G, node_community, color_mode, appointed_by_map,
    )

    # --- Layout ---
    if layout_mode == "community":
        positions = _compute_community_positions(G, communities)
    else:
        positions = None

    # --- Compute node sizes ---
    if node_size_by == "weighted_degree":
        raw = dict(G.degree(weight="weight"))
    elif node_size_by == "case_count":
        raw = {n: G.nodes[n].get("case_count", 1) for n in G.nodes}
    else:  # uniform
        raw = {n: 1 for n in G.nodes}

    max_val = max(raw.values()) if raw else 1
    min_size, max_size = 30, 70

    def scale(v):
        if max_val <= 1:
            return (min_size + max_size) / 2
        return min_size + (v / max_val) * (max_size - min_size)

    # --- Build pyvis Network ---
    height_str = f"{graph_height}px"
    net = Network(height=height_str, width="100%", bgcolor=BG_COLOR, font_color="#ffffff")

    if layout_mode == "community":
        opts = {"physics": {"enabled": False}}
        if curved_edges:
            opts["edges"] = {"smooth": {"enabled": True, "type": "curvedCW"}}
        net.set_options(json.dumps(opts))
    else:
        net.force_atlas_2based(
            gravity=-80, central_gravity=0.005, spring_length=200,
            spring_strength=0.02, damping=0.4, overlap=1,
        )
        if curved_edges:
            net.set_edge_smooth("curvedCW")

    # --- Add nodes ---
    for node in G.nodes:
        color = node_color[node]
        group_label = node_group_label[node]
        r, g, b = _hex_to_rgb(color)
        size = scale(raw[node])
        case_count = G.nodes[node].get("case_count", 0)
        degree = G.degree(node, weight="weight")
        if color_mode == "appointed_by":
            title = f"{node}\nAppointed by: {group_label}\nCases: {case_count}\nDegree: {degree}"
        else:
            title = f"{node}\nCases: {case_count}\nDegree: {degree}\nCommunity: {group_label}"
        label = _format_label(node)
        font_size = max(8, int(size * 0.28))
        node_kwargs = dict(
            label=label, title=title, size=size, shape="circle",
            color={
                "background": _darken_hex(color, 0.15),
                "border": color,
                "highlight": {"background": color, "border": "#ffffff"},
                "hover": {"background": color, "border": "#ffffff"},
            },
            font={"size": font_size, "color": "#ffffff", "face": "arial",
                  "multi": True, "strokeWidth": 0},
            borderWidth=2,
            shadow={
                "enabled": True,
                "color": f"rgba({r},{g},{b},0.55)",
                "size": 18, "x": 0, "y": 0,
            },
        )
        if positions and node in positions:
            node_kwargs["x"] = positions[node][0]
            node_kwargs["y"] = positions[node][1]
            node_kwargs["physics"] = False
        net.add_node(node, **node_kwargs)

    # --- Edge filtering and scaling ---
    max_weight = max((d["weight"] for _, _, d in G.edges(data=True)), default=1)
    for u, v, d in G.edges(data=True):
        w = d["weight"]
        if w < edge_threshold:
            continue
        width = max(0.5, w / max_weight * 5)

        if opacity_scaling:
            alpha = max(0.10, min(0.85, w / max_weight))
        else:
            alpha = 0.5

        # Edge color: same-group edges use group color, cross-group edges grey
        grp_u = node_group_label.get(u, "")
        grp_v = node_group_label.get(v, "")
        if grp_u == grp_v and grp_u:
            base = node_color[u]
            r, g, b = _hex_to_rgb(base)
            edge_color = f"rgba({r},{g},{b},{alpha:.2f})"
        else:
            edge_color = f"rgba(100,100,120,{alpha:.2f})"

        # Glow on strong edges via shadow
        use_shadow = w / max_weight > 0.4
        net.add_edge(
            u, v, width=width, title=f"Weight: {w}",
            color={"color": edge_color, "highlight": "#ffffff", "hover": "#dddddd"},
            shadow={
                "enabled": use_shadow,
                "color": edge_color,
                "size": 6, "x": 0, "y": 0,
            } if use_shadow else {"enabled": False},
        )

    html = net.generate_html()

    # Inject resize observer so the vis.js canvas auto-fills its container
    resize_script = """
<script>
(function() {
    var container = document.getElementById('mynetwork');
    if (!container) return;
    function resize() {
        container.style.height = window.innerHeight + 'px';
    }
    window.addEventListener('resize', resize);
})();
</script>
"""
    html = html.replace("</body>", resize_script + "</body>")
    return html


def get_community_summary(G: nx.Graph) -> list[dict]:
    """Return community membership summary sorted by size descending.

    Returns:
        List of {"community": int, "members": [...], "size": int}.
    """
    if G.number_of_nodes() == 0:
        return []

    communities = nx.community.louvain_communities(G, weight="weight", seed=42)
    result = []
    for idx, comm in enumerate(communities):
        members = sorted(comm)
        result.append({"community": idx, "members": members, "size": len(members)})
    result.sort(key=lambda x: -x["size"])
    return result


def build_matplotlib_figure(
    G: nx.Graph,
    edge_threshold: int = 0,
    node_size_by: str = "weighted_degree",
    opacity_scaling: bool = True,
    figsize: tuple = (14, 10),
    dpi: int = 150,
    color_mode: str = "community",
    appointed_by_map: dict | None = None,
):
    """Build a static matplotlib figure of the justice network.

    Uses same community detection, coloring, and layout as the PyVis version.
    Dark background with glow effects for depth.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.patheffects as pe

    if G.number_of_nodes() == 0:
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        fig.set_facecolor(BG_COLOR)
        ax.set_facecolor(BG_COLOR)
        ax.text(0.5, 0.5, "No nodes in graph", ha="center", va="center",
                fontsize=16, color="#cccccc")
        ax.axis("off")
        return fig

    # Community detection (same seed as PyVis version)
    communities = nx.community.louvain_communities(G, weight="weight", seed=42)
    node_community = {}
    for idx, comm in enumerate(communities):
        for node in comm:
            node_community[node] = idx

    # Resolve colors
    node_color_map, node_group_label, legend_entries = _resolve_node_colors(
        G, node_community, color_mode, appointed_by_map,
    )

    # Node sizes (matplotlib area units)
    if node_size_by == "weighted_degree":
        raw = dict(G.degree(weight="weight"))
    elif node_size_by == "case_count":
        raw = {n: G.nodes[n].get("case_count", 1) for n in G.nodes}
    else:
        raw = {n: 1 for n in G.nodes}
    max_val = max(raw.values()) if raw else 1
    min_s, max_s = 300, 2000

    def scale(v):
        if max_val <= 1:
            return (min_s + max_s) / 2
        return min_s + (v / max_val) * (max_s - min_s)

    node_list = list(G.nodes)
    node_sizes = [scale(raw[n]) for n in node_list]
    node_colors = [node_color_map[n] for n in node_list]

    # Layout: community-aware spring layout (same algorithm as PyVis)
    n_comm = len(communities)
    initial_pos = {}
    radius = 3.0
    for i, comm in enumerate(communities):
        angle = 2 * math.pi * i / max(n_comm, 1)
        cx = math.cos(angle) * radius
        cy = math.sin(angle) * radius
        for j, node in enumerate(sorted(comm)):
            jitter_angle = 2 * math.pi * j / max(len(comm), 1)
            initial_pos[node] = (
                cx + math.cos(jitter_angle) * 0.5,
                cy + math.sin(jitter_angle) * 0.5,
            )
    pos = nx.spring_layout(
        G, pos=initial_pos,
        k=2.0 / math.sqrt(max(G.number_of_nodes(), 1)),
        iterations=150, seed=42, weight="weight",
    )

    # Filter edges
    max_weight = max((d["weight"] for _, _, d in G.edges(data=True)), default=1)
    filtered_edges = [
        (u, v, d) for u, v, d in G.edges(data=True) if d["weight"] >= edge_threshold
    ]

    # Draw
    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)
    fig.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    # Edges — draw glow layer behind strong edges, then the edge itself
    for u, v, d in filtered_edges:
        w = d["weight"]
        width = max(0.3, w / max_weight * 3)
        if opacity_scaling:
            alpha = max(0.08, min(0.7, w / max_weight))
        else:
            alpha = 0.4
        grp_u = node_group_label.get(u, "")
        grp_v = node_group_label.get(v, "")
        if grp_u == grp_v and grp_u:
            color = node_color_map[u]
        else:
            color = "#667788"
        xs = [pos[u][0], pos[v][0]]
        ys = [pos[u][1], pos[v][1]]
        strength = w / max_weight
        if strength > 0.3:
            ax.plot(xs, ys, color=color, alpha=alpha * 0.3,
                    linewidth=width + 3, zorder=0, solid_capstyle="round")
        ax.plot(xs, ys, color=color, alpha=alpha, linewidth=width, zorder=1)

    # Node glow layer (larger, faint circles behind each node)
    for i, node in enumerate(node_list):
        x, y = pos[node]
        color = node_colors[i]
        glow_size = node_sizes[i] * 1.8
        ax.scatter(x, y, s=glow_size, c=color,
                   alpha=0.15, edgecolors="none", zorder=1)

    # Nodes
    nx.draw_networkx_nodes(
        G, pos, ax=ax, nodelist=node_list,
        node_size=node_sizes,
        node_color=[_darken_hex(c, 0.10) for c in node_colors],
        edgecolors=node_colors,
        linewidths=2.0,
    )

    # Labels inside nodes
    for node in node_list:
        x, y = pos[node]
        label = _format_label(node, max_line_len=14)
        area = scale(raw[node])
        font_size = max(5, min(9, area / 200))
        ax.text(
            x, y, label, ha="center", va="center",
            fontsize=font_size, color="white", fontweight="bold", zorder=3,
            path_effects=[pe.withStroke(linewidth=2, foreground="black")],
        )

    # Legend (styled for dark background)
    legend_handles = []
    for lbl, color in legend_entries[:12]:
        patch = mpatches.Patch(color=color, label=lbl)
        legend_handles.append(patch)
    if legend_handles:
        legend = ax.legend(
            handles=legend_handles, loc="upper left", fontsize=8,
            facecolor="#222222", edgecolor="#444444", labelcolor="#dddddd",
            framealpha=0.9,
        )
        legend.get_frame().set_linewidth(0.8)

    ax.axis("off")
    fig.tight_layout(pad=0.5)
    return fig


def export_figure_bytes(fig, fmt: str = "png", dpi: int = 150) -> bytes:
    """Export a matplotlib figure to bytes (PNG or SVG)."""
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    return buf.getvalue()
