"""Diagnostics module for the detection pipeline.

Volume-level diagnostics that run automatically on every pipeline invocation.
Aggregates failure signals to help identify when the pipeline hits unfamiliar formatting.
"""
import statistics
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set


@dataclass
class DiagnosticCheck:
    """Single diagnostic check result."""
    name: str           # e.g., "mean_confidence"
    severity: str       # "ok", "warning", "critical"
    message: str        # human-readable summary
    value: Any          # the measured value (for programmatic use)


@dataclass
class DiagnosticReport:
    """Full diagnostic report for a volume."""
    checks: List[DiagnosticCheck] = field(default_factory=list)
    near_misses: List[Dict[str, Any]] = field(default_factory=list)  # DIAG-2

    @property
    def worst_severity(self) -> str:
        """Return the worst severity across all checks."""
        if any(c.severity == "critical" for c in self.checks):
            return "critical"
        if any(c.severity == "warning" for c in self.checks):
            return "warning"
        return "ok"


def check_mean_confidence(cases: List[Dict]) -> DiagnosticCheck:
    """Check 1: mean confidence score across all cases.
    
    Thresholds:
        >= 0.75 -> ok: "Mean confidence {score:.3f} (healthy)"
        >= 0.60 -> warning: "Mean confidence {score:.3f} -- some cases may have unfamiliar formatting"
        < 0.60 -> critical: "Mean confidence {score:.3f} -- unfamiliar formatting detected, consider annotating ground truth for this era"
    """
    if not cases:
        return DiagnosticCheck(
            name="mean_confidence",
            severity="warning",
            message="No cases detected",
            value=0.0
        )
    
    # Extract confidence scores from cases
    confidence_scores = []
    for case in cases:
        # Try to get confidence from notes field (format: "confidence: 0.950")
        notes = case.get("notes", "")
        if isinstance(notes, str) and "confidence:" in notes:
            try:
                # Extract the numeric value after "confidence:"
                score_str = notes.split("confidence:")[1].strip().split()[0]
                score = float(score_str)
                confidence_scores.append(score)
            except (ValueError, IndexError):
                pass
        # Also try from confidence_score field if present
        elif "confidence_score" in case:
            score = case.get("confidence_score", 0.0)
            confidence_scores.append(score)
    
    if not confidence_scores:
        return DiagnosticCheck(
            name="mean_confidence",
            severity="warning",
            message="No confidence scores found in cases",
            value=0.0
        )
    
    mean_score = statistics.mean(confidence_scores)
    
    if mean_score >= 0.75:
        severity = "ok"
        message = f"Mean confidence {mean_score:.3f} (healthy)"
    elif mean_score >= 0.60:
        severity = "warning"
        message = f"Mean confidence {mean_score:.3f} -- some cases may have unfamiliar formatting"
    else:
        severity = "critical"
        message = f"Mean confidence {mean_score:.3f} -- unfamiliar formatting detected, consider annotating ground truth for this era"
    
    return DiagnosticCheck(
        name="mean_confidence",
        severity=severity,
        message=message,
        value=mean_score
    )


