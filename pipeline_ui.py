"""SC Decisions — Pipeline Control Panel.

Streamlit web UI for the detection pipeline.
Launch: streamlit run pipeline_ui.py
"""

import streamlit as st
import streamlit.components.v1 as components
import time
import io
import csv
import json
from pathlib import Path

st.set_page_config(
    page_title="SC Decisions — Pipeline Control",
    layout="wide",
    initial_sidebar_state="expanded",
)

import ui_helpers as uh
from regex_improve.detection.label_inspector import (
    parse_lookup_input, lookup_cases, format_case_text, compile_results,
)
import networkx as nx
from network.build_network import NetworkBuilder, export_edge_list, export_adjacency_matrix, export_graphml
from network.visualize import build_pyvis_html, get_community_summary, build_matplotlib_figure, export_figure_bytes
from network.appointed_by import build_appointed_by_map
from regex_improve.detection.csv_extractor import JusticeMatcher

# ---------------------------------------------------------------------------
# Session state initialization (runs once per session)
# ---------------------------------------------------------------------------
if "settings" not in st.session_state:
    st.session_state.settings = uh.load_settings()
if "runner" not in st.session_state:
    st.session_state.runner = None
if "log_lines" not in st.session_state:
    st.session_state.log_lines = []
if "run_complete" not in st.session_state:
    st.session_state.run_complete = False
if "run_metrics" not in st.session_state:
    st.session_state.run_metrics = {}
if "validation_results" not in st.session_state:
    st.session_state.validation_results = {}
if "inspect_results" not in st.session_state:
    st.session_state.inspect_results = []
if "network_graph" not in st.session_state:
    st.session_state.network_graph = None
if "network_stats" not in st.session_state:
    st.session_state.network_stats = None
if "network_html" not in st.session_state:
    st.session_state.network_html = None
if "network_png" not in st.session_state:
    st.session_state.network_png = None
if "network_svg" not in st.session_state:
    st.session_state.network_svg = None
if "appointed_by_map" not in st.session_state:
    st.session_state.appointed_by_map = None

# ---------------------------------------------------------------------------
# Sidebar — Global Settings
# ---------------------------------------------------------------------------
st.sidebar.header("Settings")

s = st.session_state.settings

s["input_dir"] = st.sidebar.text_input("Volume directory", value=s["input_dir"])
s["output_dir"] = st.sidebar.text_input("Output directory", value=s["output_dir"])

st.sidebar.divider()
s["skip_llm"] = st.sidebar.toggle("Skip LLM", value=s["skip_llm"])
s["force"] = st.sidebar.toggle("Force reprocess", value=s["force"])
s["budget"] = st.sidebar.number_input(
    "LLM Budget ($)", value=s["budget"], min_value=0.0, step=0.5
)
s["threshold"] = st.sidebar.slider(
    "Confidence threshold", 0.0, 1.0, s["threshold"], 0.05
)

st.sidebar.divider()
if st.sidebar.button("Save Settings"):
    uh.save_settings(s)
    st.sidebar.success("Settings saved!")


# ---------------------------------------------------------------------------
# Helper: run command with live log display
# ---------------------------------------------------------------------------
def run_and_display(cmd: list, cwd: str, label: str):
    """Run a subprocess and display live log output with summary."""
    st.session_state.log_lines = []
    st.session_state.run_complete = False
    st.session_state.run_metrics = {}

    runner = uh.PipelineRunner()
    st.session_state.runner = runner
    runner.start(cmd, cwd)

    with st.status(f"Running {label}...", expanded=True) as status:
        log_area = st.empty()

        while not runner.is_done:
            new_lines, done = runner.poll()
            if new_lines:
                st.session_state.log_lines.extend(new_lines)
                display = st.session_state.log_lines[-200:]
                log_area.code("".join(display), language="log")
            time.sleep(0.3)

        # Final drain
        new_lines, _ = runner.poll()
        if new_lines:
            st.session_state.log_lines.extend(new_lines)

        log_area.code(
            "".join(st.session_state.log_lines[-200:]), language="log"
        )

        if runner.returncode == 0:
            status.update(label=f"{label} — Complete!", state="complete")
        else:
            status.update(
                label=f"{label} — Failed (exit {runner.returncode})",
                state="error",
            )

    st.session_state.run_complete = True
    st.session_state.run_metrics = uh.parse_summary_metrics(
        "".join(st.session_state.log_lines)
    )
    st.session_state.runner = None


