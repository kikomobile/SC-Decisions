"""Detection manifest for caching and per-label method tracking.

Tracks which volumes have been processed, their status, and enables
incremental re-processing: re-run regex (free) while preserving
cached LLM results (expensive).
"""

import json
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "detection_manifest.json"
PIPELINE_VERSION = "1.1"


def load_manifest(output_dir: Path) -> Dict[str, Any]:
    """Load the detection manifest from output_dir.

    Returns:
        Dict mapping volume_name -> entry. Empty dict if no manifest file.
    """
    manifest_path = output_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load manifest from {manifest_path}: {e}")
        return {}


def save_manifest(output_dir: Path, manifest: Dict[str, Any]) -> None:
    """Save the detection manifest atomically (write tmp -> os.replace).

    Args:
        output_dir: Directory to write manifest into
        manifest: Full manifest dict
    """
    manifest_path = output_dir / MANIFEST_FILENAME
    tmp_path = output_dir / (MANIFEST_FILENAME + ".tmp")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        os.replace(str(tmp_path), str(manifest_path))
    except OSError as e:
        logger.error(f"Failed to save manifest to {manifest_path}: {e}")
        raise


def get_volume_entry(manifest: Dict[str, Any], volume_name: str) -> Optional[Dict[str, Any]]:
    """Get a volume's manifest entry, or None if not present."""
    return manifest.get(volume_name)


def update_volume_entry(
    manifest: Dict[str, Any],
    volume_name: str,
    prediction_file: str,
    total_cases: int,
    llm_calls: int,
    has_llm_labels: bool,
    confidence_threshold: float,
    source_file_mtime: str,
    status: str = "done"
) -> None:
    """Update (or create) a volume's manifest entry in place.

    Args:
        manifest: Manifest dict to mutate
        volume_name: e.g. "Volume_226"
        prediction_file: Output filename e.g. "Volume_226_predicted.json"
        total_cases: Number of cases extracted
        llm_calls: Number of LLM API calls made
        has_llm_labels: Whether any annotation has detection_method=="llm"
        confidence_threshold: Threshold used for this run
        source_file_mtime: ISO timestamp of source file modification time
        status: Processing status (default "done")
    """
    manifest[volume_name] = {
        "status": status,
        "prediction_file": prediction_file,
        "processed_at": datetime.now().isoformat(timespec='seconds'),
        "pipeline_version": PIPELINE_VERSION,
        "total_cases": total_cases,
        "llm_calls": llm_calls,
        "has_llm_labels": has_llm_labels,
        "confidence_threshold": confidence_threshold,
        "source_file_mtime": source_file_mtime,
    }


def _get_source_mtime(source_path: Path) -> str:
    """Get source file modification time as ISO string."""
    mtime = os.path.getmtime(source_path)
    return datetime.fromtimestamp(mtime).isoformat(timespec='seconds')


def should_reprocess(
    manifest: Dict[str, Any],
    volume_name: str,
    source_path: Path,
    force: bool
) -> Tuple[bool, str]:
    """Determine whether a volume needs reprocessing.

    Returns:
        (should_reprocess: bool, reason: str)
    """
    if force:
        return True, "force flag set"

    entry = get_volume_entry(manifest, volume_name)
    if entry is None:
        return True, "not in manifest"

    if entry.get("status") != "done":
        return True, f"status is '{entry.get('status')}', not 'done'"

    # Check source file modification time
    if source_path.exists():
        current_mtime = _get_source_mtime(source_path)
        recorded_mtime = entry.get("source_file_mtime", "")
        if current_mtime != recorded_mtime:
            return True, f"source file modified (was {recorded_mtime}, now {current_mtime})"

    return False, "up to date"