def check_missing_required_labels(cases: List[Dict]) -> DiagnosticCheck:
    """Check 2: percentage of cases missing required labels.
    
    Required labels: case_number, date, doc_type
    Thresholds:
        <= 5% -> ok: "Required labels present in {pct:.0f}% of cases"
        <= 15% -> warning: "{count} cases ({pct:.0f}%) missing case_number/date/doc_type -- bracket regex may be failing"
        > 15% -> critical: "{count} cases ({pct:.0f}%) missing required labels -- bracket regex likely failing for this era"
    """
    if not cases:
        return DiagnosticCheck(
            name="missing_required_labels",
            severity="warning",
            message="No cases to check",
            value={"missing_count": 0, "total_cases": 0, "percentage": 0.0}
        )
    
    required_labels = {"case_number", "date", "doc_type"}
    missing_cases = 0
    label_missing_counts = {label: 0 for label in required_labels}
    
    for case in cases:
        annotations = case.get("annotations", [])
        found_labels = {ann.get("label") for ann in annotations}
        
        # Check if any required label is missing
        missing_for_case = required_labels - found_labels
        if missing_for_case:
            missing_cases += 1
            for label in missing_for_case:
                label_missing_counts[label] += 1
    
    total_cases = len(cases)
    missing_pct = (missing_cases / total_cases) * 100 if total_cases > 0 else 0.0
    
    # Find top 3 most commonly missing labels
    sorted_missing = sorted(label_missing_counts.items(), key=lambda x: x[1], reverse=True)
    top_missing = [f"{label} ({count})" for label, count in sorted_missing[:3] if count > 0]
    
    if missing_pct <= 5.0:
        severity = "ok"
        message = f"Required labels present in {100 - missing_pct:.0f}% of cases"
        if top_missing:
            message += f" (most missing: {', '.join(top_missing)})"
    elif missing_pct <= 15.0:
        severity = "warning"
        message = f"{missing_cases} cases ({missing_pct:.0f}%) missing case_number/date/doc_type -- bracket regex may be failing"
        if top_missing:
            message += f" (most missing: {', '.join(top_missing)})"
    else:
        severity = "critical"
        message = f"{missing_cases} cases ({missing_pct:.0f}%) missing required labels -- bracket regex likely failing for this era"
        if top_missing:
            message += f" (most missing: {', '.join(top_missing)})"
    
    return DiagnosticCheck(
        name="missing_required_labels",
        severity=severity,
        message=message,
        value={
            "missing_count": missing_cases,
            "total_cases": total_cases,
            "percentage": missing_pct,
            "label_missing_counts": label_missing_counts
        }
    )


def check_span_lengths(cases: List[Dict]) -> DiagnosticCheck:
    """Check 3: detect outlier span lengths for parties and votes.
    
    Thresholds:
        0 outliers -> ok: "Span lengths normal (parties: mean {p_mean:.0f} chars, votes: mean {v_mean:.0f} chars)"
        <= 10% outliers -> warning: "{count} cases ({pct:.0f}%) with outlier span lengths" + list the case_ids
        > 10% outliers -> critical: "{count} cases ({pct:.0f}%) with outlier span lengths -- extraction boundaries may be wrong"
    """
    if not cases:
        return DiagnosticCheck(
            name="span_lengths",
            severity="warning",
            message="No cases to check",
            value={"outliers": [], "parties_mean": 0.0, "votes_mean": 0.0}
        )
    
    # Collect span lengths for parties and votes
    parties_lengths = []
    votes_lengths = []
    parties_data = []  # (case_id, length, text_snippet)
    votes_data = []    # (case_id, length, text_snippet)
    
    for case in cases:
        case_id = case.get("case_id", "unknown")
        annotations = case.get("annotations", [])
        
        for ann in annotations:
            label = ann.get("label", "")
            text = ann.get("text", "")
            length = len(text)
            
            if label == "parties":
                parties_lengths.append(length)
                parties_data.append((case_id, length, text[:50] + "..." if len(text) > 50 else text))
            elif label == "votes":
                votes_lengths.append(length)
                votes_data.append((case_id, length, text[:50] + "..." if len(text) > 50 else text))
    
    # Find outliers (> 3 standard deviations from mean)
    outliers = []
    
    # Check parties outliers (only if we have enough samples)
    if len(parties_lengths) >= 5:
        try:
            parties_mean = statistics.mean(parties_lengths)
            parties_stdev = statistics.stdev(parties_lengths) if len(parties_lengths) > 1 else 0
            parties_threshold = parties_mean + (3 * parties_stdev)
            
            for case_id, length, snippet in parties_data:
                if length > parties_threshold:
                    outliers.append({
                        "case_id": case_id,
                        "label": "parties",
                        "length": length,
                        "mean": parties_mean,
                        "stdev": parties_stdev,
                        "snippet": snippet
                    })
        except statistics.StatisticsError:
            pass
    
    # Check votes outliers (only if we have enough samples)
    if len(votes_lengths) >= 5:
        try:
            votes_mean = statistics.mean(votes_lengths)
            votes_stdev = statistics.stdev(votes_lengths) if len(votes_lengths) > 1 else 0
            votes_threshold = votes_mean + (3 * votes_stdev)
            
            for case_id, length, snippet in votes_data:
                if length > votes_threshold:
                    outliers.append({
                        "case_id": case_id,
                        "label": "votes",
                        "length": length,
                        "mean": votes_mean,
                        "stdev": votes_stdev,
                        "snippet": snippet
                    })
        except statistics.StatisticsError:
            pass
    
    # Calculate means for reporting
    parties_mean_val = statistics.mean(parties_lengths) if parties_lengths else 0.0
    votes_mean_val = statistics.mean(votes_lengths) if votes_lengths else 0.0
    
    # Calculate outlier percentage
    total_cases = len(cases)
    outlier_pct = (len(outliers) / total_cases * 100) if total_cases > 0 else 0
    
    if not outliers:
        severity = "ok"
        message = f"Span lengths normal (parties: mean {parties_mean_val:.0f} chars, votes: mean {votes_mean_val:.0f} chars)"
    elif outlier_pct <= 10.0:
        severity = "warning"
        outlier_cases = sorted(set(o["case_id"] for o in outliers))
        # Show up to 5 case IDs
        shown = outlier_cases[:5]
        if len(outlier_cases) > 5:
            message = f"{len(outliers)} cases ({outlier_pct:.0f}%) with outlier span lengths: {', '.join(shown)} and {len(outlier_cases) - 5} more"
        else:
            message = f"{len(outliers)} cases ({outlier_pct:.0f}%) with outlier span lengths: {', '.join(shown)}"
    else:
        severity = "critical"
        outlier_cases = sorted(set(o["case_id"] for o in outliers))
        # Show first 5 case IDs only
        shown = outlier_cases[:5]
        message = f"{len(outliers)} cases ({outlier_pct:.0f}%) with outlier span lengths -- extraction boundaries may be wrong"
        if len(outlier_cases) > 5:
            message += f": {', '.join(shown)} and {len(outlier_cases) - 5} more"
        else:
            message += f": {', '.join(shown)}"
    
    return DiagnosticCheck(
        name="span_lengths",
        severity=severity,
        message=message,
        value={
            "outliers": outliers,
            "parties_mean": parties_mean_val,
            "votes_mean": votes_mean_val,
            "parties_count": len(parties_lengths),
            "votes_count": len(votes_lengths),
            "outlier_percentage": outlier_pct
        }
    )


