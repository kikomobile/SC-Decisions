"""Correction tracking for human review of pipeline predictions.

Snapshots imported predictions as a frozen baseline, then computes
diffs against the current annotation state to produce structured
correction logs for pipeline improvement analysis.
"""

import copy
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from gui.models import Annotation, Case, VolumeData


@dataclass
class CorrectionEntry:
    case_id: str
    correction_type: str        # "removed", "added", "label_changed", "span_adjusted"
    label: str                  # the annotation label involved
    original: Optional[dict]    # original annotation dict (None for "added")
    corrected: Optional[dict]   # corrected annotation dict (None for "removed")
    context_text: str           # ~200 chars of surrounding volume text
    start_line: int             # line number for reference
    notes: str = ""


@dataclass
class CorrectionLog:
    volume_name: str
    source_file: str
    total_predicted: int
    corrections: List[CorrectionEntry] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


class CorrectionTracker:
    """Tracks corrections made to imported pipeline predictions."""

    def __init__(self):
        self.baseline: Optional[VolumeData] = None
        self.volume_name: str = ""
        self.source_file: str = ""
        self.volume_text: str = ""

    def set_baseline(self, volume_data: VolumeData, source_file: str, volume_text: str):
        """Snapshot the imported predictions as frozen baseline.

        Args:
            volume_data: The imported VolumeData (will be deep-copied)
            source_file: Path to the predicted.json that was imported
            volume_text: Full volume text for extracting context
        """
        self.baseline = copy.deepcopy(volume_data)
        self.volume_name = volume_data.volume
        self.source_file = str(source_file)
        self.volume_text = volume_text

    def has_baseline(self) -> bool:
        return self.baseline is not None

    def compute_diff(self, current: VolumeData) -> CorrectionLog:
        """Compare baseline predictions against current annotations.

        Returns:
            CorrectionLog with all detected corrections and summary stats
        """
        if self.baseline is None:
            return CorrectionLog(
                volume_name=self.volume_name,
                source_file=self.source_file,
                total_predicted=0
            )

        # Count total predicted annotations in baseline
        total_predicted = sum(
            len(c.annotations) for c in self.baseline.cases
        )

        corrections: List[CorrectionEntry] = []

        # Index baseline and current cases by case_id
        baseline_cases = {c.case_id: c for c in self.baseline.cases}
        current_cases = {c.case_id: c for c in current.cases}

        all_case_ids = sorted(
            set(baseline_cases.keys()) | set(current_cases.keys()),
            key=_natural_sort_key
        )

        for case_id in all_case_ids:
            b_case = baseline_cases.get(case_id)
            c_case = current_cases.get(case_id)

            if b_case is None:
                # Entire case added by reviewer
                for ann in c_case.annotations:
                    corrections.append(CorrectionEntry(
                        case_id=case_id,
                        correction_type="added",
                        label=ann.label,
                        original=None,
                        corrected=ann.to_dict(),
                        context_text=self._get_context(ann.start_char, ann.end_char),
                        start_line=ann.start_line
                    ))
                continue

            if c_case is None:
                # Entire case removed by reviewer
                for ann in b_case.annotations:
                    corrections.append(CorrectionEntry(
                        case_id=case_id,
                        correction_type="removed",
                        label=ann.label,
                        original=ann.to_dict(),
                        corrected=None,
                        context_text=self._get_context(ann.start_char, ann.end_char),
                        start_line=ann.start_line
                    ))
                continue

            # Both exist — compare annotations within the case
            case_corrections = self._diff_case(case_id, b_case, c_case)
            corrections.extend(case_corrections)

        # Build summary
        by_type: Dict[str, int] = {}
        by_label: Dict[str, int] = {}
        cases_with_corrections = set()

        for c in corrections:
            by_type[c.correction_type] = by_type.get(c.correction_type, 0) + 1
            by_label[c.label] = by_label.get(c.label, 0) + 1
            cases_with_corrections.add(c.case_id)

        summary = {
            "total_corrections": len(corrections),
            "by_type": by_type,
            "by_label": dict(sorted(by_label.items(), key=lambda x: -x[1])),
            "cases_with_corrections": len(cases_with_corrections),
            "cases_perfect": len(all_case_ids) - len(cases_with_corrections)
        }

        log = CorrectionLog(
            volume_name=self.volume_name,
            source_file=self.source_file,
            total_predicted=total_predicted,
            corrections=corrections,
            summary=summary
        )
        return log

    def _diff_case(
        self, case_id: str, baseline: Case, current: Case
    ) -> List[CorrectionEntry]:
        """Compare annotations between baseline and current for one case."""
        corrections = []

        b_anns = list(baseline.annotations)
        c_anns = list(current.annotations)

        # Build keys for exact matching: (label, start_char, end_char)
        def ann_key(a: Annotation):
            return (a.label, a.start_char, a.end_char)

        b_keys = {ann_key(a): a for a in b_anns}
        c_keys = {ann_key(a): a for a in c_anns}

        b_key_set = set(b_keys.keys())
        c_key_set = set(c_keys.keys())

        # Exact matches — no correction needed
        exact_matches = b_key_set & c_key_set

        # Remaining after removing exact matches
        b_remaining = [b_keys[k] for k in b_key_set - exact_matches]
        c_remaining = [c_keys[k] for k in c_key_set - exact_matches]

        # Check for label changes: same (start_char, end_char), different label
        b_by_span = {}
        for a in b_remaining:
            span = (a.start_char, a.end_char)
            b_by_span.setdefault(span, []).append(a)

        c_by_span = {}
        for a in c_remaining:
            span = (a.start_char, a.end_char)
            c_by_span.setdefault(span, []).append(a)

        matched_b = set()
        matched_c = set()

        # Label changes: same span, different label
        for span in set(b_by_span.keys()) & set(c_by_span.keys()):
            for b_ann in b_by_span[span]:
                for c_ann in c_by_span[span]:
                    if b_ann.label != c_ann.label and id(b_ann) not in matched_b and id(c_ann) not in matched_c:
                        corrections.append(CorrectionEntry(
                            case_id=case_id,
                            correction_type="label_changed",
                            label=c_ann.label,
                            original=b_ann.to_dict(),
                            corrected=c_ann.to_dict(),
                            context_text=self._get_context(b_ann.start_char, b_ann.end_char),
                            start_line=b_ann.start_line
                        ))
                        matched_b.add(id(b_ann))
                        matched_c.add(id(c_ann))

        # Span adjustments: same label, start_char within 200 chars
        b_unmatched = [a for a in b_remaining if id(a) not in matched_b]
        c_unmatched = [a for a in c_remaining if id(a) not in matched_c]

        for b_ann in list(b_unmatched):
            best_match = None
            best_dist = 201  # beyond threshold
            for c_ann in c_unmatched:
                if b_ann.label == c_ann.label and id(c_ann) not in matched_c:
                    dist = abs(b_ann.start_char - c_ann.start_char)
                    if dist <= 200 and dist < best_dist:
                        best_match = c_ann
                        best_dist = dist

            if best_match is not None:
                corrections.append(CorrectionEntry(
                    case_id=case_id,
                    correction_type="span_adjusted",
                    label=b_ann.label,
                    original=b_ann.to_dict(),
                    corrected=best_match.to_dict(),
                    context_text=self._get_context(b_ann.start_char, b_ann.end_char),
                    start_line=b_ann.start_line
                ))
                matched_b.add(id(b_ann))
                matched_c.add(id(best_match))
                c_unmatched.remove(best_match)

        # Remaining baseline annotations are removals (false positives)
        for a in b_remaining:
            if id(a) not in matched_b:
                corrections.append(CorrectionEntry(
                    case_id=case_id,
                    correction_type="removed",
                    label=a.label,
                    original=a.to_dict(),
                    corrected=None,
                    context_text=self._get_context(a.start_char, a.end_char),
                    start_line=a.start_line
                ))

        # Remaining current annotations are additions (false negatives)
        for a in c_remaining:
            if id(a) not in matched_c:
                corrections.append(CorrectionEntry(
                    case_id=case_id,
                    correction_type="added",
                    label=a.label,
                    original=None,
                    corrected=a.to_dict(),
                    context_text=self._get_context(a.start_char, a.end_char),
                    start_line=a.start_line
                ))

        return corrections

    def _get_context(self, start_char: int, end_char: int) -> str:
        """Extract ~200 chars of surrounding text for context."""
        if not self.volume_text:
            return ""
        text_len = len(self.volume_text)
        ctx_start = max(0, start_char - 100)
        ctx_end = min(text_len, end_char + 100)
        context = self.volume_text[ctx_start:ctx_end]
        # Replace newlines for single-line display
        context = context.replace("\r\n", "\\n").replace("\n", "\\n")
        return context