# ---------------------------------------------------------------------------
# Helper: display summary metrics
# ---------------------------------------------------------------------------
def display_metrics(metrics: dict):
    """Show summary metrics as st.metric cards."""
    if not metrics:
        return
    cols = st.columns(4)
    if "total_cases" in metrics:
        cols[0].metric("Total Cases", metrics["total_cases"])
    if "high_confidence" in metrics:
        cols[1].metric("High Confidence", metrics["high_confidence"])
    if "low_confidence" in metrics:
        cols[2].metric("Low Confidence", metrics["low_confidence"])
    if "ocr_corrections" in metrics:
        cols[3].metric("OCR Corrections", metrics["ocr_corrections"])
    if "volumes_processed" in metrics:
        cols[0].metric("Volumes Processed", metrics["volumes_processed"])


# ---------------------------------------------------------------------------
# Main layout — four tabs
# ---------------------------------------------------------------------------
st.title("SC Decisions — Pipeline Control")

tab_single, tab_batch, tab_csv, tab_inspect, tab_network = st.tabs(
    ["Single Volume", "Batch Processing", "CSV Extraction", "Label Inspector", "Network Analysis"]
)

# --- Tab 1: Single Volume ---------------------------------------------------
with tab_single:
    volumes = uh.scan_volumes(s["input_dir"])
    vol_names = [v.name for v in volumes]

    if vol_names:
        selected_vol = st.selectbox("Select volume", vol_names)
        volume_path = str(Path(s["input_dir"]) / selected_vol)
    else:
        st.warning(f"No Volume_*.txt files found in {s['input_dir']}")
        volume_path = st.text_input("Volume path (manual)", key="single_manual_path")

    # Output path auto-computed
    if volume_path:
        stem = Path(volume_path).stem
        default_out = str(Path(s["output_dir"]) / f"{stem}_predicted.json")
    else:
        default_out = ""
    output_path = st.text_input("Output path", value=default_out, key="single_output")

    # Optional ground truth
    gt_path = st.text_input(
        "Ground truth path (optional, for scoring)",
        value=s.get("ground_truth_path", ""),
        key="single_gt",
    )

    col1, col2 = st.columns(2)
    run_single = col1.button("Run Pipeline", key="run_single", type="primary")
    if output_path:
        col2.button(
            "Open Output Folder",
            key="open_single",
            on_click=lambda p=str(Path(output_path).parent): uh.open_folder(p),
        )

    if run_single and volume_path:
        cmd = uh.build_single_cmd(
            volume_path=volume_path,
            output_path=output_path,
            skip_llm=s["skip_llm"],
            force=s["force"],
            budget=s["budget"],
            threshold=s["threshold"],
            score_path=gt_path,
        )
        run_and_display(cmd, uh.get_pipeline_cwd(), "Single Volume")
        display_metrics(st.session_state.run_metrics)

# --- Tab 2: Batch Processing ------------------------------------------------
with tab_batch:
    col1, col2 = st.columns(2)
    range_start = col1.number_input(
        "Range start",
        value=s["volume_range_start"],
        min_value=121,
        max_value=999,
        key="batch_start",
    )
    range_end = col2.number_input(
        "Range end",
        value=s["volume_range_end"],
        min_value=121,
        max_value=999,
        key="batch_end",
    )

    s["volume_range_start"] = range_start
    s["volume_range_end"] = range_end

    col1, col2 = st.columns(2)
    run_batch = col1.button("Run Batch", key="run_batch", type="primary")
    col2.button(
        "Open Output Folder",
        key="open_batch",
        on_click=lambda d=s["output_dir"]: uh.open_folder(d),
    )

    if run_batch:
        cmd = uh.build_batch_cmd(
            input_dir=s["input_dir"],
            output_dir=s["output_dir"],
            range_start=range_start,
            range_end=range_end,
            skip_llm=s["skip_llm"],
            force=s["force"],
            budget=s["budget"],
            threshold=s["threshold"],
        )
        run_and_display(cmd, uh.get_pipeline_cwd(), "Batch Processing")
        display_metrics(st.session_state.run_metrics)