def check_confidence_distribution(cases: List[Dict]) -> DiagnosticCheck:
    """Check 4: distribution of confidence scores across buckets.
    
    Buckets: [0.0-0.5), [0.5-0.7), [0.7-0.9), [0.9-1.0]
    Thresholds:
        >= 70% in top two buckets -> ok
        >= 50% in top two buckets -> warning: "Only {pct:.0f}% of cases above 0.7 confidence"
        < 50% in top two buckets -> critical: "Majority of cases below 0.7 confidence"
    """
    if not cases:
        return DiagnosticCheck(
            name="confidence_distribution",
            severity="warning",
            message="No cases to analyze",
            value={"buckets": {}, "top_two_pct": 0.0}
        )
    
    # Initialize buckets
    buckets = {
        "[0.0-0.5)": 0,
        "[0.5-0.7)": 0,
        "[0.7-0.9)": 0,
        "[0.9-1.0]": 0
    }
    
    total_with_score = 0
    
    for case in cases:
        # Try to extract confidence score
        score = 0.0
        notes = case.get("notes", "")
        if isinstance(notes, str) and "confidence:" in notes:
            try:
                score_str = notes.split("confidence:")[1].strip().split()[0]
                score = float(score_str)
            except (ValueError, IndexError):
                continue
        elif "confidence_score" in case:
            score = case.get("confidence_score", 0.0)
        else:
            continue
        
        total_with_score += 1
        
        # Bucket the score
        if score >= 0.9:
            buckets["[0.9-1.0]"] += 1
        elif score >= 0.7:
            buckets["[0.7-0.9)"] += 1
        elif score >= 0.5:
            buckets["[0.5-0.7)"] += 1
        else:
            buckets["[0.0-0.5)"] += 1
    
    if total_with_score == 0:
        return DiagnosticCheck(
            name="confidence_distribution",
            severity="warning",
            message="No confidence scores found in cases",
            value={"buckets": buckets, "top_two_pct": 0.0}
        )
    
    # Calculate percentage in top two buckets
    top_two_count = buckets["[0.7-0.9)"] + buckets["[0.9-1.0]"]
    top_two_pct = (top_two_count / total_with_score) * 100
    
    # Create histogram line
    histogram = " | ".join([f"{bucket}: {count}" for bucket, count in buckets.items()])
    
    if top_two_pct >= 70.0:
        severity = "ok"
        message = f"Confidence distribution: {histogram}"
    elif top_two_pct >= 50.0:
        severity = "warning"
        message = f"Only {top_two_pct:.0f}% of cases above 0.7 confidence ({histogram})"
    else:
        severity = "critical"
        message = f"Majority of cases below 0.7 confidence ({histogram})"
    
    return DiagnosticCheck(
        name="confidence_distribution",
        severity=severity,
        message=message,
        value={
            "buckets": buckets,
            "top_two_pct": top_two_pct,
            "total_with_score": total_with_score,
            "histogram": histogram
        }
    )


