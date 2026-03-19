"""SC Decisions — Pipeline Control Panel.

Streamlit web UI for the detection pipeline.
Launch: streamlit run pipeline_ui.py
"""

import streamlit as st
import time
from pathlib import Path

st.set_page_config(
    page_title="SC Decisions — Pipeline Control",
    layout="wide",
    initial_sidebar_state="expanded",
)

import ui_helpers as uh

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
# Main layout — three tabs
# ---------------------------------------------------------------------------
st.title("SC Decisions — Pipeline Control")

tab_single, tab_batch, tab_csv = st.tabs(
    ["Single Volume", "Batch Processing", "CSV Extraction"]
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

    val_before = st.text_input(
        "Baseline CSV (before)",
        value="predictions_extract.csv",
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
            with st.expander(name, expanded=False):
                st.code(output, language="text")