# --- Tab 3: CSV Extraction --------------------------------------------------
with tab_csv:
    csv_input = st.text_input(
        "Predictions directory", value=s["output_dir"], key="csv_input_dir"
    )
    csv_output = st.text_input(
        "Output CSV path", value=s["csv_output"], key="csv_output_path"
    )
    csv_justices = st.text_input(
        "Justices JSON", value=s["justices_path"], key="csv_justices"
    )
    csv_threshold = st.slider(
        "Fuzzy match threshold", 0.0, 1.0, s["csv_threshold"], 0.05, key="csv_thresh"
    )

    col1, col2 = st.columns(2)
    run_csv = col1.button("Extract CSV", key="run_csv", type="primary")
    if csv_output:
        col2.button(
            "Open Output Folder",
            key="open_csv",
            on_click=lambda p=str(Path(csv_output).parent): uh.open_folder(p),
        )

    if run_csv:
        cmd = uh.build_csv_cmd(
            input_dir=csv_input,
            output_path=csv_output,
            justices_path=csv_justices,
            threshold=csv_threshold,
        )
        run_and_display(cmd, str(uh.get_repo_root()), "CSV Extraction")
        display_metrics(st.session_state.run_metrics)

    # Validation section
    st.divider()
    st.subheader("Validation Checks")

    _archive = sorted(Path("csv_archive").glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    _default_baseline = str(_archive[0]) if _archive else "predictions_extract.csv"
    val_before = st.text_input(
        "Baseline CSV (before)",
        value=_default_baseline,
        key="val_before",
    )
    val_after = st.text_input(
        "Latest CSV (after)", value=csv_output, key="val_after"
    )

    if st.button("Run Validation", key="run_validation"):
        with st.spinner("Running validation checks..."):
            results = uh.run_all_csv_validations(val_before, val_after)
            st.session_state.validation_results = results

    if st.session_state.validation_results:
        for name, output in st.session_state.validation_results.items():
            if name.endswith("_html"):
                continue  # rendered inline with the plain-text version
            with st.expander(name, expanded=False):
                html_key = f"{name}_html"
                if html_key in st.session_state.validation_results:
                    st.markdown(
                        st.session_state.validation_results[html_key],
                        unsafe_allow_html=True,
                    )
                    st.code(output, language="text")
                else:
                    st.code(output, language="text")

# --- Tab 4: Label Inspector -------------------------------------------------
with tab_inspect:
    st.markdown(
        "Paste **volume + case number** rows (tab-separated, e.g. copied from Excel)."
    )
    inspect_input = st.text_area(
        "Volume / Case Number pairs",
        height=150,
        placeholder="227\tG.R. No. 71905\n227\tG.R. No. 68661",
        key="inspect_input",
    )

    col1, col2 = st.columns([1, 3])
    run_inspect = col1.button("Look Up Labels", key="run_inspect", type="primary")

    if run_inspect and inspect_input.strip():
        queries = parse_lookup_input(inspect_input)
        if not queries:
            st.error("No valid volume/case_number pairs found. Expected tab-separated lines.")
        else:
            with st.spinner(f"Looking up {len(queries)} case(s)..."):
                results = lookup_cases(s["output_dir"], queries)

            # Summary metrics
            found = sum(1 for r in results if r.found)
            not_found = len(results) - found
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Queried", len(results))
            mc2.metric("Found", found)
            mc3.metric("Not Found", not_found)

            # Store in session state for download button
            st.session_state.inspect_results = results

            # Display each case
            for r in results:
                if r.found:
                    with st.expander(
                        f"Vol {r.volume} — {r.case_number} — conf: {r.confidence:.3f if r.confidence is not None else 'N/A'}",
                        expanded=False,
                    ):
                        st.code(format_case_text(r), language="text")
                else:
                    with st.expander(
                        f"Vol {r.volume} — {r.case_number} — NOT FOUND",
                        expanded=False,
                    ):
                        st.warning(r.error)

            # Download button
            compiled = compile_results(results)
            st.download_button(
                "Download Results (JSON)",
                data=json.dumps(compiled, indent=2, ensure_ascii=False),
                file_name="label_inspection.json",
                mime="application/json",
                key="inspect_download",
            )

# --- Tab 5: Network Analysis -----------------------------------------------
with tab_network:
    repo_root = uh.get_repo_root()
    csv_path = repo_root / "predictions_extract.csv"
    justices_path = repo_root / "regex_improve" / "detection" / "justices.json"

    # --- Build controls ---
    st.subheader("Build Parameters")
    bc1, bc2, bc3, bc4 = st.columns(4)
    vol_start = bc1.number_input("Vol Start", value=226, min_value=121, max_value=999, key="net_vol_start")
    vol_end = bc2.number_input("Vol End", value=961, min_value=121, max_value=999, key="net_vol_end")
    min_conf = bc3.slider("Min Confidence", 0.0, 1.0, 0.7, 0.05, key="net_min_conf")
    build_net = bc4.button("Build Network", key="run_network", type="primary")

    # --- Display controls ---
    dc1, dc2, dc3 = st.columns(3)
    edge_thresh = dc1.slider("Edge Weight Threshold", 0, 500, 0, 10, key="net_edge_thresh")
    size_options = {"Weighted Degree": "weighted_degree", "Case Count": "case_count", "Uniform": "uniform"}
    size_label = dc2.selectbox("Node Size By", list(size_options.keys()), key="net_size_by")
    size_by = size_options[size_label]
    layout_options = {"Community Clusters": "community", "Interactive Physics": "physics"}
    layout_label = dc3.selectbox("Layout", list(layout_options.keys()), key="net_layout")
    layout_mode = layout_options[layout_label]

    dc4, dc5, dc6, dc7 = st.columns(4)
    curved_edges = dc4.checkbox("Curved edges", value=True, key="net_curved")
    opacity_scaling = dc5.checkbox("Opacity scaling", value=True, key="net_opacity")
    graph_height = dc6.slider("Graph Height", 400, 1200, 700, 50, key="net_height")
    color_options = {"Community (Louvain)": "community", "Appointed By": "appointed_by"}
    color_label = dc7.selectbox("Color By", list(color_options.keys()), key="net_color_mode")
    color_mode = color_options[color_label]

    # --- Build logic ---
    if build_net:
        if not csv_path.exists():
            st.error(f"CSV not found: {csv_path}")
        elif not justices_path.exists():
            st.error(f"justices.json not found: {justices_path}")
        else:
            with st.spinner("Building network..."):
                matcher = JusticeMatcher(str(justices_path))
                builder = NetworkBuilder(matcher, min_confidence=min_conf)
                G = builder.build(str(csv_path), vol_min=vol_start, vol_max=vol_end)
                st.session_state.network_graph = G
                st.session_state.network_stats = builder.stats

                # Build appointed-by mapping for color mode
                justices_csv = repo_root / "ph_sc_justices.csv"
                if justices_csv.exists():
                    st.session_state.appointed_by_map = build_appointed_by_map(
                        list(G.nodes), str(justices_csv),
                    )
                else:
                    st.session_state.appointed_by_map = None

                # Also export to disk
                out_dir = repo_root / "network_output"
                out_dir.mkdir(parents=True, exist_ok=True)
                export_edge_list(G, str(out_dir / "edge_list.csv"))
                export_adjacency_matrix(G, str(out_dir / "adjacency_matrix.csv"))
                export_graphml(G, str(out_dir / "voting_network.graphml"))
                stats_out = {**builder.stats, "nodes": G.number_of_nodes(), "edges": G.number_of_edges()}
                if G.number_of_nodes() > 1:
                    stats_out["density"] = round(nx.density(G), 6)
                with open(out_dir / "network_stats.json", "w", encoding="utf-8") as f:
                    json.dump(stats_out, f, indent=2)

            st.success(f"Network built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # --- Display when graph exists ---
    G = st.session_state.network_graph
    stats = st.session_state.network_stats

    if G is not None and G.number_of_nodes() > 0:
        # Metrics row
        communities = get_community_summary(G)
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Nodes", G.number_of_nodes())
        mc2.metric("Edges", G.number_of_edges())
        mc3.metric("Density", f"{nx.density(G):.4f}")
        mc4.metric("Communities", len(communities))

        # Pyvis visualization
        ab_map = st.session_state.appointed_by_map
        html = build_pyvis_html(
            G, edge_threshold=edge_thresh, node_size_by=size_by,
            curved_edges=curved_edges, opacity_scaling=opacity_scaling,
            layout_mode=layout_mode, graph_height=graph_height,
            color_mode=color_mode, appointed_by_map=ab_map,
        )
        st.session_state.network_html = html
        components.html(html, height=graph_height + 20, scrolling=True)

        # --- Details expanders ---
        with st.expander("Community Membership", expanded=False):
            for comm in communities:
                st.markdown(f"**Community {comm['community']}** ({comm['size']} members)")
                st.write(", ".join(comm["members"]))

        with st.expander("Top 20 Justice Pairs", expanded=False):
            edges = [(u, v, d["weight"]) for u, v, d in G.edges(data=True)]
            edges.sort(key=lambda x: -x[2])
            for i, (u, v, w) in enumerate(edges[:20], 1):
                st.text(f"{i:2d}. {u:<25s} — {v:<25s}  weight={w}")

        with st.expander("Build Statistics", expanded=False):
            if stats:
                st.json(stats)

        # --- Download buttons ---
        st.subheader("Downloads")
        dl1, dl2, dl3 = st.columns(3)

        # Edge list CSV
        buf_edge = io.StringIO()
        w = csv.writer(buf_edge)
        w.writerow(["source", "target", "weight"])
        sorted_edges = sorted(G.edges(data=True), key=lambda x: -x[2]["weight"])
        for u, v, d in sorted_edges:
            w.writerow([u, v, d["weight"]])
        dl1.download_button(
            "Edge List (CSV)",
            data=buf_edge.getvalue(),
            file_name="edge_list.csv",
            mime="text/csv",
            key="dl_edge_list",
        )

        # Adjacency matrix CSV
        buf_adj = io.StringIO()
        w2 = csv.writer(buf_adj)
        nodes_sorted = sorted(G.nodes())
        w2.writerow([""] + nodes_sorted)
        for u in nodes_sorted:
            row = [u] + [G[u][v]["weight"] if G.has_edge(u, v) else 0 for v in nodes_sorted]
            w2.writerow(row)
        dl2.download_button(
            "Adjacency Matrix (CSV)",
            data=buf_adj.getvalue(),
            file_name="adjacency_matrix.csv",
            mime="text/csv",
            key="dl_adj_matrix",
        )

        # Stats JSON
        stats_download = {**(stats or {}), "nodes": G.number_of_nodes(), "edges": G.number_of_edges()}
        if G.number_of_nodes() > 1:
            stats_download["density"] = round(nx.density(G), 6)
        dl3.download_button(
            "Network Stats (JSON)",
            data=json.dumps(stats_download, indent=2),
            file_name="network_stats.json",
            mime="application/json",
            key="dl_stats",
        )

        # --- Graph export row ---
        dl4, dl5, dl6 = st.columns(3)

        # Interactive HTML
        if st.session_state.network_html:
            dl4.download_button(
                "Interactive Graph (HTML)",
                data=st.session_state.network_html,
                file_name="justice_network.html",
                mime="text/html",
                key="dl_html",
            )

        # PNG export
        if dl5.button("Generate PNG", key="gen_png"):
            with st.spinner("Rendering PNG..."):
                fig = build_matplotlib_figure(
                    G, edge_threshold=edge_thresh, node_size_by=size_by,
                    opacity_scaling=opacity_scaling,
                    color_mode=color_mode, appointed_by_map=ab_map,
                )
                st.session_state.network_png = export_figure_bytes(fig, fmt="png", dpi=150)
                import matplotlib.pyplot as plt
                plt.close(fig)
        if st.session_state.network_png:
            dl5.download_button(
                "Download PNG",
                data=st.session_state.network_png,
                file_name="justice_network.png",
                mime="image/png",
                key="dl_png",
            )

        # SVG export
        if dl6.button("Generate SVG", key="gen_svg"):
            with st.spinner("Rendering SVG..."):
                fig = build_matplotlib_figure(
                    G, edge_threshold=edge_thresh, node_size_by=size_by,
                    opacity_scaling=opacity_scaling,
                    color_mode=color_mode, appointed_by_map=ab_map,
                )
                st.session_state.network_svg = export_figure_bytes(fig, fmt="svg")
                import matplotlib.pyplot as plt
                plt.close(fig)
        if st.session_state.network_svg:
            dl6.download_button(
                "Download SVG",
                data=st.session_state.network_svg,
                file_name="justice_network.svg",
                mime="image/svg+xml",
                key="dl_svg",
            )
    elif G is not None:
        st.info("Network has no nodes. Try adjusting the volume range or confidence threshold.")