def run_diagnostics(cases: List[Dict], volume_text: Optional[str] = None, 
                   matched_lines: Optional[Set[int]] = None) -> DiagnosticReport:
    """Run all diagnostic checks on a set of cases.
    
    Args:
        cases: List of case dicts (each must have "annotations" key)
        volume_text: Optional full volume text for near-miss detection
        matched_lines: Optional set of 1-based line numbers already matched by pipeline
        
    Returns:
        DiagnosticReport with all check results
    """
    report = DiagnosticReport()
    
    # Run the 4 statistical checks
    report.checks.append(check_mean_confidence(cases))
    report.checks.append(check_missing_required_labels(cases))
    report.checks.append(check_span_lengths(cases))
    report.checks.append(check_confidence_distribution(cases))
    
    # Run near-miss detection if volume_text and matched_lines are provided
    if volume_text is not None and matched_lines is not None:
        report.near_misses = find_near_misses(volume_text, matched_lines)
    
    return report


# Near-miss patterns for DIAG-2 (tightened to eliminate body text false positives)
RE_NEAR_DIVISION = re.compile(
    r'^\s*(?:(?:FIRST|SECOND|THIRD)\s+DIVISION|EN\s*BANC)\s*$',
    re.IGNORECASE
)

RE_NEAR_BRACKET = re.compile(
    r'^[\[\(\{1I\s]{0,5}(?:G\.?\s*R\.?\s*No|A\.?\s*M\.?\s*No)',
    re.IGNORECASE
)

RE_NEAR_SO_ORDERED = re.compile(
    r'^\s*SO\s*ORDERED\s*[.,;]?\s*$',
    re.IGNORECASE
)

RE_NEAR_DOC_TYPE = re.compile(
    r'^\s*(?:D\s*E\s*C\s*I\s*S\s*I\s*O\s*N|R\s*E\s*S\s*O\s*L\s*U\s*T\s*I\s*O\s*N)\s*$',
    re.IGNORECASE
)


def find_near_misses(volume_text: str, matched_lines: Set[int]) -> List[Dict[str, Any]]:
    """Scan volume text for lines that almost match structural patterns but don't fully match.
    
    Args:
        volume_text: The full volume text
        matched_lines: Set of 1-based line numbers already matched by the pipeline
        
    Returns:
        List of near-miss dicts, each with line_num, pattern, and text
    """
    near_misses = []
    lines = volume_text.splitlines()
    
    for line_num, line in enumerate(lines, start=1):
        # Skip lines already matched by the pipeline
        if line_num in matched_lines:
            continue
        
        # Skip very long lines (body text, not structural)
        if len(line) > 200:
            continue
        
        # Check each near-miss pattern (order: most specific first)
        pattern_matched = None
        
        if RE_NEAR_BRACKET.match(line):
            pattern_matched = "bracket"
        elif RE_NEAR_DIVISION.match(line):
            pattern_matched = "division"
        elif RE_NEAR_SO_ORDERED.match(line):
            pattern_matched = "so_ordered"
        elif RE_NEAR_DOC_TYPE.match(line):
            pattern_matched = "doc_type"
        
        if pattern_matched:
            near_misses.append({
                "line_num": line_num,
                "pattern": pattern_matched,
                "text": line[:120]  # Truncate to 120 chars
            })
    
    # Cap at 30 near-misses
    if len(near_misses) > 30:
        # Keep first 30, add overflow summary
        overflow_count = len(near_misses) - 30
        near_misses = near_misses[:30]
        near_misses.append({
            "line_num": 0,
            "pattern": "overflow",
            "text": f"... and {overflow_count} more near-misses truncated"
        })
    
    return near_misses


