"""Non-UI helpers for the Streamlit pipeline control panel.

Settings persistence, subprocess runner, command builders, validation runners.
Pure stdlib — no Streamlit imports.
"""

import json
import os
import re
import subprocess
import sys
import threading
import queue
from pathlib import Path


# ---------------------------------------------------------------------------
# A. Settings persistence
# ---------------------------------------------------------------------------

SETTINGS_PATH = Path(".pipeline_ui_settings.json")

DEFAULT_SETTINGS = {
    "input_dir": "downloads",
    "output_dir": "downloads/predictions",
    "csv_output": "predictions_extract.csv",
    "justices_path": "regex_improve/detection/justices.json",
    "skip_llm": True,
    "force": False,
    "budget": 5.0,
    "threshold": 0.7,
    "csv_threshold": 0.75,
    "volume_range_start": 226,
    "volume_range_end": 500,
    "ground_truth_path": "",
    "last_mode": "batch",
}


def load_settings() -> dict:
    """Load settings from JSON file, filling missing keys with defaults."""
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                saved = json.load(f)
            settings.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save_settings(settings: dict) -> None:
    """Atomically write settings to JSON."""
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(str(tmp), str(SETTINGS_PATH))


# ---------------------------------------------------------------------------
# B. Subprocess runner
# ---------------------------------------------------------------------------

class PipelineRunner:
    """Thread-safe subprocess runner with real-time line output."""

    def __init__(self):
        self.log_queue: queue.Queue = queue.Queue()
        self.process = None
        self._thread = None
        self._done = False
        self._returncode = None

    @property
    def is_done(self) -> bool:
        return self._done

    @property
    def returncode(self):
        return self._returncode

    def start(self, cmd: list, cwd: str) -> None:
        """Start the subprocess in a background thread."""
        self._done = False
        self._returncode = None
        self._thread = threading.Thread(
            target=self._worker, args=(cmd, cwd), daemon=True
        )
        self._thread.start()

    def _worker(self, cmd: list, cwd: str) -> None:
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=cwd,
            )
            for line in self.process.stdout:
                self.log_queue.put(line)
            self.process.wait()
            self._returncode = self.process.returncode
        except Exception as e:
            self.log_queue.put(f"ERROR: {e}\n")
            self._returncode = -1
        self._done = True

    def poll(self) -> tuple:
        """Drain queue, return (new_lines_list, is_done)."""
        lines = []
        while not self.log_queue.empty():
            try:
                lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        return lines, self._done

    def stop(self) -> None:
        """Terminate the subprocess."""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self._done = True
            self._returncode = -9


# ---------------------------------------------------------------------------
# C. Command builders
# ---------------------------------------------------------------------------

def get_repo_root() -> Path:
    """Return absolute path to the repo root (where this file lives)."""
    return Path(__file__).resolve().parent


def get_pipeline_cwd() -> str:
    """Return absolute path to regex_improve/ (pipeline CWD)."""
    return str(get_repo_root() / "regex_improve")


def build_single_cmd(
    volume_path: str,
    output_path: str,
    skip_llm: bool,
    force: bool,
    budget: float,
    threshold: float,
    score_path: str = "",
) -> list:
    """Build command list for single-volume pipeline run."""
    cmd = [
        sys.executable, "-u", "-B", "-m", "detection",
        str(Path(volume_path).resolve()),
        "-o", str(Path(output_path).resolve()),
        "--budget", str(budget),
        "--threshold", str(threshold),
    ]
    if skip_llm:
        cmd.append("--skip-llm")
    if force:
        cmd.append("--force")
    if score_path:
        cmd.extend(["--score", str(Path(score_path).resolve())])
    return cmd


def build_batch_cmd(
    input_dir: str,
    output_dir: str,
    range_start: int,
    range_end: int,
    skip_llm: bool,
    force: bool,
    budget: float,
    threshold: float,
) -> list:
    """Build command list for batch pipeline run."""
    cmd = [
        sys.executable, "-u", "-B", "-m", "detection",
        str(Path(input_dir).resolve()),
        "--range", f"{range_start}-{range_end}",
        "-o", str(Path(output_dir).resolve()),
        "--budget", str(budget),
        "--threshold", str(threshold),
    ]
    if skip_llm:
        cmd.append("--skip-llm")
    if force:
        cmd.append("--force")
    return cmd


def build_csv_cmd(
    input_dir: str,
    output_path: str,
    justices_path: str,
    threshold: float,
) -> list:
    """Build command list for CSV extraction."""
    return [
        sys.executable, "-u", "-B",
        str(get_repo_root() / "extract_predictions_csv.py"),
        "--input-dir", str(Path(input_dir).resolve()),
        "--output", str(Path(output_path).resolve()),
        "--justices", str(Path(justices_path).resolve()),
        "--threshold", str(threshold),
    ]


# ---------------------------------------------------------------------------
# D. Validation and utilities
# ---------------------------------------------------------------------------

def scan_volumes(input_dir: str) -> list:
    """List Volume_*.txt files in directory, sorted by volume number."""
    p = Path(input_dir)
    if not p.is_dir():
        return []
    files = list(p.glob("Volume_*.txt"))

    def sort_key(f):
        m = re.search(r"(\d+)", f.stem)
        return int(m.group(1)) if m else 0

    return sorted(files, key=sort_key)


def run_validation_script(script_name: str, args: list) -> str:
    """Run a validation script and return its stdout."""
    cmd = [sys.executable, "-B", f"validation/{script_name}"] + args
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(get_repo_root())
    )
    return result.stdout + result.stderr


def run_all_csv_validations(before_csv: str, after_csv: str) -> dict:
    """Run all 4 CSV validation checks. Returns {script_name: output}."""
    results = {}
    results["check_headlines"] = run_validation_script(
        "check_headlines.py", [before_csv, after_csv]
    )
    results["check_overflow"] = run_validation_script(
        "check_overflow.py", [after_csv]
    )
    results["check_ponente_breakdown"] = run_validation_script(
        "check_ponente_breakdown.py", [before_csv, after_csv]
    )
    results["check_votes_by_era"] = run_validation_script(
        "check_votes_by_era.py", [before_csv, after_csv]
    )
    results["check_votes_by_era_html"] = run_validation_script(
        "check_votes_by_era.py", ["--html", after_csv]
    )
    return results


def open_folder(path: str) -> None:
    """Open a folder in Windows Explorer."""
    norm = os.path.normpath(path)
    subprocess.Popen(["explorer", norm])


def parse_summary_metrics(log_text: str) -> dict:
    """Extract key metrics from pipeline stdout text."""
    metrics = {}
    patterns = {
        "total_cases": r"Total cases:\s*(\d+)",
        "high_confidence": r"High confidence:\s*(\d+)",
        "low_confidence": r"Low confidence:\s*(\d+)",
        "ocr_corrections": r"OCR corrections:\s*(\d+)",
        "llm_calls": r"LLM calls:\s*(\d+)",
        "llm_cost": r"LLM cost:\s*\$([\d.]+)",
        "volumes_processed": r"Volumes processed:\s*(\d+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, log_text)
        if m:
            val = m.group(1)
            metrics[key] = float(val) if "." in val else int(val)
    return metrics