def _natural_sort_key(s: str):
    """Sort key for natural ordering (vol226_case_2 before vol226_case_10)."""
    import re
    parts = re.split(r'(\d+)', s)
    result = []
    for part in parts:
        if part.isdigit():
            result.append(int(part))
        else:
            result.append(part.lower())
    return result


if __name__ == "__main__":
    """Test the correction tracker with mock data."""
    print("Testing CorrectionTracker...")

    # Create baseline VolumeData
    baseline = VolumeData(volume="Volume_226.txt")
    case0 = Case(case_id="vol226_case_0", status="auto_extracted")
    case0.annotations.append(Annotation(
        label="start_of_case", text="SECOND DIVISION", group=None,
        start_char=100, end_char=115, start_line=10, end_line=10,
        start_page=1, end_page=1
    ))
    case0.annotations.append(Annotation(
        label="parties", text="WRONG PARTIES TEXT", group=0,
        start_char=200, end_char=218, start_line=15, end_line=15,
        start_page=1, end_page=1
    ))
    case0.annotations.append(Annotation(
        label="ponente", text="GUTIERREZ, JR.", group=None,
        start_char=300, end_char=314, start_line=20, end_line=20,
        start_page=1, end_page=1
    ))

    case1 = Case(case_id="vol226_case_1", status="auto_extracted")
    case1.annotations.append(Annotation(
        label="start_of_case", text="EN BANC", group=None,
        start_char=500, end_char=507, start_line=50, end_line=50,
        start_page=2, end_page=2
    ))

    baseline.cases = [case0, case1]

    # Create modified VolumeData (simulating human corrections)
    modified = VolumeData(volume="Volume_226.txt")

    mod_case0 = Case(case_id="vol226_case_0", status="in_progress")
    # start_of_case unchanged
    mod_case0.annotations.append(Annotation(
        label="start_of_case", text="SECOND DIVISION", group=None,
        start_char=100, end_char=115, start_line=10, end_line=10,
        start_page=1, end_page=1
    ))
    # parties removed and re-added with different span
    mod_case0.annotations.append(Annotation(
        label="parties", text="CORRECT PARTIES", group=0,
        start_char=205, end_char=220, start_line=15, end_line=16,
        start_page=1, end_page=1
    ))
    # ponente label changed to counsel
    mod_case0.annotations.append(Annotation(
        label="counsel", text="GUTIERREZ, JR.", group=None,
        start_char=300, end_char=314, start_line=20, end_line=20,
        start_page=1, end_page=1
    ))
    # New annotation added
    mod_case0.annotations.append(Annotation(
        label="date", text="May 23, 1986", group=None,
        start_char=150, end_char=162, start_line=12, end_line=12,
        start_page=1, end_page=1
    ))

    mod_case1 = Case(case_id="vol226_case_1", status="in_progress")
    mod_case1.annotations.append(Annotation(
        label="start_of_case", text="EN BANC", group=None,
        start_char=500, end_char=507, start_line=50, end_line=50,
        start_page=2, end_page=2
    ))

    modified.cases = [mod_case0, mod_case1]

    # Track and diff
    tracker = CorrectionTracker()
    tracker.set_baseline(baseline, "test_predictions.json", "x" * 1000)

    assert tracker.has_baseline(), "Baseline should be set"

    log = tracker.compute_diff(modified)

    print(f"Volume: {log.volume_name}")
    print(f"Total predicted: {log.total_predicted}")
    print(f"Total corrections: {log.summary['total_corrections']}")
    print(f"By type: {log.summary['by_type']}")
    print(f"By label: {log.summary['by_label']}")
    print(f"Cases with corrections: {log.summary['cases_with_corrections']}")
    print(f"Cases perfect: {log.summary['cases_perfect']}")
    print()

    for c in log.corrections:
        print(f"  [{c.correction_type}] {c.case_id} / {c.label}")
        if c.original:
            print(f"    original: {c.original['text'][:50]}")
        if c.corrected:
            print(f"    corrected: {c.corrected['text'][:50]}")

    # Assertions
    assert log.summary["total_corrections"] >= 3, (
        f"Expected at least 3 corrections, got {log.summary['total_corrections']}"
    )
    assert log.summary["cases_with_corrections"] == 1, (
        f"Expected 1 case with corrections, got {log.summary['cases_with_corrections']}"
    )
    assert log.summary["cases_perfect"] == 1, (
        f"Expected 1 perfect case, got {log.summary['cases_perfect']}"
    )

    print("\nAll tests passed!")