def load_previous_predictions(output_dir: Path, prediction_file: str) -> Optional[Dict[str, Any]]:
    """Load a previous prediction JSON file.

    Args:
        output_dir: Directory containing prediction files
        prediction_file: Filename of the prediction file

    Returns:
        Parsed JSON dict, or None if file doesn't exist or is invalid
    """
    pred_path = output_dir / prediction_file
    if not pred_path.exists():
        return None
    try:
        with open(pred_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load previous predictions from {pred_path}: {e}")
        return None


def merge_annotations(
    previous_anns: List[Dict[str, Any]],
    current_anns: List[Dict[str, Any]],
    force_llm_rerun: bool = False
) -> List[Dict[str, Any]]:
    """Merge previous and current annotations, preserving cached LLM results.

    Strategy:
    - Previous regex -> replaced by current regex
    - Previous LLM -> kept (unless force_llm_rerun=True)
    - New in current -> added
    - Missing from current but in previous -> kept (preserve coverage)

    Key: (label, group) tuple. For annotations with group=None, label alone is the key,
    but multiple annotations with the same label and group=None are matched by position.

    Args:
        previous_anns: Annotations from previous run
        current_anns: Annotations from current (regex) run
        force_llm_rerun: If True, discard previous LLM annotations too

    Returns:
        Merged annotation list
    """
    if not previous_anns:
        return list(current_anns)
    if not current_anns:
        # If current produced nothing, keep previous
        return list(previous_anns)

    # Separate previous LLM annotations from previous regex annotations
    prev_llm = []
    prev_regex = []
    for ann in previous_anns:
        if ann.get("detection_method") == "llm":
            if not force_llm_rerun:
                prev_llm.append(ann)
            # When force_llm_rerun, LLM annotations are simply dropped
        else:
            prev_regex.append(ann)

    # Build a set of (label, group) keys for previous LLM annotations
    llm_keys = set()
    for ann in prev_llm:
        key = (ann.get("label"), ann.get("group"))
        llm_keys.add(key)

    # Start with current annotations, but replace with LLM version where it exists
    # (LLM results are more expensive/accurate — preserve them over regex)
    merged = []
    merged_keys = set()
    for ann in current_anns:
        key = (ann.get("label"), ann.get("group"))
        if key in llm_keys:
            # LLM version exists for this label — skip the regex version
            continue
        merged.append(ann)
        merged_keys.add(key)

    # Add all previous LLM annotations
    for ann in prev_llm:
        key = (ann.get("label"), ann.get("group"))
        merged.append(ann)
        merged_keys.add(key)

    # Add back previous regex annotations for labels missing from current
    # (preserve coverage for labels that current regex missed)
    for ann in prev_regex:
        key = (ann.get("label"), ann.get("group"))
        if key not in merged_keys:
            merged.append(ann)
            merged_keys.add(key)

    return merged


if __name__ == "__main__":
    """Self-test exercising manifest and merge logic."""
    import tempfile
    import shutil

    print("=" * 60)
    print("manifest.py self-test")
    print("=" * 60)

    # Test 1: Roundtrip save/load
    print("\n1. Roundtrip save/load...")
    tmp_dir = Path(tempfile.mkdtemp(prefix="manifest_test_"))
    try:
        manifest = {}
        update_volume_entry(
            manifest, "Volume_226",
            prediction_file="Volume_226_predicted.json",
            total_cases=72,
            llm_calls=0,
            has_llm_labels=False,
            confidence_threshold=0.7,
            source_file_mtime="2026-03-12T19:22:00"
        )
        save_manifest(tmp_dir, manifest)
        loaded = load_manifest(tmp_dir)
        assert "Volume_226" in loaded, "Volume_226 not in loaded manifest"
        assert loaded["Volume_226"]["total_cases"] == 72
        assert loaded["Volume_226"]["status"] == "done"
        assert loaded["Volume_226"]["pipeline_version"] == PIPELINE_VERSION
        print("   [OK] Save/load roundtrip works")

        # Test 2: should_reprocess — new volume
        print("\n2. should_reprocess — new volume...")
        reprocess, reason = should_reprocess({}, "Volume_227", Path("/nonexistent"), False)
        assert reprocess is True
        assert "not in manifest" in reason
        print(f"   [OK] New volume: {reason}")

        # Test 3: should_reprocess — up to date
        print("\n3. should_reprocess — up to date...")
        # Create a temp source file
        src_file = tmp_dir / "Volume_226.txt"
        src_file.write_text("test content")
        mtime = _get_source_mtime(src_file)
        manifest["Volume_226"]["source_file_mtime"] = mtime
        reprocess, reason = should_reprocess(manifest, "Volume_226", src_file, False)
        assert reprocess is False
        assert "up to date" in reason
        print(f"   [OK] Up to date: {reason}")

        # Test 4: should_reprocess — force
        print("\n4. should_reprocess — force flag...")
        reprocess, reason = should_reprocess(manifest, "Volume_226", src_file, True)
        assert reprocess is True
        assert "force" in reason
        print(f"   [OK] Force: {reason}")

        # Test 5: should_reprocess — mtime changed
        print("\n5. should_reprocess — source file modified...")
        manifest["Volume_226"]["source_file_mtime"] = "2020-01-01T00:00:00"
        reprocess, reason = should_reprocess(manifest, "Volume_226", src_file, False)
        assert reprocess is True
        assert "modified" in reason
        print(f"   [OK] Modified: {reason}")

        # Test 6: merge_annotations — current replaces previous regex
        print("\n6. merge_annotations — regex replacement...")
        prev = [
            {"label": "date", "text": "old date", "group": None, "detection_method": "regex"},
            {"label": "ponente", "text": "OLD", "group": None, "detection_method": "regex"},
        ]
        curr = [
            {"label": "date", "text": "new date", "group": None, "detection_method": "regex"},
            {"label": "ponente", "text": "NEW", "group": None, "detection_method": "regex"},
        ]
        merged = merge_annotations(prev, curr)
        assert len(merged) == 2
        texts = {a["label"]: a["text"] for a in merged}
        assert texts["date"] == "new date"
        assert texts["ponente"] == "NEW"
        print("   [OK] Current regex replaces previous regex")

        # Test 7: merge_annotations — preserves LLM
        print("\n7. merge_annotations — preserves LLM labels...")
        prev = [
            {"label": "date", "text": "regex date", "group": None, "detection_method": "regex"},
            {"label": "parties", "text": "LLM parties", "group": None, "detection_method": "llm"},
        ]
        curr = [
            {"label": "date", "text": "new regex date", "group": None, "detection_method": "regex"},
            # parties not extracted by current regex
        ]
        merged = merge_annotations(prev, curr)
        assert len(merged) == 2
        texts = {a["label"]: a["text"] for a in merged}
        assert texts["date"] == "new regex date"
        assert texts["parties"] == "LLM parties"
        print("   [OK] LLM annotations preserved when current regex misses them")

        # Test 8: merge_annotations — force replaces LLM
        print("\n8. merge_annotations — force discards LLM...")
        merged = merge_annotations(prev, curr, force_llm_rerun=True)
        assert len(merged) == 1
        assert merged[0]["label"] == "date"
        print("   [OK] LLM annotations discarded with force_llm_rerun=True")

        # Test 9: merge_annotations — new labels in current added
        print("\n9. merge_annotations — new labels added...")
        prev = [
            {"label": "date", "text": "old", "group": None, "detection_method": "regex"},
        ]
        curr = [
            {"label": "date", "text": "new", "group": None, "detection_method": "regex"},
            {"label": "division", "text": "EN BANC", "group": None, "detection_method": "regex"},
        ]
        merged = merge_annotations(prev, curr)
        assert len(merged) == 2
        labels = {a["label"] for a in merged}
        assert "division" in labels
        print("   [OK] New labels from current run added")

        # Test 10: merge_annotations — previous coverage preserved
        print("\n10. merge_annotations — missing labels kept from previous...")
        prev = [
            {"label": "date", "text": "old", "group": None, "detection_method": "regex"},
            {"label": "counsel", "text": "Atty. X", "group": None, "detection_method": "regex"},
        ]
        curr = [
            {"label": "date", "text": "new", "group": None, "detection_method": "regex"},
            # counsel missing from current
        ]
        merged = merge_annotations(prev, curr)
        assert len(merged) == 2
        texts = {a["label"]: a["text"] for a in merged}
        assert texts["counsel"] == "Atty. X"
        print("   [OK] Previous regex labels preserved when current misses them")

        # Test 11: merge_annotations — empty inputs
        print("\n11. merge_annotations — empty inputs...")
        assert merge_annotations([], [{"label": "x", "text": "y", "group": None}]) == [{"label": "x", "text": "y", "group": None}]
        assert merge_annotations([{"label": "x", "text": "y", "group": None}], []) == [{"label": "x", "text": "y", "group": None}]
        assert merge_annotations([], []) == []
        print("   [OK] Empty inputs handled")

        # Test 12: load_previous_predictions
        print("\n12. load_previous_predictions...")
        pred_data = {"format_version": 2, "volumes": []}
        pred_path = tmp_dir / "Volume_226_predicted.json"
        with open(pred_path, 'w') as f:
            json.dump(pred_data, f)
        loaded_pred = load_previous_predictions(tmp_dir, "Volume_226_predicted.json")
        assert loaded_pred is not None
        assert loaded_pred["format_version"] == 2
        missing = load_previous_predictions(tmp_dir, "nonexistent.json")
        assert missing is None
        print("   [OK] load_previous_predictions works")

        print("\n" + "=" * 60)
        print("All 12 tests passed!")
        print("=" * 60)

    finally:
        shutil.rmtree(tmp_dir)
