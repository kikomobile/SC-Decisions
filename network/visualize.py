"""Interactive pyvis visualization with Louvain community detection coloring."""

import io
import json
import math

import networkx as nx
from pyvis.network import Network

from .appointed_by import PRESIDENT_COLORS, FALLBACK_COLOR


BG_COLOR = "#ffffff"

# 12 colors optimized for white backgrounds (matches dissent chart palette)
COMMUNITY_COLORS = [
    "#e879a0",  # soft pink
    "#10b981",  # emerald green
    "#3b82f6",  # blue
    "#f59e0b",  # amber
    "#8b5cf6",  # violet
    "#22b8cf",  # teal cyan
    "#ec4899",  # pink
    "#eab308",  # gold
    "#6366f1",  # indigo
    "#14b8a6",  # teal
    "#f97316",  # orange
    "#64748b",  # slate
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

        # Legend: presidents actually present, in chronological order
        _PRESIDENT_ORDER = [
            "Ferdinand Marcos", "Corazon Aquino", "Fidel V. Ramos",
            "Joseph Estrada", "Gloria Macapagal Arroyo",
            "Benigno Aquino III", "Rodrigo Duterte", "Bongbong Marcos",
        ]
        present = set(node_group_label.values())
        legend_entries = [
            (pres, PRESIDENT_COLORS.get(pres, FALLBACK_COLOR))
            for pres in _PRESIDENT_ORDER if pres in present
        ]
        # Append any present presidents not in the ordered list (e.g. older eras)
        for pres in sorted(present):
            if pres not in dict(legend_entries):
                legend_entries.append(
                    (pres, PRESIDENT_COLORS.get(pres, FALLBACK_COLOR))
                )
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


def _resolve_overlaps(
    pos: dict, node_sizes: dict, padding: float = 12, iterations: int = 80,
) -> dict:
    """Push overlapping nodes apart based on their vis.js pixel sizes."""
    nodes = list(pos.keys())
    # Work on mutable copies
    px = {n: float(pos[n][0]) for n in nodes}
    py = {n: float(pos[n][1]) for n in nodes}
    for _ in range(iterations):
        moved = False
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                dx = px[b] - px[a]
                dy = py[b] - py[a]
                dist = math.sqrt(dx * dx + dy * dy) or 0.1
                min_dist = (node_sizes.get(a, 40) + node_sizes.get(b, 40)) / 2 + padding
                if dist < min_dist:
                    overlap = (min_dist - dist) / 2
                    ux, uy = dx / dist, dy / dist
                    px[a] -= ux * overlap
                    py[a] -= uy * overlap
                    px[b] += ux * overlap
                    py[b] += uy * overlap
                    moved = True
        if not moved:
            break
    return {n: (px[n], py[n]) for n in nodes}


def _compute_community_positions(
    G: nx.Graph, communities: list, graph_height: int = 700,
    node_sizes: dict | None = None,
    centroid_radius_base: float = 10.0,
    jitter_scale: float = 0.25,
    repulsion_k: float = 8.0,
) -> dict:
    """Compute node positions with community-clustered starting points.

    Places community centroids on a circle, jitters members around each,
    then refines with spring_layout. Resolves overlaps using actual node
    sizes. Returns {node: (x, y)} in pixel coords.
    """
    N = max(G.number_of_nodes(), 1)
    n_comm = len(communities)

    # Scale output pixel space with node count so nodes don't crowd
    avg_size = 50
    if node_sizes:
        avg_size = sum(node_sizes.values()) / max(len(node_sizes), 1)
    spacing = max(28, avg_size * 0.7)
    width = max(1800, int(N * spacing))
    height = max(int(graph_height * 1.8), int(N * spacing * 0.7))

    # Large centroid radius keeps communities well separated
    centroid_radius = centroid_radius_base + n_comm * 1.0
    initial_pos = {}
    for i, comm in enumerate(communities):
        angle = 2 * math.pi * i / max(n_comm, 1)
        cx = math.cos(angle) * centroid_radius
        cy = math.sin(angle) * centroid_radius
        # Jitter radius scales with community size
        jitter_r = 0.6 + math.sqrt(len(comm)) * jitter_scale
        for j, node in enumerate(sorted(comm)):
            jitter_angle = 2 * math.pi * j / max(len(comm), 1)
            initial_pos[node] = (
                cx + math.cos(jitter_angle) * jitter_r,
                cy + math.sin(jitter_angle) * jitter_r,
            )

    # Higher k = more repulsion between nodes; prevents overlap
    pos = nx.spring_layout(
        G, pos=initial_pos,
        k=repulsion_k / math.sqrt(N),
        iterations=200, seed=42, weight="weight",
    )

    # Scale to pixel coordinates
    pad = 100
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_range = x_max - x_min or 1
    y_range = y_max - y_min or 1
    pixel_pos = {
        node: (
            pad + (x - x_min) / x_range * (width - 2 * pad),
            pad + (y - y_min) / y_range * (height - 2 * pad),
        )
        for node, (x, y) in pos.items()
    }

    # Push apart any remaining overlaps using actual node sizes
    if node_sizes:
        pixel_pos = _resolve_overlaps(pixel_pos, node_sizes)

    return {n: (int(px), int(py)) for n, (px, py) in pixel_pos.items()}


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
    show_community_hulls: bool = False,
    centroid_radius_base: float = 10.0,
    jitter_scale: float = 0.25,
    repulsion_k: float = 8.0,
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
        show_community_hulls: Draw convex hull boundaries around Louvain communities.
        centroid_radius_base: Base radius for community centroid placement.
        jitter_scale: Scale factor for intra-community member jitter.
        repulsion_k: Spring layout repulsion constant.

    Returns:
        HTML string suitable for st.components.v1.html().
    """
    if G.number_of_nodes() == 0:
        return f"<p style='color:#666;background:{BG_COLOR}'>No nodes in graph.</p>"

    # --- Community detection ---
    communities = nx.community.louvain_communities(G, weight="weight", seed=42)
    node_community = {}
    for idx, comm in enumerate(communities):
        for node in comm:
            node_community[node] = idx

    # --- Resolve colors ---
    node_color, node_group_label, legend_entries = _resolve_node_colors(
        G, node_community, color_mode, appointed_by_map,
    )

    # --- Compute node sizes (before layout so positions account for size) ---
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

    node_sizes = {n: scale(raw[n]) for n in G.nodes}

    # --- Layout ---
    if layout_mode == "community":
        positions = _compute_community_positions(
            G, communities, graph_height, node_sizes,
            centroid_radius_base=centroid_radius_base,
            jitter_scale=jitter_scale,
            repulsion_k=repulsion_k,
        )
    else:
        positions = None

    # --- Build pyvis Network ---
    height_str = f"{graph_height}px"
    net = Network(height=height_str, width="100%", bgcolor=BG_COLOR, font_color="#1a1a1a")

    if layout_mode == "community":
        opts = {"physics": {"enabled": False}}
        if curved_edges:
            opts["edges"] = {"smooth": {"enabled": True, "type": "curvedCW"}}
        net.set_options(json.dumps(opts))
    else:
        # Map community separation sliders to physics engine params:
        #   centroid_radius_base → gravity (more radius = stronger repulsion)
        #   jitter_scale → spring_length (more jitter = longer springs)
        #   repulsion_k → spring_strength inverse (more repulsion = weaker springs)
        phys_gravity = -30 - centroid_radius_base * 5          # 10→-80, 30→-180
        phys_spring_len = int(100 + jitter_scale * 400)        # 0.25→200, 1.0→500
        phys_spring_str = max(0.005, 0.04 - repulsion_k * 0.002)  # 8→0.024, 20→0.005
        physics_opts = {
            "physics": {
                "forceAtlas2Based": {
                    "gravitationalConstant": phys_gravity,
                    "centralGravity": 0.01,
                    "springLength": phys_spring_len,
                    "springConstant": phys_spring_str,
                    "avoidOverlap": 0.8,
                },
                "solver": "forceAtlas2Based",
                "damping": 0.93,
                "stabilization": {
                    "enabled": True,
                    "iterations": 500,
                    "updateInterval": 25,
                },
                "maxVelocity": 15,
            },
        }
        if curved_edges:
            physics_opts["edges"] = {"smooth": {"enabled": True, "type": "curvedCW"}}
        net.set_options(json.dumps(physics_opts))

    # --- Resolve display labels (with disambiguation for duplicates) ---
    display_names = {}
    for node in G.nodes:
        display_names[node] = G.nodes[node].get("display_name", node)
    # Find duplicates and add first initial to distinguish
    from collections import Counter as _Counter
    dn_counts = _Counter(display_names.values())
    for node, dn in list(display_names.items()):
        if dn_counts[dn] > 1:
            # Add first letter of the full name as initial
            first_char = node[0] if node else ""
            display_names[node] = f"{first_char}. {dn}"

    # --- Add nodes ---
    for node in G.nodes:
        color = node_color[node]
        group_label = node_group_label[node]
        r, g, b = _hex_to_rgb(color)
        size = node_sizes[node]
        case_count = G.nodes[node].get("case_count", 0)
        degree = G.degree(node, weight="weight")
        comm_idx = node_community.get(node, "?")
        if color_mode == "appointed_by":
            title = f"{node}\nAppointed by: {group_label}\nCommunity: {comm_idx}\nCases: {case_count}\nDegree: {degree}"
        else:
            title = f"{node}\nCases: {case_count}\nDegree: {degree}\nCommunity: {group_label}"
        label = _format_label(display_names[node])
        font_size = max(8, int(size * 0.28))
        node_kwargs = dict(
            label=label, title=title, size=size, shape="circle",
            color={
                "background": _darken_hex(color, 0.15),
                "border": color,
                "highlight": {"background": color, "border": "#1a1a1a"},
                "hover": {"background": color, "border": "#1a1a1a"},
            },
            font={"size": font_size, "color": "#1a1a1a", "face": "arial",
                  "multi": True, "strokeWidth": 2, "strokeColor": "#ffffff"},
            borderWidth=2,
            shadow={
                "enabled": True,
                "color": "rgba(0,0,0,0.12)",
                "size": 10, "x": 2, "y": 2,
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
            edge_color = f"rgba(180,180,195,{alpha:.2f})"

        # Disable glow on white background — looks muddy
        use_shadow = False
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

    # Inject fixed-position legend overlay
    if legend_entries:
        legend_title = "Appointed By" if color_mode == "appointed_by" else "Communities"
        legend_items = ""
        for lbl, color in legend_entries:
            legend_items += (
                f'<div style="margin-bottom:3px;">'
                f'<span style="display:inline-block;width:12px;height:12px;'
                f'border-radius:2px;margin-right:6px;vertical-align:middle;'
                f'background:{color};"></span>'
                f'<span style="color:#555;font-size:11px;font-family:DM Sans,arial,sans-serif;'
                f'vertical-align:middle;">{lbl}</span></div>'
            )
        legend_html = (
            f'<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">'
            f'<div style="position:fixed;top:10px;right:10px;z-index:1000;'
            f'background:rgba(255,255,255,0.95);border:1px solid #e0e0e0;'
            f'border-radius:16px;padding:12px 16px;max-height:80vh;'
            f'overflow-y:auto;box-shadow:0 4px 20px rgba(0,0,0,0.08);'
            f'font-family:DM Sans,sans-serif;">'
            f'<div style="color:#1a1a1a;font-weight:700;margin-bottom:8px;'
            f'font-size:13px;font-family:DM Sans,sans-serif;">{legend_title}</div>'
            f'{legend_items}</div>'
        )
        html = html.replace("</body>", legend_html + "</body>")

    # Inject script that disables physics after stabilization completes.
    # ForceAtlas2 lacks angular damping — nodes orbit endlessly if physics
    # stays enabled.  Freezing after stabilization gives a clean layout
    # while still allowing manual drag-and-drop repositioning.
    stabilize_script = """
<script>
(function() {
    var checkNet = setInterval(function() {
        if (typeof network !== 'undefined') {
            clearInterval(checkNet);
            network.once('stabilizationIterationsDone', function() {
                network.setOptions({physics: {enabled: false}});
            });
        }
    }, 50);
})();
</script>
"""
    html = html.replace("</body>", stabilize_script + "</body>")

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

    # Inject convex hull overlay for community boundaries
    if show_community_hulls:
        # Build community membership JSON: {nodeId: communityIndex}
        comm_data = {node: node_community[node] for node in G.nodes}
        # Community colors list
        comm_colors = COMMUNITY_COLORS
        hull_script = """
<script>
(function() {
    var communityData = """ + json.dumps(comm_data) + """;
    var communityColors = """ + json.dumps(comm_colors) + """;

    function cross(O, A, B) {
        return (A[0] - O[0]) * (B[1] - O[1]) - (A[1] - O[1]) * (B[0] - O[0]);
    }

    function convexHull(points) {
        if (points.length <= 2) return points.slice();
        points.sort(function(a, b) { return a[0] - b[0] || a[1] - b[1]; });
        var lower = [];
        for (var i = 0; i < points.length; i++) {
            while (lower.length >= 2 && cross(lower[lower.length-2], lower[lower.length-1], points[i]) <= 0)
                lower.pop();
            lower.push(points[i]);
        }
        var upper = [];
        for (var i = points.length - 1; i >= 0; i--) {
            while (upper.length >= 2 && cross(upper[upper.length-2], upper[upper.length-1], points[i]) <= 0)
                upper.pop();
            upper.push(points[i]);
        }
        upper.pop();
        lower.pop();
        return lower.concat(upper);
    }

    function hexToRgba(hex, alpha) {
        hex = hex.replace('#', '');
        var r = parseInt(hex.substring(0, 2), 16);
        var g = parseInt(hex.substring(2, 4), 16);
        var b = parseInt(hex.substring(4, 6), 16);
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    function drawRoundedHull(ctx, hull, pad) {
        if (hull.length < 2) return;
        if (hull.length === 2) {
            ctx.beginPath();
            ctx.moveTo(hull[0][0], hull[0][1]);
            ctx.lineTo(hull[1][0], hull[1][1]);
            ctx.stroke();
            return;
        }
        ctx.beginPath();
        for (var i = 0; i < hull.length; i++) {
            var a = hull[(i - 1 + hull.length) % hull.length];
            var b = hull[i];
            var c = hull[(i + 1) % hull.length];
            var ab = [b[0] - a[0], b[1] - a[1]];
            var bc = [c[0] - b[0], c[1] - b[1]];
            var labAB = Math.sqrt(ab[0]*ab[0] + ab[1]*ab[1]) || 1;
            var labBC = Math.sqrt(bc[0]*bc[0] + bc[1]*bc[1]) || 1;
            var r = Math.min(pad * 0.6, labAB * 0.4, labBC * 0.4);
            var p1 = [b[0] - ab[0]/labAB * r, b[1] - ab[1]/labAB * r];
            var p2 = [b[0] + bc[0]/labBC * r, b[1] + bc[1]/labBC * r];
            if (i === 0) ctx.moveTo(p1[0], p1[1]);
            else ctx.lineTo(p1[0], p1[1]);
            ctx.quadraticCurveTo(b[0], b[1], p2[0], p2[1]);
        }
        ctx.closePath();
    }

    var checkInterval = setInterval(function() {
        if (typeof network !== 'undefined') {
            clearInterval(checkInterval);

            network.on('beforeDrawing', function(ctx) {
                var positions = network.getPositions();
                var communities = {};
                for (var nodeId in communityData) {
                    var commIdx = communityData[nodeId];
                    if (!communities[commIdx]) communities[commIdx] = [];
                    var pos = positions[nodeId];
                    if (pos) communities[commIdx].push([pos.x, pos.y]);
                }
                for (var commIdx in communities) {
                    var members = communities[commIdx];
                    if (members.length < 2) continue;
                    var cx = 0, cy = 0;
                    for (var i = 0; i < members.length; i++) {
                        cx += members[i][0]; cy += members[i][1];
                    }
                    cx /= members.length; cy /= members.length;
                    var padding = 55;
                    var expanded = [];
                    for (var i = 0; i < members.length; i++) {
                        var dx = members[i][0] - cx;
                        var dy = members[i][1] - cy;
                        var dist = Math.sqrt(dx*dx + dy*dy);
                        if (dist > 0) {
                            expanded.push([
                                members[i][0] + (dx/dist) * padding,
                                members[i][1] + (dy/dist) * padding
                            ]);
                        } else {
                            expanded.push([members[i][0] + padding, members[i][1]]);
                        }
                    }
                    var hull = convexHull(expanded);
                    if (hull.length < 2) continue;
                    var colorIdx = parseInt(commIdx) % communityColors.length;
                    var color = communityColors[colorIdx];
                    drawRoundedHull(ctx, hull, padding);
                    ctx.fillStyle = hexToRgba(color, 0.08);
                    ctx.fill();
                    ctx.strokeStyle = hexToRgba(color, 0.3);
                    ctx.lineWidth = 2;
                    ctx.setLineDash([10, 5]);
                    ctx.stroke();
                    ctx.setLineDash([]);
                    // Community label near centroid
                    ctx.fillStyle = hexToRgba(color, 0.5);
                    ctx.font = '12px arial';
                    ctx.fillText('C' + commIdx, cx - 8, cy - padding - 10);
                }
            });

            // Force redraw so hulls appear immediately (needed when
            // physics is disabled — no simulation frames to trigger it)
            setTimeout(function() { network.redraw(); }, 50);
        }
    }, 100);
})();
</script>
"""
        html = html.replace("</body>", hull_script + "</body>")

    return html


def export_standalone_html(
    G: nx.Graph,
    edge_threshold: int = 0,
    node_size_by: str = "weighted_degree",
    curved_edges: bool = True,
    opacity_scaling: bool = True,
    layout_mode: str = "community",
    graph_height: int = 700,
    color_mode: str = "community",
    appointed_by_map: dict | None = None,
    show_community_hulls: bool = False,
    centroid_radius_base: float = 10.0,
    jitter_scale: float = 0.25,
    repulsion_k: float = 8.0,
    title: str = "Philippine Supreme Court \u2014 Justice Voting Network",
    subtitle: str = "Co-voting patterns among Supreme Court justices",
    output_path: str | None = None,
) -> str:
    """Export a self-contained standalone HTML file of the network graph.

    Generates the pyvis graph and wraps it in a styled HTML shell matching
    the dissent rate chart design (DM Sans/DM Serif Display, white background,
    card layout with OG meta tags for LinkedIn sharing).

    Args:
        G through repulsion_k: Same as build_pyvis_html().
        title: Page title displayed in the header.
        subtitle: Subtitle text below the title.
        output_path: If provided, writes HTML to this file path.

    Returns:
        Complete HTML string.
    """
    raw_html = build_pyvis_html(
        G,
        edge_threshold=edge_threshold,
        node_size_by=node_size_by,
        curved_edges=curved_edges,
        opacity_scaling=opacity_scaling,
        layout_mode=layout_mode,
        graph_height=graph_height,
        color_mode=color_mode,
        appointed_by_map=appointed_by_map,
        show_community_hulls=show_community_hulls,
        centroid_radius_base=centroid_radius_base,
        jitter_scale=jitter_scale,
        repulsion_k=repulsion_k,
    )

    # Extract body content from pyvis-generated HTML
    body_start = raw_html.find("<body>")
    body_end = raw_html.find("</body>")
    if body_start == -1 or body_end == -1:
        body_content = raw_html
    else:
        body_content = raw_html[body_start + len("<body>"):body_end]

    # Extract head scripts/styles from pyvis (vis.js CDN links, etc.)
    head_start = raw_html.find("<head>")
    head_end = raw_html.find("</head>")
    pyvis_head = ""
    if head_start != -1 and head_end != -1:
        pyvis_head = raw_html[head_start + len("<head>"):head_end]

    # Build metrics summary
    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()
    density = f"{nx.density(G):.4f}" if n_nodes > 1 else "N/A"
    communities = nx.community.louvain_communities(G, weight="weight", seed=42)
    n_communities = len(communities)

    standalone = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="Interactive network visualization of co-voting patterns among Philippine Supreme Court justices.">
<meta property="og:image" content="og-preview.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="Interactive network visualization of co-voting patterns among Philippine Supreme Court justices.">
<meta name="twitter:image" content="og-preview.png">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,700&family=DM+Serif+Display&display=swap" rel="stylesheet">
{pyvis_head}
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'DM Sans', sans-serif;
    background: #ffffff;
    color: #1a1a1a;
    min-height: 100vh;
  }}
  .container {{
    max-width: 1320px;
    margin: 0 auto;
    padding: 40px 32px 60px;
  }}
  .header {{ margin-bottom: 28px; }}
  .header h1 {{
    font-family: 'DM Serif Display', serif;
    font-size: 32px;
    color: #111;
    letter-spacing: -0.5px;
    margin-bottom: 6px;
  }}
  .header .subtitle {{
    font-size: 14px;
    color: #777;
    font-weight: 400;
  }}
  .nav-link {{
    display: inline-block;
    margin-bottom: 20px;
    font-size: 13px;
    color: #3b82f6;
    text-decoration: none;
  }}
  .nav-link:hover {{ text-decoration: underline; }}
  .graph-wrapper {{
    position: relative;
    background: #fff;
    border: 1px solid #e0e0e0;
    border-radius: 16px;
    overflow: hidden;
    margin-bottom: 24px;
  }}
  .graph-wrapper #mynetwork {{
    border: none !important;
  }}
  .metrics-bar {{
    display: flex;
    gap: 32px;
    padding: 16px 24px;
    border-bottom: 1px solid #f0f0f0;
    font-size: 13px;
  }}
  .metric-item {{ display: flex; flex-direction: column; }}
  .metric-label {{ color: #999; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 500; }}
  .metric-value {{ color: #1a1a1a; font-size: 18px; font-weight: 700; }}
  .footer {{
    text-align: center;
    padding: 20px;
    font-size: 12px;
    color: #aaa;
  }}
  .footer a {{ color: #3b82f6; text-decoration: none; }}
  .footer a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="container">
  <a href="index.html" class="nav-link">&larr; Back to overview</a>
  <div class="header">
    <h1>{title}</h1>
    <p class="subtitle">{subtitle}</p>
  </div>
  <div class="graph-wrapper">
    <div class="metrics-bar">
      <div class="metric-item"><span class="metric-label">Justices</span><span class="metric-value">{n_nodes}</span></div>
      <div class="metric-item"><span class="metric-label">Connections</span><span class="metric-value">{n_edges}</span></div>
      <div class="metric-item"><span class="metric-label">Density</span><span class="metric-value">{density}</span></div>
      <div class="metric-item"><span class="metric-label">Communities</span><span class="metric-value">{n_communities}</span></div>
    </div>
    {body_content}
  </div>
  <div class="footer">
    <p>Data: Philippine Supreme Court Reports Annotated &middot;
    <a href="https://github.com/kikomobile/SC-Decisions">Source on GitHub</a></p>
  </div>
</div>
</body>
</html>"""

    if output_path:
        from pathlib import Path
        Path(output_path).write_text(standalone, encoding="utf-8")

    return standalone


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
    White background with subtle depth effects.
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
                fontsize=16, color="#666666")
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
            ax.plot(xs, ys, color=color, alpha=alpha * 0.15,
                    linewidth=width + 3, zorder=0, solid_capstyle="round")
        ax.plot(xs, ys, color=color, alpha=alpha, linewidth=width, zorder=1)

    # Node glow layer (larger, faint circles behind each node)
    for i, node in enumerate(node_list):
        x, y = pos[node]
        color = node_colors[i]
        glow_size = node_sizes[i] * 1.8
        ax.scatter(x, y, s=glow_size, c=color,
                   alpha=0.08, edgecolors="none", zorder=1)

    # Nodes
    nx.draw_networkx_nodes(
        G, pos, ax=ax, nodelist=node_list,
        node_size=node_sizes,
        node_color=[_darken_hex(c, 0.10) for c in node_colors],
        edgecolors=node_colors,
        linewidths=2.0,
    )

    # Resolve display names (same logic as PyVis)
    display_names_mpl = {}
    for node in node_list:
        display_names_mpl[node] = G.nodes[node].get("display_name", node)
    from collections import Counter as _CntMpl
    dn_counts_mpl = _CntMpl(display_names_mpl.values())
    for node, dn in list(display_names_mpl.items()):
        if dn_counts_mpl[dn] > 1:
            first_char = node[0] if node else ""
            display_names_mpl[node] = f"{first_char}. {dn}"

    # Labels inside nodes
    for node in node_list:
        x, y = pos[node]
        label = _format_label(display_names_mpl[node], max_line_len=14)
        area = scale(raw[node])
        font_size = max(5, min(9, area / 200))
        ax.text(
            x, y, label, ha="center", va="center",
            fontsize=font_size, color="#1a1a1a", fontweight="bold", zorder=3,
            path_effects=[pe.withStroke(linewidth=2, foreground="white")],
        )

    # Legend (styled for white background)
    legend_handles = []
    for lbl, color in legend_entries[:12]:
        patch = mpatches.Patch(color=color, label=lbl)
        legend_handles.append(patch)
    if legend_handles:
        legend = ax.legend(
            handles=legend_handles, loc="upper left", fontsize=8,
            facecolor="#ffffff", edgecolor="#e0e0e0", labelcolor="#1a1a1a",
            framealpha=0.95,
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
