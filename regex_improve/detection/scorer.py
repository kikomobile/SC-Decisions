"""IoU-based span matching scorer for detection pipeline.

Reads predicted and ground truth JSON files (both in format_version=2 schema),
compares annotations per label, and outputs precision/recall/F1.
Completely independent from the GUI's evaluation.py.
"""

import json
import argparse
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
import sys


# Constants
POSITION_LABELS = {
    "start_of_case", "start_syllabus", "start_decision",
    "end_decision", "start_opinion", "end_opinion", "end_of_case"
}

GROUPED_LABELS = {"case_number", "parties"}

ALL_LABELS = [
    "start_of_case", "case_number", "date", "division", "parties",
    "start_syllabus", "end_syllabus", "counsel", "ponente", "doc_type",
    "start_decision", "end_decision", "votes", "start_opinion",
    "end_opinion", "end_of_case"
]


@dataclass
class Annotation:
    """Minimal annotation representation for scoring."""
    label: str
    text: str
    start_char: int
    end_char: int
    group: Optional[int] = None


@dataclass
class Case:
    """Minimal case representation for scoring."""
    case_id: str
    annotations: List[Annotation] = field(default_factory=list)


@dataclass
class ScoreResult:
    """Result of scoring for a single label."""
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int


def compute_iou(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    """Intersection over Union for two character spans.
    
    Returns 0.0 if no overlap, 1.0 if identical.
    Handles edge case where union=0.
    """
    # Ensure valid ranges
    if a_end <= a_start or b_end <= b_start:
        return 0.0
    
    intersection_start = max(a_start, b_start)
    intersection_end = min(a_end, b_end)
    
    if intersection_end <= intersection_start:
        return 0.0
    
    intersection = intersection_end - intersection_start
    union = (a_end - a_start) + (b_end - b_start) - intersection
    
    if union == 0:
        return 0.0
    
    return intersection / union


def match_spans(
    gt_anns: List[Annotation],
    pred_anns: List[Annotation],
    iou_threshold: float,
    is_position_label: bool
) -> Tuple[int, int, int]:
    """Greedy matching of spans between ground truth and predictions.
    
    For each GT annotation, find the best IoU prediction.
    Each prediction matches at most one GT.
    
    For position labels, any overlap (IoU > 0) counts as a match.
    For content labels, IoU >= threshold required.
    
    Returns (TP, FP, FN).
    """
    if not gt_anns and not pred_anns:
        return 0, 0, 0
    
    # Sort by start_char for consistent matching
    gt_sorted = sorted(gt_anns, key=lambda a: a.start_char)
    pred_sorted = sorted(pred_anns, key=lambda a: a.start_char)
    
    matched_preds = set()
    tp = 0
    
    # For each GT annotation, find best matching prediction
    for gt_idx, gt_ann in enumerate(gt_sorted):
        best_iou = 0.0
        best_pred_idx = -1
        
        for pred_idx, pred_ann in enumerate(pred_sorted):
            if pred_idx in matched_preds:
                continue
            
            iou = compute_iou(
                gt_ann.start_char, gt_ann.end_char,
                pred_ann.start_char, pred_ann.end_char
            )
            
            # Check if match meets threshold
            if is_position_label:
                match_ok = iou > 0
            else:
                match_ok = iou >= iou_threshold
            
            if match_ok and iou > best_iou:
                best_iou = iou
                best_pred_idx = pred_idx
        
        if best_pred_idx >= 0:
            matched_preds.add(best_pred_idx)
            tp += 1
    
    fp = len(pred_sorted) - len(matched_preds)
    fn = len(gt_sorted) - tp
    
    return tp, fp, fn


def match_grouped_spans(
    gt_anns: List[Annotation],
    pred_anns: List[Annotation],
    iou_threshold: float
) -> Tuple[int, int, int]:
    """Match spans for grouped labels (case_number, parties).
    
    First try matching by group index (gt group 0 → pred group 0).
    If groups don't align, fall back to best-IoU matching.
    
    Returns (TP, FP, FN).
    """
    if not gt_anns and not pred_anns:
        return 0, 0, 0
    
    # Group annotations by group index
    gt_by_group: Dict[Optional[int], List[Annotation]] = {}
    pred_by_group: Dict[Optional[int], List[Annotation]] = {}
    
    for ann in gt_anns:
        gt_by_group.setdefault(ann.group, []).append(ann)
    
    for ann in pred_anns:
        pred_by_group.setdefault(ann.group, []).append(ann)
    
    # Try to match within each group
    matched_preds = set()
    tp = 0
    
    # Create mapping from pred index to (group, idx_in_group)
    pred_index_map = []
    for group, preds in pred_by_group.items():
        for idx, pred in enumerate(preds):
            pred_index_map.append((group, idx, pred))
    
    # For each GT group
    for gt_group, gt_group_anns in gt_by_group.items():
        # Get predictions for this group
        pred_group_anns = pred_by_group.get(gt_group, [])
        
        # Match within group
        for gt_ann in gt_group_anns:
            best_iou = 0.0
            best_pred_idx = -1
            
            for pred_idx, (group, idx_in_group, pred_ann) in enumerate(pred_index_map):
                if group != gt_group:
                    continue
                if pred_idx in matched_preds:
                    continue
                
                iou = compute_iou(
                    gt_ann.start_char, gt_ann.end_char,
                    pred_ann.start_char, pred_ann.end_char
                )
                
                if iou >= iou_threshold and iou > best_iou:
                    best_iou = iou
                    best_pred_idx = pred_idx
            
            if best_pred_idx >= 0:
                matched_preds.add(best_pred_idx)
                tp += 1
    
    # If groups don't align well, fall back to global matching
    # (some GT annotations may not have been matched due to group mismatch)
    unmatched_gt = []
    for gt_group, gt_group_anns in gt_by_group.items():
        for gt_ann in gt_group_anns:
            # Check if this GT was matched
            matched = False
            for pred_idx in matched_preds:
                _, _, pred_ann = pred_index_map[pred_idx]
                iou = compute_iou(
                    gt_ann.start_char, gt_ann.end_char,
                    pred_ann.start_char, pred_ann.end_char
                )
                if iou >= iou_threshold:
                    matched = True
                    break
            if not matched:
                unmatched_gt.append(gt_ann)
    
    # Try to match unmatched GT with unmatched predictions
    unmatched_preds = []
    for pred_idx, (_, _, pred_ann) in enumerate(pred_index_map):
        if pred_idx not in matched_preds:
            unmatched_preds.append(pred_ann)
    
    # Use regular matching for remaining
    additional_tp, additional_fp, additional_fn = match_spans(
        unmatched_gt, unmatched_preds, iou_threshold, is_position_label=False
    )
    
    tp += additional_tp
    fp = len(pred_index_map) - len(matched_preds) - additional_tp  # remaining unmatched preds
    fn = additional_fn
    
    return tp, fp, fn


def load_json_file(filepath: str) -> Dict[str, Any]:
    """Load JSON file with error handling."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}", file=sys.stderr)
        sys.exit(1)


def parse_annotations(json_data: Dict[str, Any]) -> List[Case]:
    """Parse annotations from JSON data into Case objects."""
    cases = []
    
    # Check format version
    format_version = json_data.get("format_version", 1)
    if format_version != 2:
        print(f"Warning: Expected format_version=2, got {format_version}", file=sys.stderr)
    
    # Get volumes - can be either list or dict
    volumes_data = json_data.get("volumes", {})
    
    if isinstance(volumes_data, dict):
        # volumes is a dict mapping volume names to volume data
        volumes_list = volumes_data.values()
    else:
        # volumes is a list
        volumes_list = volumes_data
    
    for volume in volumes_list:
        volume_cases = volume.get("cases", [])
        for case_data in volume_cases:
            case_id = case_data.get("case_id", "")
            annotations = []
            
            for ann_data in case_data.get("annotations", []):
                label = ann_data.get("label", "")
                text = ann_data.get("text", "")
                start_char = ann_data.get("start_char", 0)
                end_char = ann_data.get("end_char", 0)
                group = ann_data.get("group")
                
                annotation = Annotation(
                    label=label,
                    text=text,
                    start_char=start_char,
                    end_char=end_char,
                    group=group
                )
                annotations.append(annotation)
            
            case = Case(case_id=case_id, annotations=annotations)
            cases.append(case)
    
    return cases


def match_cases(gt_cases: List[Case], pred_cases: List[Case]) -> List[Tuple[Case, Optional[Case]]]:
    """Match cases between ground truth and predictions.
    
    Strategy: for each GT case with annotations, find the predicted case
    whose `start_of_case` annotation `start_char` is closest.
    """
    matched_pairs = []
    
    # Build mapping from start_char to predicted cases
    pred_by_start_char = {}
    for pred_case in pred_cases:
        # Find start_of_case annotation
        start_ann = None
        for ann in pred_case.annotations:
            if ann.label == "start_of_case":
                start_ann = ann
                break
        
        if start_ann:
            pred_by_start_char[start_ann.start_char] = pred_case
    
    # Match GT cases
    for gt_case in gt_cases:
        # Skip GT cases with 0 annotations (vol226_case_7 and vol226_case_46)
        if not gt_case.annotations:
            continue
        
        # Find start_of_case annotation in GT
        gt_start_ann = None
        for ann in gt_case.annotations:
            if ann.label == "start_of_case":
                gt_start_ann = ann
                break
        
        if not gt_start_ann:
            # No start_of_case in GT, skip
            continue
        
        # Find closest predicted case by start_char
        closest_pred = None
        min_distance = float('inf')
        
        for pred_start_char, pred_case in pred_by_start_char.items():
            distance = abs(pred_start_char - gt_start_ann.start_char)
            if distance < min_distance:
                min_distance = distance
                closest_pred = pred_case
        
        matched_pairs.append((gt_case, closest_pred))
    
    return matched_pairs


def score_volume(
    predicted_path: str,
    ground_truth_path: str,
    iou_threshold: float = 0.8
) -> Dict[str, Any]:
    """Main scoring function.
    
    Returns:
    {
        "per_label": {
            "start_of_case": {"precision": float, "recall": float, "f1": float, "tp": int, "fp": int, "fn": int},
            ...
        },
        "micro_avg": {"precision": float, "recall": float, "f1": float},
        "per_case": {
            "vol226_case_0": {
                "matched_labels": ["start_of_case", "case_number", ...],
                "missed_labels": [...],
                "extra_labels": [...]
            },
            ...
        }
    }
    """
    # Load data
    gt_data = load_json_file(ground_truth_path)
    pred_data = load_json_file(predicted_path)
    
    gt_cases = parse_annotations(gt_data)
    pred_cases = parse_annotations(pred_data)
    
    # Match cases
    matched_pairs = match_cases(gt_cases, pred_cases)
    
    # Initialize results
    per_label_results = {label: {"tp": 0, "fp": 0, "fn": 0} for label in ALL_LABELS}
    per_case_results = {}
    
    # Score each matched case pair
    for gt_case, pred_case in matched_pairs:
        case_id = gt_case.case_id
        per_case_results[case_id] = {
            "matched_labels": [],
            "missed_labels": [],
            "extra_labels": []
        }
        
        # Group annotations by label
        gt_by_label = {}
        pred_by_label = {}
        
        for ann in gt_case.annotations:
            gt_by_label.setdefault(ann.label, []).append(ann)
        
        if pred_case:
            for ann in pred_case.annotations:
                pred_by_label.setdefault(ann.label, []).append(ann)
        
        # Score each label
        for label in ALL_LABELS:
            gt_anns = gt_by_label.get(label, [])
            pred_anns = pred_by_label.get(label, []) if pred_case else []
            
            # Skip if neither has this label
            if not gt_anns and not pred_anns:
                continue
            
            # Choose appropriate matcher
            if label in GROUPED_LABELS:
                tp, fp, fn = match_grouped_spans(gt_anns, pred_anns, iou_threshold)
            else:
                is_position = label in POSITION_LABELS
                tp, fp, fn = match_spans(gt_anns, pred_anns, iou_threshold, is_position)
            
            # Update per-label results
            per_label_results[label]["tp"] += tp
            per_label_results[label]["fp"] += fp
            per_label_results[label]["fn"] += fn
            
            # Update per-case results
            if tp > 0:
                per_case_results[case_id]["matched_labels"].append(label)
            if fn > 0:
                per_case_results[case_id]["missed_labels"].append(label)
            if fp > 0:
                per_case_results[case_id]["extra_labels"].append(label)
    
    # Handle unmatched GT cases (all-FN)
    matched_gt_ids = {gt_case.case_id for gt_case, _ in matched_pairs}
    for gt_case in gt_cases:
        if gt_case.case_id not in matched_gt_ids and gt_case.annotations:
            # This GT case wasn't matched to any prediction
            case_id = gt_case.case_id
            per_case_results[case_id] = {
                "matched_labels": [],
                "missed_labels": [],
                "extra_labels": []
            }
            
            # Count all GT annotations as FN
            for ann in gt_case.annotations:
                label = ann.label
                per_label_results[label]["fn"] += 1
                per_case_results[case_id]["missed_labels"].append(label)
    
    # Handle unmatched predicted cases (all-FP)
    matched_pred_ids = {pred_case.case_id for _, pred_case in matched_pairs if pred_case}
    for pred_case in pred_cases:
        if pred_case.case_id not in matched_pred_ids:
            # This predicted case wasn't matched to any GT
            case_id = pred_case.case_id
            if case_id not in per_case_results:
                per_case_results[case_id] = {
                    "matched_labels": [],
                    "missed_labels": [],
                    "extra_labels": []
                }
            
            # Count all predicted annotations as FP
            for ann in pred_case.annotations:
                label = ann.label
                per_label_results[label]["fp"] += 1
                per_case_results[case_id]["extra_labels"].append(label)
    
    # Compute per-label metrics
    final_per_label = {}
    for label, counts in per_label_results.items():
        tp = counts["tp"]
        fp = counts["fp"]
        fn = counts["fn"]
        
        # Compute precision, recall, F1
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        
        final_per_label[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn
        }
    
    # Compute micro-averaged metrics
    total_tp = sum(counts["tp"] for counts in per_label_results.values())
    total_fp = sum(counts["fp"] for counts in per_label_results.values())
    total_fn = sum(counts["fn"] for counts in per_label_results.values())
    
    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    micro_f1 = 2 * micro_precision * micro_recall / (micro_precision + micro_recall) if (micro_precision + micro_recall) > 0 else 0.0
    
    micro_avg = {
        "precision": round(micro_precision, 4),
        "recall": round(micro_recall, 4),
        "f1": round(micro_f1, 4)
    }
    
    return {
        "per_label": final_per_label,
        "micro_avg": micro_avg,
        "per_case": per_case_results
    }


def format_results_table(results: Dict[str, Any]) -> str:
    """Format scoring results as a readable table."""
    lines = []
    lines.append("=" * 80)
    lines.append("SCORING RESULTS")
    lines.append("=" * 80)
    lines.append("")
    
    # Micro-averaged metrics
    micro = results["micro_avg"]
    lines.append(f"Micro-averaged: P={micro['precision']:.4f}, R={micro['recall']:.4f}, F1={micro['f1']:.4f}")
    lines.append("")
    
    # Per-label table
    lines.append("Per-label metrics:")
    lines.append("-" * 80)
    lines.append(f"{'Label':<20} {'Precision':>10} {'Recall':>10} {'F1':>10} {'TP':>6} {'FP':>6} {'FN':>6}")
    lines.append("-" * 80)
    
    for label in ALL_LABELS:
        if label in results["per_label"]:
            stats = results["per_label"][label]
            lines.append(
                f"{label:<20} {stats['precision']:>10.4f} {stats['recall']:>10.4f} "
                f"{stats['f1']:>10.4f} {stats['tp']:>6} {stats['fp']:>6} {stats['fn']:>6}"
            )
    
    lines.append("")
    
    # Case summary
    per_case = results["per_case"]
    total_cases = len(per_case)
    perfect_cases = sum(1 for case in per_case.values() 
                       if not case["missed_labels"] and not case["extra_labels"])
    
    lines.append(f"Case summary: {total_cases} total cases, {perfect_cases} perfect matches")
    lines.append("")
    
    # Show problematic cases
    problematic = []
    for case_id, case_info in per_case.items():
        if case_info["missed_labels"] or case_info["extra_labels"]:
            problematic.append((case_id, case_info))
    
    if problematic:
        lines.append("Problematic cases:")
        for case_id, case_info in problematic[:10]:  # Show first 10
            missed = len(case_info["missed_labels"])
            extra = len(case_info["extra_labels"])
            lines.append(f"  {case_id}: {missed} missed, {extra} extra labels")
        
        if len(problematic) > 10:
            lines.append(f"  ... and {len(problematic) - 10} more")
    
    lines.append("=" * 80)
    return "\n".join(lines)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Score predicted annotations against ground truth"
    )
    parser.add_argument(
        "--predicted", "-p",
        required=True,
        help="Path to predicted JSON file"
    )
    parser.add_argument(
        "--ground-truth", "-g",
        required=True,
        help="Path to ground truth JSON file"
    )
    parser.add_argument(
        "--iou", "-i",
        type=float,
        default=0.8,
        help="IoU threshold for content labels (default: 0.8)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of table"
    )
    
    args = parser.parse_args()
    
    # Run scoring
    results = score_volume(
        predicted_path=args.predicted,
        ground_truth_path=args.ground_truth,
        iou_threshold=args.iou
    )
    
    # Output results
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(format_results_table(results))


if __name__ == "__main__":
    main()
