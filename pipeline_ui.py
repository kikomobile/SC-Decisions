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
import pandas as pd
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
from network.build_network import NetworkBuilder, export_edge_list, export_adjacency_matrix, export_graphml, extract_display_name
from network.visualize import build_pyvis_html, get_community_summary, build_matplotlib_figure, export_figure_bytes
from network.appointed_by import build_appointed_by_map, PRESIDENT_COLORS, FALLBACK_COLOR
from network.temporal import (
    load_cases, load_tenures, TemporalAnalyzer,
    TemporalNetwork, build_temporal_network_plotly, compute_global_bounds,
    build_tenure_timeline_plotly,
    extract_cross_community_cases, compile_cross_community_summary,
    court_dissent_rate_timeline, DISSENT_RATE_COMBOS,
)
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
if "temporal_analyzer" not in st.session_state:
    st.session_state.temporal_analyzer = None
if "temporal_summary" not in st.session_state:
    st.session_state.temporal_summary = None
if "temporal_snapshots" not in st.session_state:
    st.session_state.temporal_snapshots = None
if "tn_axis_range" not in st.session_state:
    st.session_state.tn_axis_range = None
if "tn_step" not in st.session_state:
    st.session_state.tn_step = 0
if "tn_playing" not in st.session_state:
    st.session_state.tn_playing = False
if "tn_tenures" not in st.session_state:
    st.session_state.tn_tenures = None
if "tn_appointed_by" not in st.session_state:
    st.session_state.tn_appointed_by = None
if "ta_windowed_data" not in st.session_state:
    st.session_state.ta_windowed_data = None  # dict of metric_name -> DataFrame
if "ta_windows" not in st.session_state:
    st.session_state.ta_windows = []  # list of window_center dates
if "ta_step" not in st.session_state:
    st.session_state.ta_step = 0
if "ta_params" not in st.session_state:
    st.session_state.ta_params = {}  # stored compute params for export

# ---------------------------------------------------------------------------
# Sidebar — Global Settings
# ---------------------------------------------------------------------------
st.sidebar.header("Settings")

s = st.session_state.settings

s["input_dir"] = st.sidebar.text_input("Volume directory", value=s["input_dir"],
    help="Path to the folder containing Volume_NNN.txt files")
s["output_dir"] = st.sidebar.text_input("Output directory", value=s["output_dir"],
    help="Path where predicted JSON outputs are saved")

st.sidebar.divider()
s["skip_llm"] = st.sidebar.toggle("Skip LLM", value=s["skip_llm"],
    help="Run regex-only detection without calling the LLM for ambiguous fields")
s["force"] = st.sidebar.toggle("Force reprocess", value=s["force"],
    help="Reprocess volumes even if output files already exist")
