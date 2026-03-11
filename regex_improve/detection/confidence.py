"""Confidence scoring for extracted cases.

Score each extracted case's quality to decide which cases need LLM re-extraction.
Cases scoring below 0.7 are flagged for the LLM fallback.
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

try:
    from rapidfuzz import process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    print("Warning: rapidfuzz not installed. Ponente check will use fallback.")

try:
    from .ocr_correction import KNOWN_JUSTICES
except ImportError:
    KNOWN_JUSTICES = []
    print("Warning: Could not import KNOWN_JUSTICES from ocr_correction. Using empty list.")


# Constants
REQUIRED_LABELS = {
    "start_of_case", "case_number", "date", "division", "doc_type",
    "start_decision", "end_decision", "votes", "end_of_case"
}

LABEL_ORDER = [
    "start_of_case", "case_number", "date", "division", "parties",
    "start_syllabus", "end_syllabus", "counsel", "doc_type", "ponente",
    "start_decision", "end_decision", "votes", "start_opinion",
    "end_opinion", "end_of_case"
]

PARTIES_LEN_RANGE = (50, 2000)  # characters
VOTES_LEN_RANGE = (20, 500)     # characters

# Date pattern for validation (lenient)
DATE_PATTERN = re.compile(
    r'^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}',
    re.IGNORECASE
)


@dataclass
class ConfidenceResult:
    """Result of confidence scoring for a case."""
    score: float                # 0.0 to 1.0
    checks: Dict[str, float]   # individual check name -> score
    flags: List[str]           # human-readable issue descriptions


def _check_required_labels_present(annotations: List[Dict]) -> Tuple[float, List[str]]:
    """Check 1: required labels present.
    
    Weight: 0.3
    Score: count of found required labels / total required labels.
    """
    found_labels = {ann.get("label") for ann in annotations}
    found_required = found_labels.intersection(REQUIRED_LABELS)
    
    score = len(found_required) / len(REQUIRED_LABELS) if REQUIRED_LABELS else 0.0
    
    flags = []
    missing = REQUIRED_LABELS - found_required
    if missing:
        flags.append(f"Missing required labels: {', '.join(sorted(missing))}")
    
    return score, flags


def _check_parties_length(annotations: List[Dict]) -> Tuple[float, List[str]]:
    """Check 2: parties length within reasonable range.
    
    Weight: 0.1
    Score: 1.0 if any parties annotation has length in (50, 2000), else 0.0.
    """
    parties_anns = [ann for ann in annotations if ann.get("label") == "parties"]
    
    if not parties_anns:
        return 0.0, ["No parties annotation found"]
    
    for ann in parties_anns:
        text = ann.get("text", "")
        length = len(text)
        if PARTIES_LEN_RANGE[0] <= length <= PARTIES_LEN_RANGE[1]:
            return 1.0, []
    
    # If we get here, no parties annotation is within range
    length = len(parties_anns[0].get("text", ""))
    return 0.0, [f"Parties length {length} outside range {PARTIES_LEN_RANGE}"]


def _check_votes_length(annotations: List[Dict]) -> Tuple[float, List[str]]:
    """Check 3: votes length within reasonable range.
    
    Weight: 0.1
    Score: 1.0 if any votes annotation has length in (20, 500), else 0.0.
    """
    votes_anns = [ann for ann in annotations if ann.get("label") == "votes"]
    
    if not votes_anns:
        return 0.0, ["No votes annotation found"]
    
    for ann in votes_anns:
        text = ann.get("text", "")
        length = len(text)
        if VOTES_LEN_RANGE[0] <= length <= VOTES_LEN_RANGE[1]:
            return 1.0, []
    
    # If we get here, no votes annotation is within range
    length = len(votes_anns[0].get("text", ""))
    return 0.0, [f"Votes length {length} outside range {VOTES_LEN_RANGE}"]


def _check_ponente_known(annotations: List[Dict], known_justices: List[str]) -> Tuple[float, List[str]]:
    """Check 4: ponente matches known justice.
    
    Weight: 0.1
    Score: 1.0 if ponente text fuzzy-matches a known justice (>85%),
           0.5 if "PER CURIAM",
           0.0 if unknown/missing.
    """
    ponente_anns = [ann for ann in annotations if ann.get("label") == "ponente"]
    
    if not ponente_anns:
        return 0.0, ["No ponente annotation found"]
    
    ponente_text = ponente_anns[0].get("text", "").strip()
    
    # Check for PER CURIAM
    if "PER CURIAM" in ponente_text.upper():
        return 0.5, ["Ponente is PER CURIAM (0.5 score)"]
    
    # If rapidfuzz not available, skip check with neutral 0.5
    if not RAPIDFUZZ_AVAILABLE:
        return 0.5, ["Ponente check skipped (rapidfuzz not installed)"]

    # Fuzzy match against known justices
    if known_justices and ponente_text:
        try:
            result = process.extractOne(ponente_text, known_justices, score_cutoff=85)
            if result:
                matched_justice, score, _ = result
                return 1.0, [f"Ponente matches known justice: {matched_justice} (score: {score:.1f})"]
        except Exception:
            pass

    return 0.0, [f"Ponente '{ponente_text}' not recognized"]


def _check_ordering_correct(annotations: List[Dict]) -> Tuple[float, List[str]]:
    """Check 5: annotations appear in correct order.
    
    Weight: 0.2
    Score: 1.0 if all present labels appear in LABEL_ORDER by start_char.
           0.0 if any is out of order.
    """
    if not annotations:
        return 0.0, ["No annotations to check ordering"]
    
    # Get annotations with start_char
    anns_with_pos = []
    for ann in annotations:
        start_char = ann.get("start_char")
        if start_char is not None:
            anns_with_pos.append((start_char, ann.get("label")))
    
    if not anns_with_pos:
        return 0.5, ["No start_char positions available for ordering check"]
    
    # Sort by start_char
    anns_with_pos.sort(key=lambda x: x[0])
    
    # Check if labels appear in LABEL_ORDER
    # Build a map of label to its position in LABEL_ORDER
    label_to_order = {label: i for i, label in enumerate(LABEL_ORDER)}
    
    # Get (start_char, order_index, label_name) for labels that are in LABEL_ORDER
    ordered_triples = []
    for start_char, label in anns_with_pos:
        if label in label_to_order:
            ordered_triples.append((start_char, label_to_order[label], label))

    # Group annotations by start_char, use minimum order index per group
    from itertools import groupby
    groups = []
    for char_pos, items in groupby(ordered_triples, key=lambda x: x[0]):
        items_list = list(items)
        min_idx = min(t[1] for t in items_list)
        labels = [t[2] for t in items_list]
        groups.append((char_pos, min_idx, labels))

    # Check if group order indices are non-decreasing
    out_of_order_labels = []
    for i in range(1, len(groups)):
        _, prev_idx, prev_labels = groups[i - 1]
        _, curr_idx, curr_labels = groups[i]
        if curr_idx < prev_idx:
            out_of_order_labels.append(f"{','.join(prev_labels)} -> {','.join(curr_labels)}")

    if out_of_order_labels:
        return 0.0, [f"Labels out of order: {', '.join(out_of_order_labels)}"]

    return 1.0, []


def _check_no_overlaps(annotations: List[Dict]) -> Tuple[float, List[str]]:
    """Check 6: no overlapping annotations.
    
    Weight: 0.1
    Score: 1.0 if no pair of annotations has overlapping char ranges.
           0.0 if any do.
    """
    if len(annotations) < 2:
        return 1.0, []
    
    # Get annotations with start and end chars
    anns_with_spans = []
    for ann in annotations:
        start = ann.get("start_char")
        end = ann.get("end_char")
        if start is not None and end is not None and start < end:
            anns_with_spans.append((start, end, ann.get("label")))
    
    # Check for overlaps (allow identical spans — stacked annotations)
    overlaps = []
    for i in range(len(anns_with_spans)):
        for j in range(i + 1, len(anns_with_spans)):
            start_i, end_i, label_i = anns_with_spans[i]
            start_j, end_j, label_j = anns_with_spans[j]

            # Identical spans are allowed (stacked annotations, e.g. start_of_case + division)
            if start_i == start_j and end_i == end_j:
                continue

            # Check for partial overlap (not just touching)
            if not (end_i <= start_j or end_j <= start_i):
                overlaps.append(f"{label_i} [{start_i}-{end_i}] overlaps {label_j} [{start_j}-{end_j}]")
    
    if overlaps:
        return 0.0, [f"Overlapping annotations: {', '.join(overlaps[:3])}"]
    
    return 1.0, []


def _check_date_valid(annotations: List[Dict]) -> Tuple[float, List[str]]:
    """Check 7: date text matches Month DD, YYYY pattern.
    
    Weight: 0.1
    Score: 1.0 if date text matches pattern, 0.0 otherwise.
    """
    date_anns = [ann for ann in annotations if ann.get("label") == "date"]
    
    if not date_anns:
        return 0.0, ["No date annotation found"]
    
    date_text = date_anns[0].get("text", "").strip()
    
    # Try to match the date pattern
    if DATE_PATTERN.search(date_text):
        return 1.0, []
    
    # Also check for common OCR errors that might have been corrected
    # Remove brackets/parentheses and try again
    cleaned = re.sub(r'[\[\]\(\)\{\}]', '', date_text)
    if DATE_PATTERN.search(cleaned):
        return 0.5, [f"Date '{date_text}' matches after cleaning brackets"]
    
    return 0.0, [f"Date '{date_text}' doesn't match Month DD, YYYY pattern"]


def score_case(annotations: List[Dict], known_justices: Optional[List[str]] = None) -> ConfidenceResult:
    """Score a case's quality based on 7 weighted checks.
    
    Args:
        annotations: List of annotation dicts
        known_justices: Optional list of known justice names for fuzzy matching
        
    Returns:
        ConfidenceResult with score, individual check scores, and flags
    """
    if known_justices is None:
        known_justices = KNOWN_JUSTICES
    
    # Define checks with their weights
    checks = [
        (_check_required_labels_present, 0.3, "required_labels_present"),
        (_check_parties_length, 0.1, "parties_length"),
        (_check_votes_length, 0.1, "votes_length"),
        (_check_ponente_known, 0.1, "ponente_known"),
        (_check_ordering_correct, 0.2, "ordering_correct"),
        (_check_no_overlaps, 0.1, "no_overlaps"),
        (_check_date_valid, 0.1, "date_valid"),
    ]
    
    check_scores = {}
    all_flags = []
    total_score = 0.0
    
    for check_func, weight, name in checks:
        if name == "ponente_known":
            score, flags = check_func(annotations, known_justices)
        else:
            score, flags = check_func(annotations)
        
        check_scores[name] = score
        total_score += weight * score
        all_flags.extend(flags)
    
    return ConfidenceResult(
        score=total_score,
        checks=check_scores,
        flags=all_flags
    )


def score_all_cases(cases: List[Dict], known_justices: Optional[List[str]] = None,
                   threshold: float = 0.7) -> Tuple[List[Dict], List[Dict]]:
    """Split cases into high-confidence and low-confidence lists based on threshold.
    
    Args:
        cases: List of case dicts (each must have "annotations" key)
        known_justices: Optional list of known justice names
        threshold: Confidence threshold (default 0.7)
        
    Returns:
        Tuple of (high_confidence_cases, low_confidence_cases)
    """
    high_confidence = []
    low_confidence = []
    
    for case in cases:
        annotations = case.get("annotations", [])
        result = score_case(annotations, known_justices)
        
        # Add confidence score to case
        case_with_score = case.copy()
        case_with_score["confidence_score"] = result.score
        case_with_score["confidence_flags"] = result.flags
        
        if result.score >= threshold:
            high_confidence.append(case_with_score)
        else:
            low_confidence.append(case_with_score)
    
    return high_confidence, low_confidence


if __name__ == "__main__":
    """Test the confidence scorer."""
    import json
    from pathlib import Path
    
    print("Testing Confidence Scorer...")
    
    # Load ground truth annotations
    gt_path = Path("regex_improve/annotation_exports/ground_truth_20260309_144413.json")
    if not gt_path.exists():
        print(f"Error: {gt_path} not found")
        exit(1)
    
    with open(gt_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Get all cases from ground truth (skip empty ones)
    all_cases = []
    for volume_name, volume_data in data.get("volumes", {}).items():
        for case in volume_data.get("cases", []):
            if case.get("annotations"):
                all_cases.append(case)

    print(f"Loaded {len(all_cases)} annotated cases from ground truth")

    # Test 1: Score ground truth cases (should be high confidence)
    print("\nTest 1: Scoring ground truth cases...")
    high_scores = []
    for i, case in enumerate(all_cases[:5]):
        annotations = case.get("annotations", [])
        result = score_case(annotations, KNOWN_JUSTICES)
        high_scores.append(result.score)
        print(f"  Case {i}: score={result.score:.3f}, flags={len(result.flags)}")
        for flag in result.flags:
            print(f"    - {flag}")

    avg_score = sum(high_scores) / len(high_scores) if high_scores else 0
    print(f"  Average score for ground truth: {avg_score:.3f}")
    assert avg_score >= 0.8, f"Ground truth should score >= 0.8, got {avg_score:.3f}"
    
    # Test 2: Create a deliberately broken case
    print("\nTest 2: Scoring broken case...")
    broken_annotations = [
        {"label": "start_of_case", "text": "EN BANC", "start_char": 100, "end_char": 106},
        {"label": "doc_type", "text": "DECISION", "start_char": 200, "end_char": 208},
        # Missing case_number, date, division
        {"label": "parties", "text": "A" * 10, "start_char": 300, "end_char": 310},  # Too short
        {"label": "votes", "text": "B" * 10, "start_char": 400, "end_char": 410},    # Too short
        {"label": "ponente", "text": "UNKNOWN JUSTICE", "start_char": 500, "end_char": 515},
        {"label": "date", "text": "Invalid Date", "start_char": 600, "end_char": 611},
        # Out of order: end_decision before start_decision
        {"label": "end_decision", "text": "SO ORDERED.", "start_char": 700, "end_char": 711},
        {"label": "start_decision", "text": "This is a decision.", "start_char": 800, "end_char": 820},
        {"label": "end_of_case", "text": "END", "start_char": 900, "end_char": 903},
    ]
    broken_result = score_case(broken_annotations, KNOWN_JUSTICES)
    print(f"  Broken case score: {broken_result.score:.3f}")
    print(f"  Checks: {broken_result.checks}")
    print(f"  Flags:")
    for flag in broken_result.flags:
        print(f"    - {flag}")
    assert broken_result.score < 0.5, f"Broken case should score < 0.5, got {broken_result.score:.3f}"

    # Test 3: score_all_cases splits correctly
    print("\nTest 3: Testing score_all_cases...")
    test_cases_list = [
        {"annotations": all_cases[0].get("annotations", [])},  # good case
        {"annotations": broken_annotations},                     # bad case
    ]
    high, low = score_all_cases(test_cases_list, KNOWN_JUSTICES, threshold=0.7)
    print(f"  High confidence: {len(high)}, Low confidence: {len(low)}")
    assert len(high) >= 1, "Good ground truth case should be high confidence"
    assert len(low) >= 1, "Broken case should be low confidence"

    print("\nAll tests passed!")