if __name__ == "__main__":
    """Test the diagnostics module."""
    print("Testing Diagnostics Module...")
    
    # Test 1: Create mock cases with known scores and annotations
    print("\nTest 1: Mock cases with perfect scores...")
    perfect_cases = [
        {
            "case_id": "test_case_1",
            "annotations": [
                {"label": "case_number", "text": "[G.R. No. 12345]"},
                {"label": "date", "text": "January 1, 1986"},
                {"label": "doc_type", "text": "DECISION"},
                {"label": "parties", "text": "Petitioner vs. Respondent" * 10},  # ~250 chars
                {"label": "votes", "text": "Concur: Justice A, Justice B" * 3},  # ~90 chars
            ],
            "notes": "confidence: 0.950"
        },
        {
            "case_id": "test_case_2",
            "annotations": [
                {"label": "case_number", "text": "[A.M. No. 67890]"},
                {"label": "date", "text": "February 15, 1987"},
                {"label": "doc_type", "text": "RESOLUTION"},
                {"label": "parties", "text": "Complainant vs. Defendant" * 8},  # ~200 chars
                {"label": "votes", "text": "Dissent: Justice C" * 4},  # ~80 chars
            ],
            "notes": "confidence: 0.920"
        }
    ]
    
    report = run_diagnostics(perfect_cases)
    print(f"  Report worst severity: {report.worst_severity}")
    for check in report.checks:
        print(f"  - {check.name}: {check.severity} - {check.message}")
    
    assert report.worst_severity == "ok", "Perfect cases should be ok"
    
    # Test 2: Cases with low confidence
    print("\nTest 2: Cases with low confidence...")
    low_confidence_cases = [
        {
            "case_id": "bad_case_1",
            "annotations": [
                {"label": "case_number", "text": "[G.R. No. 99999]"},
                # Missing date
                {"label": "doc_type", "text": "DECISION"},
                {"label": "parties", "text": "A" * 5000},  # Very long
                {"label": "votes", "text": "B" * 1000},    # Very long
            ],
            "notes": "confidence: 0.350"
        },
        {
            "case_id": "bad_case_2",
            "annotations": [
                # Missing case_number
                {"label": "date", "text": "Invalid Date"},
                # Missing doc_type
                {"label": "parties", "text": "C"},  # Very short
                {"label": "votes", "text": "D"},    # Very short
            ],
            "notes": "confidence: 0.250"
        }
    ]
    
    report2 = run_diagnostics(low_confidence_cases)
    print(f"  Report worst severity: {report2.worst_severity}")
    for check in report2.checks:
        print(f"  - {check.name}: {check.severity} - {check.message}")
    
    assert report2.worst_severity in ["warning", "critical"], "Low confidence cases should have warnings/criticals"
    
    # Test 3: Empty case list
    print("\nTest 3: Empty case list...")
    report3 = run_diagnostics([])
    print(f"  Report worst severity: {report3.worst_severity}")
    for check in report3.checks:
        print(f"  - {check.name}: {check.severity} - {check.message}")
    
    assert report3.worst_severity == "warning", "Empty case list should be warning"
    
    # Test 4: Near-miss detection with tightened patterns
    print("\nTest 4: Near-miss detection with tightened patterns...")
    volume_text = """EN BANC
FIRST DIVISION
[G.R. No. 12345]
SO ORDERED.
DECISION
Some regular text here with G.R. No. 99999 in the middle
A. M. No. 67890
RESOLUTION
SECOND DIVISION"""
    
    matched_lines = {1, 3, 5}  # Lines 1, 3, 5 already matched
    near_misses = find_near_misses(volume_text, matched_lines)
    
    print(f"  Found {len(near_misses)} near-misses:")
    for nm in near_misses:
        print(f"    Line {nm['line_num']}: [{nm['pattern']}] {nm['text']}")
    
    # Line 2 (FIRST DIVISION), Line 4 (SO ORDERED.), Line 7 (A. M. No.), Line 8 (RESOLUTION), Line 9 (SECOND DIVISION) should be near-misses
    # Line 6 should NOT match because G.R. No. is in the middle of the line (not at start)
    # Line 2 and 9 should match division pattern
    # Line 4 should match so_ordered pattern
    # Line 7 should match bracket pattern
    # Line 8 should match doc_type pattern
    assert len(near_misses) >= 4, f"Expected at least 4 near-misses, got {len(near_misses)}"
    
    print("\nAll tests passed!")