s["budget"] = st.sidebar.number_input(
    "LLM Budget ($)", value=s["budget"], min_value=0.0, step=0.5,
    help="Maximum dollar spend allowed for LLM API calls in a single run",
)
s["threshold"] = st.sidebar.slider(
    "Confidence threshold", 0.0, 1.0, s["threshold"], 0.05,
    help="Minimum confidence score to accept a parsed field (lower = more permissive)",
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
        selected_vol = st.selectbox("Select volume", vol_names,
            help="Choose a volume text file to run the detection pipeline on")
        volume_path = str(Path(s["input_dir"]) / selected_vol)
    else:
        st.warning(f"No Volume_*.txt files found in {s['input_dir']}")
        volume_path = st.text_input("Volume path (manual)", key="single_manual_path",
            help="Manually enter the full path to a Volume_NNN.txt file")

    # Output path auto-computed
    if volume_path:
        stem = Path(volume_path).stem
        default_out = str(Path(s["output_dir"]) / f"{stem}_predicted.json")
    else:
        default_out = ""
    output_path = st.text_input("Output path", value=default_out, key="single_output",
        help="Where to save the predicted JSON output for this volume")

    # Optional ground truth
    gt_path = st.text_input(
        "Ground truth path (optional, for scoring)",
        value=s.get("ground_truth_path", ""),
        key="single_gt",
        help="Path to a ground truth JSON file to score predictions against (P/R/F1)",
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
        help="First volume number in the batch range (inclusive)",
    )
    range_end = col2.number_input(
        "Range end",
        value=s["volume_range_end"],
        min_value=121,
        max_value=999,
        key="batch_end",
        help="Last volume number in the batch range (inclusive)",
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
        "Predictions directory", value=s["output_dir"], key="csv_input_dir",
        help="Folder containing predicted JSON files to extract into CSV",
    )
    csv_output = st.text_input(
        "Output CSV path", value=s["csv_output"], key="csv_output_path",
        help="Path for the consolidated predictions CSV output",
    )
    csv_justices = st.text_input(
        "Justices JSON", value=s["justices_path"], key="csv_justices",
        help="Path to justices.json for fuzzy name matching and normalization",
    )
    csv_threshold = st.slider(
        "Fuzzy match threshold", 0.0, 1.0, s["csv_threshold"], 0.05, key="csv_thresh",
        help="Minimum similarity score for fuzzy justice name matching (higher = stricter)",
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
        help="Previous CSV to compare against (e.g. from csv_archive/)",
    )
    val_after = st.text_input(
        "Latest CSV (after)", value=csv_output, key="val_after",
        help="Newly generated CSV to validate against the baseline",
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
        help="Paste tab-separated rows of volume number and G.R. number to look up parsed labels",
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
    vol_start = bc1.number_input("Vol Start", value=226, min_value=121, max_value=999, key="net_vol_start",
        help="First volume to include in the network (inclusive)")
    vol_end = bc2.number_input("Vol End", value=961, min_value=121, max_value=999, key="net_vol_end",
        help="Last volume to include in the network (inclusive)")
    min_conf = bc3.slider("Min Confidence", 0.0, 1.0, 0.7, 0.05, key="net_min_conf",
        help="Only include cases with confidence >= this value")
    build_net = bc4.button("Build Network", key="run_network", type="primary")

    # --- Case filters (shared across all sub-tabs) ---
    fc1, fc2, fc3 = st.columns([2, 2, 1])
    division_all = ["EN BANC", "FIRST DIVISION", "SECOND DIVISION", "THIRD DIVISION"]
    division_filter = fc1.multiselect("Division Filter", division_all, default=division_all,
        key="net_division_filter",
        help="Only include cases from these divisions (all selected = no filter)")
    dissent_options = {"All Cases": "all", "Unanimous Only": "unanimous", "With Dissent Only": "with_dissent"}
    dissent_label = fc2.selectbox("Dissent Filter", list(dissent_options.keys()), key="net_dissent_filter",
        help="All: no filter. Unanimous: only cases with no dissenters. With Dissent: only cases where at least one justice dissented")
    dissent_filter = dissent_options[dissent_label]
    treat_no_part = fc3.checkbox("Treat no_part as dissent", value=False, key="net_no_part",
        help="Reclassify 'took no part' justices as dissenters (~5× more signal). Applies to all sub-tabs.")

    # --- Build logic ---
    if build_net:
        if not csv_path.exists():
            st.error(f"CSV not found: {csv_path}")
        elif not justices_path.exists():
            st.error(f"justices.json not found: {justices_path}")
        else:
            with st.spinner("Building network..."):
                justices_csv = repo_root / "ph_sc_justices.csv"
                matcher = JusticeMatcher(
                    str(justices_path),
                    csv_path=str(justices_csv) if justices_csv.exists() else None,
                )
                builder = NetworkBuilder(matcher, min_confidence=min_conf)
                # Pass division filter only if not all selected (= no filter)
                div_filt = division_filter if len(division_filter) < len(division_all) else None
                G = builder.build(
                    str(csv_path), vol_min=vol_start, vol_max=vol_end,
                    division_filter=div_filt, dissent_filter=dissent_filter,
                    treat_no_part_as_dissent=treat_no_part,
                )
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

    # ===================================================================
    # Sub-tabs: Graph View | Temporal Analysis | Temporal Network
    # ===================================================================
    net_sub1, net_sub2, net_sub3 = st.tabs(["Graph View", "Temporal Analysis", "Temporal Network"])

    # --- Sub-tab 1: Graph View ---
    with net_sub1:
        # Display controls
        dc1, dc2, dc3 = st.columns(3)
        edge_thresh = dc1.slider("Edge Weight Threshold", 0, 500, 0, 10, key="net_edge_thresh",
            help="Hide edges with weight below this value to reduce visual clutter")
        size_options = {"Weighted Degree": "weighted_degree", "Case Count": "case_count", "Uniform": "uniform"}
        size_label = dc2.selectbox("Node Size By", list(size_options.keys()), key="net_size_by",
            help="What determines node size: total edge weight, number of cases participated in, or equal size")
        size_by = size_options[size_label]
        layout_options = {"Interactive Physics": "physics", "Community Clusters": "community"}
        layout_label = dc3.selectbox("Layout", list(layout_options.keys()), key="net_layout",
            help="Physics: draggable nodes with live simulation. Community: fixed positions grouped by Louvain cluster")
        layout_mode = layout_options[layout_label]

        dc4, dc5, dc6, dc7, dc8 = st.columns(5)
        curved_edges = dc4.checkbox("Curved edges", value=True, key="net_curved",
            help="Use curved lines between nodes to reduce edge overlap")
        opacity_scaling = dc5.checkbox("Opacity scaling", value=True, key="net_opacity",
            help="Make stronger edges more opaque and weaker edges more transparent")
        graph_height = dc6.slider("Graph Height", 400, 1200, 700, 50, key="net_height",
            help="Height of the graph canvas in pixels")
        color_options = {"Community (Louvain)": "community", "Appointed By": "appointed_by"}
        color_label = dc7.selectbox("Color By", list(color_options.keys()), key="net_color_mode",
            help="Color nodes by Louvain community cluster or by appointing president")
        color_mode = color_options[color_label]
        show_hulls = dc8.checkbox("Community boundaries", value=False, key="net_hulls",
            help="Draw dashed convex hull outlines around each Louvain community")

        # Community separation tuning
        lc1, lc2, lc3 = st.columns(3)
        centroid_radius_base = lc1.slider("Centroid Radius", 4.0, 30.0, 10.0, 1.0, key="net_centroid_r",
            help="How far apart community centers are placed — higher = more separation between clusters")
        jitter_scale = lc2.slider("Jitter Scale", 0.05, 1.0, 0.25, 0.05, key="net_jitter",
            help="How spread out members are within a community — lower = tighter clusters")
        repulsion_k = lc3.slider("Repulsion K", 2.0, 20.0, 8.0, 0.5, key="net_repulsion",
            help="Spring layout repulsion strength — higher = nodes push each other further apart")

        # Display when graph exists
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
                show_community_hulls=show_hulls,
                centroid_radius_base=centroid_radius_base,
                jitter_scale=jitter_scale,
                repulsion_k=repulsion_k,
            )
            st.session_state.network_html = html
            components.html(html, height=graph_height + 20, scrolling=True)

            # Details expanders
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

            # Download buttons
            st.subheader("Downloads")
            dl1, dl2, dl3 = st.columns(3)

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

            dl4, dl5, dl6 = st.columns(3)

            if st.session_state.network_html:
                dl4.download_button(
                    "Interactive Graph (HTML)",
                    data=st.session_state.network_html,
                    file_name="justice_network.html",
                    mime="text/html",
                    key="dl_html",
                )

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

    # --- Sub-tab 2: Temporal Analysis ---
    with net_sub2:
        import plotly.express as px
        import plotly.graph_objects as go

        # Temporal-specific controls
        tc1, tc2, tc3 = st.columns(3)
        t_window = tc1.slider("Window Size (years)", 1, 10, 3, 1, key="t_window",
            help="Width of each sliding time window in years")
        t_step = tc2.slider("Step (months)", 3, 24, 6, 3, key="t_step",
            help="How far the window slides between calculations")
        t_min_dissents = tc3.slider("Min Dissents", 1, 20, 5, 1, key="t_min_dissents",
            help="Only include justices with at least this many dissents in affinity metrics")

        compute_temporal = st.button("Compute Temporal", key="run_temporal", type="primary")

        if compute_temporal:
            if not csv_path.exists():
                st.error(f"CSV not found: {csv_path}")
            else:
                with st.spinner("Computing temporal analysis (all metrics)..."):
                    justices_csv = repo_root / "ph_sc_justices.csv"
                    div_filt_ta = division_filter if len(division_filter) < len(division_all) else None
                    cases = load_cases(
                        str(csv_path),
                        min_confidence=min_conf,
                        division_filter=div_filt_ta,
                        dissent_filter=dissent_filter,
                        treat_no_part_as_dissent=treat_no_part,
                    )
                    tenures = load_tenures(str(justices_csv))
                    analyzer = TemporalAnalyzer(cases, tenures)
                    st.session_state.temporal_analyzer = analyzer
                    st.session_state.temporal_summary = analyzer.summary()

                    # Pre-compute all windowed DataFrames for step-based viewing
                    windowed = {}
                    windowed["dissent_rate"] = analyzer.dissent_rate_timeline(t_window, t_step)
                    windowed["dissent_affinity"] = analyzer.dissent_affinity_windowed(
                        t_window, t_step, t_min_dissents)
                    windowed["bloc_deviation"] = analyzer.bloc_deviation(t_window, t_step)
                    windowed["temporal_drift"] = analyzer.temporal_drift(t_window, t_step)
                    windowed["agreement"] = analyzer.agreement_normalized_windowed(
                        t_window, t_step, min_shared_cases=5)
                    # Global (non-windowed) versions for timeline view
                    windowed["dissent_affinity_global"] = analyzer.dissent_affinity(t_min_dissents)
                    windowed["agreement_global"] = analyzer.agreement_normalized(
                        min_shared_cases=20)
                    # Court-wide dissent rate (all 4 combos)
                    windowed["court_dissent_rate"] = court_dissent_rate_timeline(
                        str(csv_path), DISSENT_RATE_COMBOS,
                        window_years=t_window, step_months=t_step,
                        min_confidence=min_conf,
                    )
                    st.session_state.ta_windowed_data = windowed

                    # Extract unique window centers across all windowed metrics
                    all_centers = set()
                    for key in ["dissent_rate", "bloc_deviation", "temporal_drift",
                                "dissent_affinity", "agreement"]:
                        df_tmp = windowed[key]
                        if not df_tmp.empty and "window_center" in df_tmp.columns:
                            all_centers.update(df_tmp["window_center"].unique())
                    st.session_state.ta_windows = sorted(all_centers)
                    st.session_state.ta_step = 0
                    st.session_state.ta_params = {
                        "window_years": t_window,
                        "step_months": t_step,
                        "min_dissents": t_min_dissents,
                        "treat_no_part_as_dissent": treat_no_part,
                        "division_filter": division_filter,
                        "dissent_filter": dissent_filter,
                        "min_confidence": min_conf,
                    }
                st.success(f"Loaded {st.session_state.temporal_summary['total_cases']} cases, "
                           f"{st.session_state.temporal_summary['unique_justices']} justices")

        analyzer = st.session_state.temporal_analyzer
        if analyzer is not None:
            summary = st.session_state.temporal_summary
            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("Cases", summary["total_cases"])
            sm2.metric("With Dissent", summary["cases_with_dissent"])
            sm3.metric("With No Part", summary["cases_with_no_part"])
            sm4.metric("Justices", summary["unique_justices"])

            # View mode + metric selector
            vm_col, metric_col = st.columns([1, 3])
            view_mode = vm_col.radio(
                "View", ["Timeline", "Step View"], key="t_view_mode", horizontal=True,
                help="Timeline shows all steps; Step View lets you scroll through individual windows",
            )
            metric_options = [
                "Dissent Rate Timeline",
                "Dissent Affinity",
                "Bloc Deviation",
                "Temporal Drift",
                "Agreement vs Expected",
                "Court-wide Dissent Rate",
            ]
            selected_metric = metric_col.selectbox("Metric", metric_options, key="t_metric",
                help="Choose which temporal voting metric to visualize")

            # President color map for plotly
            _pres_color_map = {**PRESIDENT_COLORS, "Unknown": FALLBACK_COLOR}

            # Windowed data (pre-computed on Compute)
            ta_data = st.session_state.ta_windowed_data
            ta_windows = st.session_state.ta_windows

            # --- Step slider for Step View ---
            _ta_current_center = None
            if view_mode == "Step View":
                if not ta_windows:
                    st.warning("No window data — click **Compute Temporal** first.")
                else:
                    from datetime import timedelta as _td
                    num_ta_steps = len(ta_windows)
                    if st.session_state.ta_step >= num_ta_steps:
                        st.session_state.ta_step = num_ta_steps - 1

                    def _on_ta_step_change():
                        st.session_state.ta_step = st.session_state._ta_step_slider

                    st.slider(
                        "Window Step", 0, num_ta_steps - 1,
                        value=st.session_state.ta_step,
                        key="_ta_step_slider",
                        on_change=_on_ta_step_change,
                        help="Scroll through individual time windows.",
                    )
                    _ta_current_center = ta_windows[st.session_state.ta_step]
                    params = st.session_state.ta_params
                    _half_win = int(params.get("window_years", 3) * 365.25 / 2)
                    _w_start = _ta_current_center - _td(days=_half_win)
                    _w_end = _ta_current_center + _td(days=_half_win)
                    st.caption(
                        f"**Step {st.session_state.ta_step + 1}/{num_ta_steps}** — "
                        f"{_w_start.strftime('%b %Y')} to {_w_end.strftime('%b %Y')}"
                    )

            # =================================================================
            # Step-view figure builders
            # =================================================================

            def _build_step_fig_dissent_rate(df_step):
                """Bar chart of dissent rates for one window step."""
                df_s = df_step[df_step["dissent_count"] > 0].sort_values(
                    "dissent_rate", ascending=True)
                if df_s.empty:
                    return None
                fig = px.bar(
                    df_s, x="dissent_rate", y="justice", orientation="h",
                    color="appointed_by", color_discrete_map=_pres_color_map,
                    hover_data=["cases_participated", "dissent_count"],
                    labels={"dissent_rate": "Dissent Rate", "justice": ""},
                    title="Dissent Rate (this window)",
                )
                fig.update_layout(template="plotly_dark",
                                  height=max(350, len(df_s) * 28))
                return fig

            def _build_step_fig_affinity(df_step):
                """Heatmap of co-dissent for one window step."""
                if df_step.empty:
                    return None
                justices_in = sorted(
                    set(df_step["justice_a"]) | set(df_step["justice_b"]))
                matrix = pd.DataFrame(0.0, index=justices_in, columns=justices_in)
                for _, row in df_step.iterrows():
                    matrix.loc[row["justice_a"], row["justice_b"]] = row["co_dissent_rate"]
                    matrix.loc[row["justice_b"], row["justice_a"]] = row["co_dissent_rate"]
                fig = px.imshow(
                    matrix, text_auto=".2f",
                    labels={"color": "Co-Dissent Rate"},
                    title="Dissent Affinity (this window)",
                    color_continuous_scale="YlOrRd",
                )
                fig.update_layout(template="plotly_dark",
                                  height=max(400, len(justices_in) * 32))
                return fig

            def _build_step_fig_bloc(df_step):
                """Bar chart of bloc deviation for one window step."""
                df_s = df_step[df_step["against_bloc"] > 0].sort_values(
                    "deviation_score", ascending=True)
                if df_s.empty:
                    return None
                fig = px.bar(
                    df_s, x="deviation_score", y="justice", orientation="h",
                    color="appointed_by", color_discrete_map=_pres_color_map,
                    hover_data=["cases_in_window", "with_bloc", "against_bloc"],
                    labels={"deviation_score": "Bloc Deviation", "justice": ""},
                    title="Bloc Deviation (this window)",
                )
                fig.update_layout(template="plotly_dark",
                                  height=max(350, len(df_s) * 28))
                return fig

            def _build_step_fig_drift(df_step, y_col="alignment_with_court"):
                """Bar chart of alignment metrics for one window step."""
                if df_step.empty:
                    return None
                df_s = df_step.sort_values(y_col, ascending=True)
                fig = px.bar(
                    df_s, x=y_col, y="justice", orientation="h",
                    color="appointed_by", color_discrete_map=_pres_color_map,
                    hover_data=["cases_in_window", "alignment_with_court",
                                "alignment_with_own_bloc", "dissent_rate"],
                    labels={y_col: y_col.replace("_", " ").title(), "justice": ""},
                    title=f"{y_col.replace('_', ' ').title()} (this window)",
                )
                fig.update_layout(template="plotly_dark",
                                  height=max(350, len(df_s) * 28))
                return fig

            def _build_step_fig_agreement(df_step):
                """Scatter plot of agreement vs expected for one window step."""
                if df_step.empty:
                    return None
                fig = px.scatter(
                    df_step, x="expected_agreement", y="observed_agreement",
                    color="same_bloc",
                    hover_data=["justice_a", "justice_b",
                                "cases_both_participated", "affinity_score"],
                    labels={
                        "expected_agreement": "Expected Agreement",
                        "observed_agreement": "Observed Agreement",
                        "same_bloc": "Same Appointment Bloc",
                    },
                    title="Agreement vs Expected (this window)",
                    color_discrete_map={True: "#4dff91", False: "#ff4d6a"},
                )
                fig.add_trace(go.Scatter(
                    x=[0.5, 1.0], y=[0.5, 1.0],
                    mode="lines", line=dict(dash="dash", color="gray"),
                    showlegend=False,
                ))
                fig.update_layout(template="plotly_dark", height=550)
                return fig

            # --- Dissent Rate Timeline ---
            if selected_metric == "Dissent Rate Timeline":
                df = ta_data["dissent_rate"] if ta_data else analyzer.dissent_rate_timeline(t_window, t_step)
                if df.empty:
                    st.info("No data for the selected parameters.")
                elif view_mode == "Step View" and _ta_current_center is not None:
                    df_step = df[df["window_center"] == _ta_current_center]
                    fig = _build_step_fig_dissent_rate(df_step)
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No dissents in this window.")
                    with st.expander("Raw Data (this step)", expanded=False):
                        st.dataframe(df_step.sort_values("dissent_rate", ascending=False))
                else:
                    justices_with_dissent = df[df["dissent_count"] > 0]["justice"].unique().tolist()
                    selected_justices = st.multiselect(
                        "Justices", sorted(justices_with_dissent),
                        default=sorted(justices_with_dissent)[:10],
                        key="t_dr_justices",
                        help="Select justices to display on the chart",
                    )
                    if selected_justices:
                        plot_df = df[df["justice"].isin(selected_justices)]
                        fig = px.line(
                            plot_df, x="window_center", y="dissent_rate",
                            color="justice", hover_data=["cases_participated", "dissent_count", "appointed_by"],
                            labels={"window_center": "Date", "dissent_rate": "Dissent Rate"},
                            title="Dissent Rate Over Time",
                            color_discrete_sequence=px.colors.qualitative.Set2,
                        )
                        fig.update_layout(template="plotly_dark", height=500)
                        st.plotly_chart(fig, use_container_width=True)

                    with st.expander("Raw Data", expanded=False):
                        st.dataframe(df[df["dissent_count"] > 0].sort_values(
                            ["window_center", "dissent_rate"], ascending=[True, False]))

            # --- Dissent Affinity ---
            elif selected_metric == "Dissent Affinity":
                if view_mode == "Step View" and _ta_current_center is not None:
                    df_w = ta_data["dissent_affinity"] if ta_data else pd.DataFrame()
                    df_step = df_w[df_w["window_center"] == _ta_current_center] if not df_w.empty else pd.DataFrame()
                    fig = _build_step_fig_affinity(df_step)
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No co-dissent pairs in this window (try lowering Min Dissents).")
                    with st.expander("Raw Data (this step)", expanded=False):
                        if not df_step.empty:
                            st.dataframe(df_step.sort_values("co_dissent_count", ascending=False))
                        else:
                            st.caption("No data.")
                else:
                    df = (ta_data.get("dissent_affinity_global")
                          if ta_data else analyzer.dissent_affinity(t_min_dissents))
                    if df is None or df.empty:
                        st.info(f"No justice pairs found with >= {t_min_dissents} dissents each.")
                    else:
                        justices_in_df = sorted(set(df["justice_a"]) | set(df["justice_b"]))
                        matrix = pd.DataFrame(0.0, index=justices_in_df, columns=justices_in_df)
                        for _, row in df.iterrows():
                            matrix.loc[row["justice_a"], row["justice_b"]] = row["co_dissent_rate"]
                            matrix.loc[row["justice_b"], row["justice_a"]] = row["co_dissent_rate"]

                        fig = px.imshow(
                            matrix, text_auto=".2f",
                            labels={"color": "Co-Dissent Rate"},
                            title="Dissent Affinity Heatmap (how often two dissenters dissent together)",
                            color_continuous_scale="YlOrRd",
                        )
                        fig.update_layout(template="plotly_dark", height=600)
                        st.plotly_chart(fig, use_container_width=True)

                        with st.expander("Dissent Against (who dissents when whom is in majority)", expanded=False):
                            df_against = analyzer.dissent_against(t_min_dissents)
                            if not df_against.empty:
                                st.dataframe(df_against.head(50))

                        with st.expander("Raw Affinity Data", expanded=False):
                            st.dataframe(df.sort_values("co_dissent_count", ascending=False))

            # --- Bloc Deviation ---
            elif selected_metric == "Bloc Deviation":
                df = ta_data["bloc_deviation"] if ta_data else analyzer.bloc_deviation(t_window, t_step)
                if df.empty:
                    st.info("No data for the selected parameters.")
                elif view_mode == "Step View" and _ta_current_center is not None:
                    df_step = df[df["window_center"] == _ta_current_center]
                    fig = _build_step_fig_bloc(df_step)
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No bloc deviations in this window.")
                    with st.expander("Raw Data (this step)", expanded=False):
                        st.dataframe(df_step.sort_values("deviation_score", ascending=False))
                else:
                    deviators = df[df["against_bloc"] > 0]["justice"].unique().tolist()
                    selected_justices = st.multiselect(
                        "Justices", sorted(deviators),
                        default=sorted(deviators)[:10],
                        key="t_bd_justices",
                        help="Select justices to display",
                    )
                    if selected_justices:
                        plot_df = df[df["justice"].isin(selected_justices)]
                        fig = px.line(
                            plot_df, x="window_center", y="deviation_score",
                            color="justice",
                            hover_data=["cases_in_window", "with_bloc", "against_bloc", "appointed_by"],
                            labels={"window_center": "Date", "deviation_score": "Bloc Deviation"},
                            title="Bloc Deviation Over Time (fraction of votes against own appointment bloc)",
                            color_discrete_sequence=px.colors.qualitative.Set2,
                        )
                        fig.update_layout(template="plotly_dark", height=500)
                        st.plotly_chart(fig, use_container_width=True)

                    with st.expander("Raw Data", expanded=False):
                        st.dataframe(df[df["against_bloc"] > 0].sort_values(
                            ["window_center", "deviation_score"], ascending=[True, False]))

            # --- Temporal Drift ---
            elif selected_metric == "Temporal Drift":
                df = ta_data["temporal_drift"] if ta_data else analyzer.temporal_drift(t_window, t_step)
                if df.empty:
                    st.info("No data for the selected parameters.")
                else:
                    drift_y = st.selectbox("Y-axis", [
                        "alignment_with_court", "alignment_with_own_bloc", "dissent_rate",
                    ], key="t_td_y", help="Which alignment metric to plot")

                    if view_mode == "Step View" and _ta_current_center is not None:
                        df_step = df[df["window_center"] == _ta_current_center]
                        fig = _build_step_fig_drift(df_step, drift_y)
                        if fig:
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.info("No data in this window.")
                        with st.expander("Raw Data (this step)", expanded=False):
                            st.dataframe(df_step.sort_values(drift_y, ascending=False))
                    else:
                        drift_justices = df["justice"].unique().tolist()
                        selected_justices = st.multiselect(
                            "Justices", sorted(drift_justices),
                            default=sorted(drift_justices)[:8],
                            key="t_td_justices",
                            help="Select justices to display",
                        )
                        if selected_justices:
                            plot_df = df[df["justice"].isin(selected_justices)]
                            fig = px.line(
                                plot_df, x="window_center", y=drift_y,
                                color="justice",
                                hover_data=["cases_in_window", "appointed_by"],
                                labels={"window_center": "Date", drift_y: drift_y.replace("_", " ").title()},
                                title=f"Temporal Drift: {drift_y.replace('_', ' ').title()}",
                                color_discrete_sequence=px.colors.qualitative.Set2,
                            )
                            fig.update_layout(template="plotly_dark", height=500)
                            st.plotly_chart(fig, use_container_width=True)

                        with st.expander("Raw Data", expanded=False):
                            st.dataframe(df.sort_values(["window_center", "justice"]))

            # --- Agreement vs Expected ---
            elif selected_metric == "Agreement vs Expected":
                if view_mode == "Step View" and _ta_current_center is not None:
                    df_w = ta_data["agreement"] if ta_data else pd.DataFrame()
                    df_step = df_w[df_w["window_center"] == _ta_current_center] if not df_w.empty else pd.DataFrame()
                    fig = _build_step_fig_agreement(df_step)
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No pairs with enough shared cases in this window.")

                    if not df_step.empty:
                        df_sorted = df_step.sort_values("affinity_score")
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown("**Most Unusual Friction** (this window)")
                            st.dataframe(df_sorted.head(10)[["justice_a", "justice_b", "affinity_score",
                                                              "observed_agreement", "expected_agreement",
                                                              "cases_both_participated"]])
                        with col_b:
                            st.markdown("**Most Unusual Alliance** (this window)")
                            st.dataframe(df_sorted.tail(10).iloc[::-1][["justice_a", "justice_b", "affinity_score",
                                                                         "observed_agreement", "expected_agreement",
                                                                         "cases_both_participated"]])
                    with st.expander("Raw Data (this step)", expanded=False):
                        if not df_step.empty:
                            st.dataframe(df_step.sort_values("affinity_score"))
                        else:
                            st.caption("No data.")
                else:
                    min_shared = st.slider("Min Shared Cases", 5, 100, 20, 5, key="t_min_shared",
                        help="Only show pairs that participated in at least this many shared cases")
                    df = (ta_data.get("agreement_global")
                          if ta_data else analyzer.agreement_normalized(min_shared_cases=min_shared))
                    if df is None or df.empty:
                        st.info(f"No pairs with >= {min_shared} shared cases.")
                    else:
                        fig = px.scatter(
                            df, x="expected_agreement", y="observed_agreement",
                            color="same_bloc",
                            hover_data=["justice_a", "justice_b", "cases_both_participated", "affinity_score"],
                            labels={
                                "expected_agreement": "Expected Agreement",
                                "observed_agreement": "Observed Agreement",
                                "same_bloc": "Same Appointment Bloc",
                            },
                            title="Agreement vs Expected (below diagonal = unusual friction)",
                            color_discrete_map={True: "#4dff91", False: "#ff4d6a"},
                        )
                        fig.add_trace(go.Scatter(
                            x=[0.9, 1.0], y=[0.9, 1.0],
                            mode="lines", line=dict(dash="dash", color="gray"),
                            showlegend=False,
                        ))
                        fig.update_layout(template="plotly_dark", height=550)
                        st.plotly_chart(fig, use_container_width=True)

                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown("**Most Unusual Friction** (lowest affinity)")
                            st.dataframe(df.head(10)[["justice_a", "justice_b", "affinity_score",
                                                       "observed_agreement", "expected_agreement",
                                                       "cases_both_participated"]])
                        with col_b:
                            st.markdown("**Most Unusual Alliance** (highest affinity)")
                            st.dataframe(df.tail(10).iloc[::-1][["justice_a", "justice_b", "affinity_score",
                                                                  "observed_agreement", "expected_agreement",
                                                                  "cases_both_participated"]])

            elif selected_metric == "Court-wide Dissent Rate":
                cdr_df = ta_data.get("court_dissent_rate", pd.DataFrame()) if ta_data else pd.DataFrame()
                if cdr_df.empty:
                    st.info("Click **Compute Temporal** to generate court-wide dissent rates.")
                else:
                    all_combos = sorted(cdr_df["combo"].unique())
                    selected_combos = st.multiselect(
                        "Filter combinations to display",
                        all_combos, default=all_combos,
                        key="cdr_combos",
                    )
                    cdr_filtered = cdr_df[cdr_df["combo"].isin(selected_combos)]

                    if view_mode == "Step View" and _ta_current_center is not None:
                        # For each combo, find the row with the closest window_center
                        step_rows_list = []
                        params = st.session_state.ta_params
                        step_days = int(params.get("step_months", 6) * 30.44)
                        for combo_lbl in selected_combos:
                            combo_df = cdr_filtered[cdr_filtered["combo"] == combo_lbl]
                            if combo_df.empty:
                                continue
                            diffs = (combo_df["window_center"] - _ta_current_center).abs()
                            closest_idx = diffs.idxmin()
                            if diffs.loc[closest_idx].days <= step_days:
                                step_rows_list.append(combo_df.loc[closest_idx])
                        df_step = pd.DataFrame(step_rows_list) if step_rows_list else pd.DataFrame()

                        if not df_step.empty:
                            step_rows = []
                            for _, r in df_step.iterrows():
                                step_rows.append({
                                    "Combination": r["combo"],
                                    "Total Cases": r["total_cases"],
                                    "Dissent Cases": r["dissent_cases"],
                                    "Dissent Rate": f"{r['dissent_rate']:.1%}",
                                })
                            st.dataframe(pd.DataFrame(step_rows), use_container_width=True, hide_index=True)
                        else:
                            st.caption("No data for this window step.")
                    else:
                        # Timeline view: line chart with justice composition overlay
                        if not cdr_filtered.empty:
                            import plotly.graph_objects as go
                            fig = go.Figure()

                            # --- Background: stacked bars of justice count by president ---
                            _PRES_ORDER_CDR = [
                                "Ferdinand Marcos", "Corazon Aquino", "Fidel V. Ramos",
                                "Joseph Estrada", "Gloria Macapagal Arroyo",
                                "Benigno Aquino III", "Rodrigo Duterte", "Bongbong Marcos",
                            ]
                            from datetime import date as _date
                            justices_csv_cdr = str(Path(__file__).parent / "ph_sc_justices.csv")
                            tenures_cdr = load_tenures(justices_csv_cdr)
                            window_centers = sorted(cdr_filtered["window_center"].unique())
                            # Get window start/end from the data
                            wc_to_range = {}
                            for _, r in cdr_filtered.drop_duplicates("window_center").iterrows():
                                wc_to_range[r["window_center"]] = (r["window_start"], r["window_end"])

                            # Count active justices per president per window
                            pres_counts: dict[str, list[int]] = {p: [] for p in _PRES_ORDER_CDR}
                            for wc in window_centers:
                                ws, we = wc_to_range[wc]
                                by_pres: dict[str, int] = {}
                                for name, t in tenures_cdr.items():
                                    t_start = t.tenure_start or _date.min
                                    t_end = t.tenure_end or _date.max
                                    if t_start < we and t_end > ws:
                                        by_pres[t.appointed_by] = by_pres.get(t.appointed_by, 0) + 1
                                for p in _PRES_ORDER_CDR:
                                    pres_counts[p].append(by_pres.get(p, 0))

                            # Add stacked bars (oldest president at bottom)
                            for p in _PRES_ORDER_CDR:
                                counts = pres_counts[p]
                                if any(c > 0 for c in counts):
                                    fig.add_trace(go.Bar(
                                        x=window_centers, y=counts,
                                        name=p,
                                        marker_color=PRESIDENT_COLORS.get(p, FALLBACK_COLOR),
                                        opacity=0.25,
                                        yaxis="y2",
                                        hovertemplate=f"{p}: %{{y}} justices<extra></extra>",
                                    ))

                            # --- Foreground: dissent rate lines ---
                            _line_colors = ["#ff1744", "#00e5ff", "#ffd600", "#76ff03"]
                            for i, combo_lbl in enumerate(selected_combos):
                                combo_df = cdr_filtered[cdr_filtered["combo"] == combo_lbl].sort_values("window_center")
                                fig.add_trace(go.Scatter(
                                    x=combo_df["window_center"], y=combo_df["dissent_rate"],
                                    mode="lines+markers",
                                    name=combo_lbl,
                                    line=dict(color=_line_colors[i % len(_line_colors)], width=3),
                                    marker=dict(size=5),
                                    yaxis="y",
                                    customdata=list(zip(combo_df["total_cases"], combo_df["dissent_cases"])),
                                    hovertemplate=(
                                        f"<b>{combo_lbl}</b><br>"
                                        "Rate: %{y:.1%}<br>"
                                        "Dissent: %{customdata[1]} / %{customdata[0]} cases"
                                        "<extra></extra>"
                                    ),
                                ))

                            fig.update_layout(
                                template="plotly_dark", height=550,
                                title="Court-wide Dissent Rate Over Time",
                                barmode="stack",
                                yaxis=dict(
                                    title="Dissent Rate",
                                    tickformat=".0%",
                                    side="left",
                                    overlaying="y2",
                                    range=[0, None],
                                ),
                                yaxis2=dict(
                                    title="Active Justices",
                                    side="right",
                                    range=[0, None],
                                ),
                                xaxis=dict(title=""),
                                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                            )
                            st.plotly_chart(fig, use_container_width=True)

                    # Full table (always shown below chart/step view)
                    if not cdr_filtered.empty:
                        st.markdown("**Dissent Rate Table**")
                        # Pivot: rows=windows, columns=combos
                        pivot_data = []
                        for wc in sorted(cdr_filtered["window_center"].unique()):
                            wdf = cdr_filtered[cdr_filtered["window_center"] == wc]
                            first_row = wdf.iloc[0]
                            row_dict = {
                                "window_start": first_row["window_start"],
                                "window_end": first_row["window_end"],
                            }
                            for _, r in wdf.iterrows():
                                lbl = r["combo"]
                                row_dict[f"{lbl} (cases)"] = f"{r['dissent_cases']}/{r['total_cases']}"
                                row_dict[f"{lbl} (rate)"] = f"{r['dissent_rate']:.1%}"
                            pivot_data.append(row_dict)
                        pivot_df = pd.DataFrame(pivot_data)
                        st.dataframe(pivot_df, use_container_width=True, hide_index=True)

                        # Download CSV (raw, not formatted)
                        csv_buf = cdr_filtered.to_csv(index=False)
                        st.download_button(
                            "Download Court-wide Dissent Rate (CSV)",
                            csv_buf, "court_dissent_rate.csv", "text/csv",
                            key="cdr_dl_csv",
                        )

            # =================================================================
            # Export All Steps
            # =================================================================
            if ta_data and ta_windows:
                st.divider()
                with st.expander("Export All Steps", expanded=False):
                    st.markdown(
                        "Export **per-step graphs** (PNG or HTML) and **raw data** (CSV) "
                        "for every window step across all 5 metrics, plus a `run_variables.json`."
                    )

                    if st.button("Save All Step Exports", key="ta_export_all", type="secondary"):
                        import os
                        from datetime import datetime as _dt, timedelta as _tdelta

                        timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")
                        save_dir = Path(__file__).parent / "exports" / f"temporal_analysis_{timestamp}"
                        save_dir.mkdir(parents=True, exist_ok=True)

                        _can_img = True
                        try:
                            import kaleido  # noqa: F401
                        except ImportError:
                            _can_img = False

                        params = st.session_state.ta_params
                        _half_win = int(params.get("window_years", 3) * 365.25 / 2)

                        num_windows = len(ta_windows)
                        # 5 metrics × num_windows graphs + 5 consolidated CSVs + 1 run_vars
                        total_items = 5 * num_windows + 6
                        progress = st.progress(0, text="Exporting...")
                        done = 0

                        _metric_keys = [
                            ("dissent_rate", "dissent_rate"),
                            ("dissent_affinity", "dissent_affinity"),
                            ("bloc_deviation", "bloc_deviation"),
                            ("temporal_drift", "temporal_drift"),
                            ("agreement", "agreement"),
                        ]

                        for mk, dk in _metric_keys:
                            df_full = ta_data.get(dk, pd.DataFrame())
                            metric_dir = save_dir / mk
                            metric_dir.mkdir(exist_ok=True)

                            step_rows = []

                            for si, wc in enumerate(ta_windows):
                                wlabel = f"step{si:03d}_{wc.strftime('%Y%m%d')}"

                                if not df_full.empty and "window_center" in df_full.columns:
                                    df_step = df_full[df_full["window_center"] == wc]
                                else:
                                    df_step = pd.DataFrame()

                                # Build per-step figure
                                fig = None
                                if mk == "dissent_rate":
                                    fig = _build_step_fig_dissent_rate(df_step)
                                elif mk == "dissent_affinity":
                                    fig = _build_step_fig_affinity(df_step)
                                elif mk == "bloc_deviation":
                                    fig = _build_step_fig_bloc(df_step)
                                elif mk == "temporal_drift":
                                    fig = _build_step_fig_drift(df_step, "alignment_with_court")
                                elif mk == "agreement":
                                    fig = _build_step_fig_agreement(df_step)

                                if fig is not None:
                                    if _can_img:
                                        fig.write_image(str(metric_dir / f"{mk}_{wlabel}.png"), scale=2)
                                    else:
                                        fig.write_html(str(metric_dir / f"{mk}_{wlabel}.html"))

                                # Save per-step CSV
                                if not df_step.empty:
                                    df_step.to_csv(metric_dir / f"{mk}_{wlabel}.csv", index=False)

                                # Collect for consolidated CSV
                                if not df_step.empty:
                                    step_copy = df_step.copy()
                                    step_copy.insert(0, "step", si)
                                    step_rows.append(step_copy)

                                done += 1
                                progress.progress(
                                    done / total_items,
                                    text=f"{mk} step {si+1}/{num_windows}",
                                )

                            # Consolidated CSV per metric (all steps)
                            if step_rows:
                                pd.concat(step_rows, ignore_index=True).to_csv(
                                    save_dir / f"{mk}_all_steps.csv", index=False,
                                )
                            done += 1
                            progress.progress(done / total_items, text=f"{mk} — consolidated CSV")

                        # Run variables JSON
                        window_summaries = []
                        for si, wc in enumerate(ta_windows):
                            _ws = wc - _tdelta(days=_half_win)
                            _we = wc + _tdelta(days=_half_win)
                            step_info = {
                                "step": si,
                                "window_center": str(wc),
                                "window_start": str(_ws),
                                "window_end": str(_we),
                            }
                            for mk, dk in _metric_keys:
                                df_full = ta_data.get(dk, pd.DataFrame())
                                if not df_full.empty and "window_center" in df_full.columns:
                                    df_s = df_full[df_full["window_center"] == wc]
                                    step_info[f"{mk}_rows"] = len(df_s)
                                else:
                                    step_info[f"{mk}_rows"] = 0
                            window_summaries.append(step_info)

                        run_vars = {
                            "timestamp": timestamp,
                            "total_windows": num_windows,
                            "image_format": "png" if _can_img else "html",
                            "summary": st.session_state.temporal_summary,
                            "parameters": params,
                            "windows": window_summaries,
                        }
                        with open(save_dir / "run_variables.json", "w", encoding="utf-8") as f:
                            json.dump(run_vars, f, indent=2, default=str)

                        progress.progress(1.0, text="Done!")
                        img_fmt = "PNG" if _can_img else "HTML (install kaleido for PNG)"
                        st.success(
                            f"Saved to `{save_dir.relative_to(Path(__file__).parent)}/`\n\n"
                            f"- 5 metric folders x {num_windows} steps ({img_fmt} + CSV each)\n"
                            f"- 5 consolidated CSVs (all steps per metric)\n"
                            f"- 1 `run_variables.json`"
                        )
        else:
            st.info("Click **Compute Temporal** to load and analyze voting patterns.")

    # =======================================================================
    # Sub-tab 3: Temporal Network
    # =======================================================================
    with net_sub3:
        import plotly.graph_objects as go
        from network.visualize import COMMUNITY_COLORS

        st.markdown("Animated community detection over sliding time windows.")

        # --- Controls ---
        tn_c1, tn_c2, tn_c3 = st.columns(3)
        tn_window = tn_c1.slider(
            "Window Size (years)", 1, 10, 3, 1, key="tn_window",
            help="Width of each sliding window in years.",
        )
        tn_step_size = tn_c2.slider(
            "Step Size (months)", 3, 24, 6, 3, key="tn_step_size",
            help="How far the window advances between steps.",
        )
        tn_edge_thresh = tn_c3.slider(
            "Edge Threshold", 0, 50, 0, 1, key="tn_edge_thresh",
            help="Hide edges with co-voting weight below this value.",
        )

        # --- Compute button ---
        if st.button("Compute Network Timeline", key="tn_compute", type="primary"):
            with st.spinner("Building temporal network snapshots..."):
                tn_csv_path = str(csv_path)
                justices_csv = str(Path(__file__).parent / "ph_sc_justices.csv")
                div_filt_tn = division_filter if len(division_filter) < len(division_all) else None
                cases = load_cases(
                    tn_csv_path,
                    min_confidence=min_conf,
                    division_filter=div_filt_tn,
                    dissent_filter=dissent_filter,
                    treat_no_part_as_dissent=treat_no_part,
                )
                tenures = load_tenures(justices_csv)
                tn_builder = TemporalNetwork(
                    cases, tenures,
                    justices_csv_path=justices_csv,
                )
                snapshots = tn_builder.compute_snapshots(tn_window, tn_step_size)
                st.session_state.temporal_snapshots = snapshots
                st.session_state.tn_axis_range = compute_global_bounds(snapshots)
                st.session_state.tn_tenures = tenures
                st.session_state.tn_appointed_by = tn_builder._appointed_by
                st.session_state.tn_step = 0
                st.session_state.tn_playing = False
            st.success(f"Computed {len(snapshots)} snapshots from {len(cases)} cases.")

        # --- Display when snapshots exist ---
        if st.session_state.temporal_snapshots:
            snapshots = st.session_state.temporal_snapshots
            num_steps = len(snapshots)

            if num_steps == 0:
                st.warning("No snapshots produced — try a smaller window or different filters.")
            else:
                # Clamp step to valid range (snapshots may have been recomputed)
                if st.session_state.tn_step >= num_steps:
                    st.session_state.tn_step = num_steps - 1

                # Step slider — callback syncs value to canonical tn_step
                def _on_step_change():
                    st.session_state.tn_step = st.session_state._tn_step_slider

                st.slider(
                    "Step", 0, num_steps - 1,
                    value=st.session_state.tn_step,
                    key="_tn_step_slider",
                    on_change=_on_step_change,
                    help="Navigate through time windows.",
                )
                step = st.session_state.tn_step

                # Play controls
                play_col, speed_col = st.columns([1, 3])
                with play_col:
                    play_label = "⏸ Pause" if st.session_state.tn_playing else "▶ Play"
                    if st.button(play_label, key="tn_play_btn"):
                        st.session_state.tn_playing = not st.session_state.tn_playing
                        st.rerun()
                with speed_col:
                    tn_speed = st.slider(
                        "Speed (sec/step)", 0.5, 3.0, 1.0, 0.25, key="tn_speed",
                        help="Seconds between auto-play steps.",
                    )

                snap = snapshots[step]

                # Graph + Info columns
                graph_col, info_col = st.columns([2, 1])

                with graph_col:
                    fig = build_temporal_network_plotly(
                        snap, edge_threshold=tn_edge_thresh,
                        community_colors=COMMUNITY_COLORS,
                        axis_range=st.session_state.tn_axis_range,
                    )
                    st.plotly_chart(fig, use_container_width=True, key=f"tn_chart_{step}")

                    # Tenure timeline chart
                    if st.session_state.tn_tenures:
                        tenure_fig = build_tenure_timeline_plotly(
                            snap,
                            st.session_state.tn_tenures,
                            st.session_state.tn_appointed_by or {},
                        )
                        st.plotly_chart(tenure_fig, use_container_width=True, key=f"tn_tenure_{step}")

                with info_col:
                    # Window summary
                    st.markdown("**Window Summary**")
                    st.caption(
                        f"{snap.window_start.strftime('%b %Y')} — "
                        f"{snap.window_end.strftime('%b %Y')}"
                    )
                    m1, m2 = st.columns(2)
                    m1.metric("Cases", snap.cases_in_window)
                    m2.metric("Dissents", snap.dissent_count)
                    m3, m4 = st.columns(2)
                    m3.metric("Justices", snap.active_justices)
                    m4.metric("Communities", len(snap.communities))
                    if snap.stability is not None:
                        st.metric("Stability (Jaccard)", f"{snap.stability:.3f}")

                    # Community membership table (rows=communities, cols=appointed_by)
                    with st.expander("Community Membership", expanded=True):
                        G = snap.graph
                        # Build table: each row = community, cells = justice names grouped by president
                        comm_table_rows = []
                        all_presidents_in_window = set()
                        for cid, members in zip(snap.community_ids, snap.communities):
                            row = {"Community": cid}
                            by_pres: dict[str, list[str]] = {}
                            for name in sorted(members):
                                pres = G.nodes[name].get("appointed_by", "Unknown") if name in G.nodes else "Unknown"
                                by_pres.setdefault(pres, []).append(
                                    G.nodes[name].get("display_name", name) if name in G.nodes else name
                                )
                                all_presidents_in_window.add(pres)
                            for pres, names in by_pres.items():
                                row[pres] = ", ".join(names)
                            comm_table_rows.append(row)

                        # Order president columns chronologically
                        _PRES_ORDER = [
                            "Ferdinand Marcos", "Corazon Aquino", "Fidel V. Ramos",
                            "Joseph Estrada", "Gloria Macapagal Arroyo",
                            "Benigno Aquino III", "Rodrigo Duterte", "Bongbong Marcos",
                        ]
                        pres_cols = [p for p in _PRES_ORDER if p in all_presidents_in_window]
                        for p in sorted(all_presidents_in_window):
                            if p not in pres_cols:
                                pres_cols.append(p)

                        comm_df = pd.DataFrame(comm_table_rows)
                        comm_df = comm_df.reindex(columns=["Community"] + pres_cols, fill_value="")
                        st.dataframe(comm_df, use_container_width=True, hide_index=True)

                    # Transitions
                    with st.expander("Transitions", expanded=True):
                        entered = snap.transitions.get("entered", [])
                        exited = snap.transitions.get("exited", [])
                        if entered:
                            st.markdown(f"**Entered:** {', '.join(entered)}")
                        if exited:
                            st.markdown(f"**Exited:** {', '.join(exited)}")
                        if not entered and not exited:
                            st.caption("No changes from previous step.")

                    # Cross-Community Cases
                    with st.expander("Cross-Community Cases", expanded=False):
                        cc_cases = extract_cross_community_cases(snap)
                        if cc_cases:
                            cc_pct = len(cc_cases) / snap.cases_in_window * 100 if snap.cases_in_window else 0
                            st.caption(
                                f"{len(cc_cases)} / {snap.cases_in_window} cases "
                                f"({cc_pct:.1f}%) span community boundaries"
                            )

                            def _cc_badge(name, comm_id):
                                """Render a justice name as a colored badge by community."""
                                color = COMMUNITY_COLORS[comm_id % len(COMMUNITY_COLORS)]
                                return (
                                    f'<span style="background:{color}22;color:{color};'
                                    f'border:1px solid {color};border-radius:3px;'
                                    f'padding:1px 5px;margin:1px;display:inline-block;'
                                    f'font-size:0.85em;">'
                                    f'{extract_display_name(name)}'
                                    f'<sub style="opacity:0.7;font-size:0.75em;"> C{comm_id}</sub>'
                                    f'</span>'
                                )

                            html_parts = ['<table style="width:100%;border-collapse:collapse;font-size:0.9em;">']
                            html_parts.append(
                                '<tr style="border-bottom:2px solid #444;">'
                                '<th style="text-align:left;padding:4px;">Case</th>'
                                '<th style="text-align:left;padding:4px;">Majority</th>'
                                '<th style="text-align:left;padding:4px;">Dissent</th>'
                                '</tr>'
                            )
                            for cc in cc_cases:
                                # Majority column — badges per community
                                maj_html = " ".join(
                                    _cc_badge(n, cid)
                                    for cid, names in sorted(cc.majority_by_community.items())
                                    for n in names
                                )
                                # Dissent column
                                dis_html = " ".join(
                                    _cc_badge(n, cid)
                                    for cid, names in sorted(cc.dissent_by_community.items())
                                    for n in names
                                ) if cc.dissent_by_community else '<span style="opacity:0.4;">—</span>'

                                html_parts.append(
                                    f'<tr style="border-bottom:1px solid #333;">'
                                    f'<td style="padding:4px;vertical-align:top;">'
                                    f'<strong>{cc.case_number}</strong><br>'
                                    f'<span style="opacity:0.6;font-size:0.85em;">'
                                    f'Vol. {cc.volume} · {cc.date} · {cc.ponente}</span></td>'
                                    f'<td style="padding:4px;vertical-align:top;">{maj_html}</td>'
                                    f'<td style="padding:4px;vertical-align:top;">{dis_html}</td>'
                                    f'</tr>'
                                )
                            html_parts.append('</table>')
                            st.markdown("".join(html_parts), unsafe_allow_html=True)
                        else:
                            st.caption("No cross-community cases in this window.")

                # --- Exports for current window ---
                with st.expander("Export Current Window"):
                    G = snap.graph
                    window_label = (
                        f"{snap.window_start.strftime('%Y%m')}_"
                        f"{snap.window_end.strftime('%Y%m')}"
                    )

                    # Edge list CSV
                    edge_buf = io.StringIO()
                    wr = csv.writer(edge_buf)
                    wr.writerow(["source", "target", "weight"])
                    for u, v, d in sorted(G.edges(data=True), key=lambda e: -e[2]["weight"]):
                        wr.writerow([u, v, d["weight"]])
                    st.download_button(
                        "Edge List (CSV)", edge_buf.getvalue(),
                        f"edge_list_{window_label}.csv", "text/csv",
                        key=f"tn_dl_edge_{step}",
                    )

                    # Adjacency matrix CSV
                    nodes_sorted = sorted(G.nodes())
                    adj_buf = io.StringIO()
                    wr = csv.writer(adj_buf)
                    wr.writerow([""] + nodes_sorted)
                    for n in nodes_sorted:
                        row = [n]
                        for m in nodes_sorted:
                            row.append(G[n][m]["weight"] if G.has_edge(n, m) else 0)
                        wr.writerow(row)
                    st.download_button(
                        "Adjacency Matrix (CSV)", adj_buf.getvalue(),
                        f"adjacency_{window_label}.csv", "text/csv",
                        key=f"tn_dl_adj_{step}",
                    )

                    # Community membership CSV
                    comm_buf = io.StringIO()
                    wr = csv.writer(comm_buf)
                    wr.writerow(["justice", "community", "appointed_by"])
                    for cid, members in zip(snap.community_ids, snap.communities):
                        for name in sorted(members):
                            pres = G.nodes[name].get("appointed_by", "Unknown") if name in G.nodes else "Unknown"
                            wr.writerow([name, cid, pres])
                    st.download_button(
                        "Community Membership (CSV)", comm_buf.getvalue(),
                        f"communities_{window_label}.csv", "text/csv",
                        key=f"tn_dl_comm_{step}",
                    )

                    # Cross-community cases CSV
                    cc_export = extract_cross_community_cases(snap)
                    if cc_export:
                        cc_buf = io.StringIO()
                        wr = csv.writer(cc_buf)
                        wr.writerow([
                            "case_number", "volume", "date", "division", "ponente",
                            "cross_in_majority", "cross_in_dissent",
                            "communities_involved", "majority_votes", "dissent_votes",
                        ])
                        for cc in cc_export:
                            maj_parts = []
                            for cid, names in sorted(cc.majority_by_community.items()):
                                short = [extract_display_name(n) for n in names]
                                maj_parts.append(f"[C{cid}] {', '.join(short)}")
                            dis_parts = []
                            for cid, names in sorted(cc.dissent_by_community.items()):
                                short = [extract_display_name(n) for n in names]
                                dis_parts.append(f"[C{cid}] {', '.join(short)}")
                            wr.writerow([
                                cc.case_number, cc.volume, str(cc.date), cc.division, cc.ponente,
                                cc.cross_in_majority, cc.cross_in_dissent,
                                "|".join(str(c) for c in cc.communities_involved),
                                " | ".join(maj_parts),
                                " | ".join(dis_parts),
                            ])
                        st.download_button(
                            f"Cross-Community Cases ({len(cc_export)})", cc_buf.getvalue(),
                            f"cross_community_{window_label}.csv", "text/csv",
                            key=f"tn_dl_cross_{step}",
                        )

                    # Network stats JSON (includes community membership by president)
                    comm_json = []
                    for cid, members in zip(snap.community_ids, snap.communities):
                        by_pres: dict[str, list[str]] = {}
                        for name in sorted(members):
                            pres = G.nodes[name].get("appointed_by", "Unknown") if name in G.nodes else "Unknown"
                            by_pres.setdefault(pres, []).append(name)
                        comm_json.append({
                            "id": cid,
                            "members": sorted(members),
                            "by_appointed_by": by_pres,
                        })
                    stats = {
                        "window_start": str(snap.window_start),
                        "window_end": str(snap.window_end),
                        "cases": snap.cases_in_window,
                        "dissents": snap.dissent_count,
                        "nodes": snap.active_justices,
                        "edges": G.number_of_edges(),
                        "density": (
                            2 * G.number_of_edges() / (snap.active_justices * (snap.active_justices - 1))
                            if snap.active_justices > 1 else 0
                        ),
                        "communities": comm_json,
                        "stability_jaccard": snap.stability,
                        "entered": snap.transitions.get("entered", []),
                        "exited": snap.transitions.get("exited", []),
                    }
                    st.download_button(
                        "Network Stats (JSON)",
                        json.dumps(stats, indent=2),
                        f"network_stats_{window_label}.json",
                        "application/json",
                        key=f"tn_dl_stats_{step}",
                    )

                    # GraphML
                    graphml_buf = io.BytesIO()
                    nx.write_graphml(G, graphml_buf)
                    st.download_button(
                        "Graph (GraphML)",
                        graphml_buf.getvalue(),
                        f"network_{window_label}.graphml",
                        "application/xml",
                        key=f"tn_dl_graphml_{step}",
                    )

                # --- Cross-Community Summary (All Windows) ---
                with st.expander("Cross-Community Summary (All Windows)", expanded=False):
                    summary_df = compile_cross_community_summary(snapshots)
                    if not summary_df.empty:
                        total_cases_all = sum(s.cases_in_window for s in snapshots)
                        total_cc_all = sum(
                            len(extract_cross_community_cases(s)) for s in snapshots
                        )
                        cc_pct_all = total_cc_all / total_cases_all * 100 if total_cases_all else 0
                        st.caption(
                            f"{total_cc_all} / {total_cases_all} case-window instances "
                            f"({cc_pct_all:.1f}%) are cross-community across {num_steps} windows "
                            f"— {len(summary_df)} unique cases"
                        )
                        st.dataframe(
                            summary_df.drop(columns=["windows"]),
                            use_container_width=True,
                            hide_index=True,
                        )
                        summary_csv = summary_df.to_csv(index=False)
                        st.download_button(
                            "Download Full Summary (CSV)",
                            summary_csv,
                            "cross_community_summary.csv",
                            "text/csv",
                            key="tn_dl_cross_summary",
                        )
                    else:
                        st.caption("No cross-community cases found in any window.")

                # --- Save All Outputs ---
                st.divider()
                if st.button("Save All Outputs", key="tn_save_all", type="secondary"):
                    import os
                    from datetime import datetime as _dt

                    timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")
                    save_dir = Path(__file__).parent / "exports" / f"temporal_{timestamp}"
                    save_dir.mkdir(parents=True, exist_ok=True)

                    # Detect SVG capability (kaleido)
                    _can_svg = True
                    try:
                        import kaleido  # noqa: F401
                    except ImportError:
                        _can_svg = False

                    progress = st.progress(0, text="Saving outputs...")
                    total_items = num_steps * 4 + 2  # graphs + timelines + communities + cross-comm CSVs + vars + summary
                    done = 0

                    for si, s in enumerate(snapshots):
                        wlabel = (
                            f"step{si:03d}_{s.window_start.strftime('%Y%m')}_"
                            f"{s.window_end.strftime('%Y%m')}"
                        )

                        # 1) Network graph
                        net_fig = build_temporal_network_plotly(
                            s, edge_threshold=tn_edge_thresh,
                            community_colors=COMMUNITY_COLORS,
                            axis_range=st.session_state.tn_axis_range,
                        )
                        if _can_svg:
                            net_fig.write_image(str(save_dir / f"network_{wlabel}.png"), scale=2)
                        else:
                            net_fig.write_html(str(save_dir / f"network_{wlabel}.html"))
                        done += 1
                        progress.progress(done / total_items, text=f"Network graph {si+1}/{num_steps}")

                        # 2) Tenure timeline
                        if st.session_state.tn_tenures:
                            tl_fig = build_tenure_timeline_plotly(
                                s,
                                st.session_state.tn_tenures,
                                st.session_state.tn_appointed_by or {},
                            )
                            if _can_svg:
                                tl_fig.write_image(str(save_dir / f"timeline_{wlabel}.png"), scale=2)
                            else:
                                tl_fig.write_html(str(save_dir / f"timeline_{wlabel}.html"))
                        done += 1
                        progress.progress(done / total_items, text=f"Timeline {si+1}/{num_steps}")

                        # 3) Community membership CSV
                        G_s = s.graph
                        comm_rows = []
                        for cid, members in zip(s.community_ids, s.communities):
                            for name in sorted(members):
                                pres = G_s.nodes[name].get("appointed_by", "Unknown") if name in G_s.nodes else "Unknown"
                                comm_rows.append({
                                    "step": si,
                                    "window_start": str(s.window_start),
                                    "window_end": str(s.window_end),
                                    "community": cid,
                                    "justice": name,
                                    "appointed_by": pres,
                                })
                        pd.DataFrame(comm_rows).to_csv(
                            save_dir / f"communities_{wlabel}.csv", index=False,
                        )

                        # 3b) Cross-community cases CSV
                        cc_save = extract_cross_community_cases(s)
                        if cc_save:
                            cc_rows = []
                            for cc in cc_save:
                                maj_parts = []
                                for cid, names in sorted(cc.majority_by_community.items()):
                                    short = [extract_display_name(n) for n in names]
                                    maj_parts.append(f"[C{cid}] {', '.join(short)}")
                                dis_parts = []
                                for cid, names in sorted(cc.dissent_by_community.items()):
                                    short = [extract_display_name(n) for n in names]
                                    dis_parts.append(f"[C{cid}] {', '.join(short)}")
                                cc_rows.append({
                                    "case_number": cc.case_number,
                                    "volume": cc.volume,
                                    "date": str(cc.date),
                                    "division": cc.division,
                                    "ponente": cc.ponente,
                                    "cross_in_majority": cc.cross_in_majority,
                                    "cross_in_dissent": cc.cross_in_dissent,
                                    "communities_involved": "|".join(str(c) for c in cc.communities_involved),
                                    "majority_votes": " | ".join(maj_parts),
                                    "dissent_votes": " | ".join(dis_parts) if dis_parts else "",
                                })
                            pd.DataFrame(cc_rows).to_csv(
                                save_dir / f"cross_community_{wlabel}.csv", index=False,
                            )

                        done += 1
                        progress.progress(done / total_items, text=f"Communities {si+1}/{num_steps}")

                        done += 1
                        progress.progress(done / total_items, text=f"Cross-community {si+1}/{num_steps}")

                    # 4) Run variables JSON
                    run_vars = {
                        "timestamp": timestamp,
                        "window_years": tn_window,
                        "step_months": tn_step_size,
                        "treat_no_part_as_dissent": treat_no_part,
                        "division_filter": division_filter,
                        "dissent_filter": dissent_filter,
                        "edge_threshold": tn_edge_thresh,
                        "min_confidence": min_conf,
                        "total_snapshots": num_steps,
                        "image_format": "png" if _can_svg else "html",
                        "snapshots": [],
                    }
                    for si, s in enumerate(snapshots):
                        G_s = s.graph
                        run_vars["snapshots"].append({
                            "step": si,
                            "window_start": str(s.window_start),
                            "window_end": str(s.window_end),
                            "cases": s.cases_in_window,
                            "dissents": s.dissent_count,
                            "justices": s.active_justices,
                            "edges": G_s.number_of_edges(),
                            "communities": len(s.communities),
                            "community_ids": s.community_ids,
                            "stability": s.stability,
                            "entered": s.transitions.get("entered", []),
                            "exited": s.transitions.get("exited", []),
                        })
                    with open(save_dir / "run_variables.json", "w", encoding="utf-8") as f:
                        json.dump(run_vars, f, indent=2)

                    # 5) Consolidated community membership CSV (all steps)
                    all_comm_rows = []
                    for si, s in enumerate(snapshots):
                        G_s = s.graph
                        for cid, members in zip(s.community_ids, s.communities):
                            for name in sorted(members):
                                pres = G_s.nodes[name].get("appointed_by", "Unknown") if name in G_s.nodes else "Unknown"
                                all_comm_rows.append({
                                    "step": si,
                                    "window_start": str(s.window_start),
                                    "window_end": str(s.window_end),
                                    "community": cid,
                                    "justice": name,
                                    "appointed_by": pres,
                                })
                    pd.DataFrame(all_comm_rows).to_csv(
                        save_dir / "all_communities.csv", index=False,
                    )

                    # 6) Cross-community summary CSV (all windows)
                    cc_summary_df = compile_cross_community_summary(snapshots)
                    if not cc_summary_df.empty:
                        cc_summary_df.to_csv(
                            save_dir / "cross_community_summary.csv", index=False,
                        )

                    done += 1
                    progress.progress(done / total_items, text="Summary...")
                    done += 1
                    progress.progress(1.0, text="Done!")
                    img_fmt = "PNG" if _can_svg else "HTML (install kaleido for PNG)"
                    cc_count = len(cc_summary_df) if not cc_summary_df.empty else 0
                    st.success(
                        f"Saved {num_steps} snapshots to `{save_dir.relative_to(Path(__file__).parent)}/`\n\n"
                        f"- {num_steps} network graphs ({img_fmt})\n"
                        f"- {num_steps} tenure timelines ({img_fmt})\n"
                        f"- {num_steps} + 1 community CSVs\n"
                        f"- {num_steps} cross-community CSVs\n"
                        f"- 1 cross-community summary CSV ({cc_count} cases)\n"
                        f"- 1 run_variables.json"
                    )

                # Auto-play logic
                if st.session_state.tn_playing:
                    import time as _time
                    _time.sleep(tn_speed)
                    next_step = step + 1
                    if next_step >= num_steps:
                        st.session_state.tn_playing = False
                    else:
                        st.session_state.tn_step = next_step
                    st.rerun()
        else:
            st.info("Click **Compute Network Timeline** to build temporal network snapshots.")
