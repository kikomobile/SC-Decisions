"""Extraction method evaluation framework."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import importlib.util
import re
from pathlib import Path

from gui.models import AnnotationStore, Annotation, Case, VolumeData
from gui.volume_loader import VolumeLoader
from gui.constants import IMPROVED_REGEX_FILE


@dataclass
class ExtractedField:
    """A single field extracted by a method."""
    label: str        # matches annotation label keys
    text: str         # extracted text
    start_char: int   # 0-based offset within the CASE text (not volume text)
    end_char: int
    group: Optional[int] = None


class ExtractionMethod(ABC):
    """Protocol for pluggable extraction methods."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Method identifier, e.g. 'regex', 'spacy_ner', 'llm'."""
        ...

    @abstractmethod
    def extract(self, text: str, start_line: int) -> List[ExtractedField]:
        """Given raw case text, return extracted fields.
        Args:
            text: raw text of the case (from start_of_case line to end_of_case line)
            start_line: 1-based line number of the case start in the volume
        Returns:
            list of ExtractedField objects
        """
        ...


class RegexMethod(ExtractionMethod):
    """Wraps improved_regex.py (or falls back to annotate_tool.py patterns)."""

    @property
    def name(self) -> str:
        return "regex"

    def __init__(self, regex_path: Path):
        """Load patterns from the regex file.
        Use importlib.util to dynamically load the module.
        For each expected pattern name (RE_CASE_BRACKET, RE_CASE_NUM, RE_DATE,
        RE_DIVISION, RE_PONENTE, RE_DECISION, RE_RESOLUTION, RE_SYLLABUS,
        RE_COUNSEL, RE_SEPARATE_OPINION), check if the module defines it.
        Fall back to annotate_tool.py patterns for undefined ones.

        Implementation:
        1. spec = importlib.util.spec_from_file_location("improved_regex", regex_path)
        2. mod = importlib.util.module_from_spec(spec)
        3. spec.loader.exec_module(mod)
        4. self.patterns = {} — populate from module attributes with fallbacks
        """
        self.patterns = {}
        
        # Try to load from the specified regex file
        if regex_path.exists():
            try:
                spec = importlib.util.spec_from_file_location("improved_regex", regex_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                
                # Define expected pattern names
                expected_patterns = [
                    "RE_CASE_BRACKET", "RE_CASE_NUM", "RE_DATE", "RE_DIVISION",
                    "RE_PONENTE", "RE_DECISION", "RE_RESOLUTION", "RE_SYLLABUS",
                    "RE_COUNSEL", "RE_SEPARATE_OPINION"
                ]
                
                for pattern_name in expected_patterns:
                    if hasattr(mod, pattern_name):
                        self.patterns[pattern_name] = getattr(mod, pattern_name)
                    else:
                        # Fallback to annotate_tool.py patterns
                        self._load_fallback_pattern(pattern_name)
            except Exception as e:
                print(f"Warning: Failed to load regex patterns from {regex_path}: {e}")
                self._load_all_fallback_patterns()
        else:
            # File doesn't exist, use fallbacks
            self._load_all_fallback_patterns()

    def _load_fallback_pattern(self, pattern_name: str):
        """Load a fallback pattern from annotate_tool.py."""
        # These are simplified versions of patterns from annotate_tool.py
        fallback_patterns = {
            "RE_CASE_BRACKET": re.compile(r'\[(G\.R\.\s*No\.\s*\d+)\]'),
            "RE_CASE_NUM": re.compile(r'G\.R\.\s*No\.\s*\d+(?:-\d+)?'),
            "RE_DATE": re.compile(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b'),
            "RE_DIVISION": re.compile(r'\b(?:FIRST|SECOND|THIRD|EN BANC)\s+DIVISION\b'),
            "RE_PONENTE": re.compile(r'\bJ\.\s+[A-Z\s\.]+\b'),
            "RE_DECISION": re.compile(r'\bDECISION\b'),
            "RE_RESOLUTION": re.compile(r'\bRESOLUTION\b'),
            "RE_SYLLABUS": re.compile(r'\bSYLLABUS\b'),
            "RE_COUNSEL": re.compile(r'\b(?:Petitioner|Respondent|Appellant|Appellee)[^\.]*\.'),
            "RE_SEPARATE_OPINION": re.compile(r'\b(?:Separate|Concurring|Dissenting)\s+Opinion\b'),
        }
        
        if pattern_name in fallback_patterns:
            self.patterns[pattern_name] = fallback_patterns[pattern_name]

    def _load_all_fallback_patterns(self):
        """Load all fallback patterns."""
        pattern_names = [
            "RE_CASE_BRACKET", "RE_CASE_NUM", "RE_DATE", "RE_DIVISION",
            "RE_PONENTE", "RE_DECISION", "RE_RESOLUTION", "RE_SYLLABUS",
            "RE_COUNSEL", "RE_SEPARATE_OPINION"
        ]
        for pattern_name in pattern_names:
            self._load_fallback_pattern(pattern_name)

    def extract(self, text: str, start_line: int) -> List[ExtractedField]:
        """Run all regex patterns on the case text.

        Extract:
        - case_number: all RE_CASE_NUM matches
        - date: first RE_DATE match
        - division: first RE_DIVISION match
        - ponente: first RE_PONENTE match
        - doc_type: "DECISION" if RE_DECISION matches, else "RESOLUTION" if RE_RESOLUTION matches

        For each match, compute start_char/end_char relative to the case text.
        Return list of ExtractedField.
        """
        extracted = []
        
        # Extract case numbers
        if "RE_CASE_NUM" in self.patterns:
            for match in self.patterns["RE_CASE_NUM"].finditer(text):
                extracted.append(ExtractedField(
                    label="case_number",
                    text=match.group(),
                    start_char=match.start(),
                    end_char=match.end(),
                    group=0  # Default group 0, will be adjusted later if multiple
                ))
        
        # Extract date
        if "RE_DATE" in self.patterns:
            match = self.patterns["RE_DATE"].search(text)
            if match:
                extracted.append(ExtractedField(
                    label="date",
                    text=match.group(),
                    start_char=match.start(),
                    end_char=match.end()
                ))
        
        # Extract division
        if "RE_DIVISION" in self.patterns:
            match = self.patterns["RE_DIVISION"].search(text)
            if match:
                extracted.append(ExtractedField(
                    label="division",
                    text=match.group(),
                    start_char=match.start(),
                    end_char=match.end()
                ))
        
        # Extract ponente
        if "RE_PONENTE" in self.patterns:
            match = self.patterns["RE_PONENTE"].search(text)
            if match:
                extracted.append(ExtractedField(
                    label="ponente",
                    text=match.group(),
                    start_char=match.start(),
                    end_char=match.end()
                ))
        
        # Extract document type
        if "RE_DECISION" in self.patterns and self.patterns["RE_DECISION"].search(text):
            extracted.append(ExtractedField(
                label="doc_type",
                text="DECISION",
                start_char=0,
                end_char=0  # No specific position for document type
            ))
        elif "RE_RESOLUTION" in self.patterns and self.patterns["RE_RESOLUTION"].search(text):
            extracted.append(ExtractedField(
                label="doc_type",
                text="RESOLUTION",
                start_char=0,
                end_char=0
            ))
        
        # Adjust case number groups if multiple case numbers
        case_numbers = [f for f in extracted if f.label == "case_number"]
        if len(case_numbers) > 1:
            for i, field in enumerate(case_numbers):
                field.group = i
        
        return extracted


@dataclass
class FieldScore:
    """Score for a single field in a single case."""
    label: str
    expected_text: str
    actual_text: Optional[str]
    exact_match: bool
    overlap: bool        # spans overlap
    detected: bool       # field was found at all
    expected_group: Optional[int] = None
    actual_group: Optional[int] = None


@dataclass
class CaseScore:
    """Evaluation results for one case."""
    case_id: str
    fields: List[FieldScore] = field(default_factory=list)


@dataclass
class EvaluationResult:
    """Full evaluation results."""
    method_name: str
    cases: List[CaseScore] = field(default_factory=list)

    def precision(self, label: str = None) -> float:
        """Compute precision (correct detections / total detections).
        If label is specified, filter to that label only."""
        if label:
            relevant_fields = []
            for case in self.cases:
                for field in case.fields:
                    if field.label == label:
                        relevant_fields.append(field)
        else:
            relevant_fields = [field for case in self.cases for field in case.fields]
        
        if not relevant_fields:
            return 0.0
        
        true_positives = sum(1 for f in relevant_fields if f.detected and f.exact_match)
        total_detections = sum(1 for f in relevant_fields if f.detected)
        
        if total_detections == 0:
            return 0.0
        return true_positives / total_detections

    def recall(self, label: str = None) -> float:
        """Compute recall (correct detections / total expected)."""
        if label:
            relevant_fields = []
            for case in self.cases:
                for field in case.fields:
                    if field.label == label:
                        relevant_fields.append(field)
        else:
            relevant_fields = [field for case in self.cases for field in case.fields]
        
        if not relevant_fields:
            return 0.0
        
        true_positives = sum(1 for f in relevant_fields if f.detected and f.exact_match)
        total_expected = len(relevant_fields)
        
        if total_expected == 0:
            return 0.0
        return true_positives / total_expected

    def f1(self, label: str = None) -> float:
        """Compute F1 score."""
        p = self.precision(label)
        r = self.recall(label)
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)

    def summary_table(self) -> str:
        """Return a formatted text table of per-field precision/recall/F1.
        Format:
        | Field        | Precision | Recall | F1    |
        |-------------|-----------|--------|-------|
        | case_number | 0.95      | 0.90   | 0.92  |
        | date        | 1.00      | 0.95   | 0.97  |
        | ...         |           |        |       |
        | OVERALL     | 0.93      | 0.88   | 0.90  |
        """
        # Get all unique labels
        labels = set()
        for case in self.cases:
            for field in case.fields:
                labels.add(field.label)
        
        # Sort labels for consistent output
        sorted_labels = sorted(labels)
        
        # Build table
        lines = []
        lines.append("| Field        | Precision | Recall | F1    |")
        lines.append("|-------------|-----------|--------|-------|")
        
        for label in sorted_labels:
            p = self.precision(label)
            r = self.recall(label)
            f1 = self.f1(label)
            lines.append(f"| {label:<12} | {p:.3f}      | {r:.3f}   | {f1:.3f}  |")
        
        # Add overall row
        p_overall = self.precision()
        r_overall = self.recall()
        f1_overall = self.f1()
        lines.append(f"| OVERALL     | {p_overall:.3f}      | {r_overall:.3f}   | {f1_overall:.3f}  |")
        
        return "\n".join(lines)


class EvaluationRunner:
    """Runs an extraction method against ground truth annotations."""

    def __init__(self, store: AnnotationStore, loaders: Dict[str, VolumeLoader]):
        self.store = store
        self.loaders = loaders  # volume_filename -> VolumeLoader

    def run(self, method: ExtractionMethod) -> EvaluationResult:
        """Run the extraction method against all annotated cases.

        For each volume in the store:
          For each complete case (has both start_of_case and end_of_case):
            1. Get case text: volume text from start_of_case line to end_of_case line
            2. Run method.extract(case_text, start_line)
            3. Compare extracted fields against annotations:
               - For each annotation label in the case:
                 - Find matching extracted field(s) by label
                 - Score exact_match, overlap, detected
            4. Build CaseScore

        Return EvaluationResult with all case scores.
        """
        result = EvaluationResult(method_name=method.name)
        
        for volume_name, volume_data in self.store.volumes.items():
            loader = self.loaders.get(volume_name)
            if not loader:
                continue  # Skip volumes without loader
            
            for case in volume_data.cases:
                # Check if case is complete (has both start and end)
                start_line = case.get_start_line()
                end_line = case.get_end_line()
                
                if not start_line or not end_line:
                    continue  # Skip incomplete cases
                
                # Get case text from loader
                case_text = self._get_case_text(loader, start_line, end_line)
                if not case_text:
                    continue
                
                # Compute case start character offset
                case_start_char = loader.line_col_to_char(start_line, 0)
                
                # Run extraction method
                extracted_fields = method.extract(case_text, start_line)
                
                # Score annotations against extracted fields
                case_score = self._score_case(case, extracted_fields, case_start_char)
                result.cases.append(case_score)
        
        return result

    def _get_case_text(self, loader: VolumeLoader, start_line: int, end_line: int) -> Optional[str]:
        """Get text of a case from start_line to end_line inclusive."""
        try:
            # Get character offsets for start and end
            start_char = loader.line_col_to_char(start_line, 0)
            # For end line, we need the end of the line
            end_line_text = loader.get_line_text(end_line)
            end_char = loader.line_col_to_char(end_line, len(end_line_text))
            
            # Extract text
            return loader.text[start_char:end_char]
        except Exception:
            return None

    def _score_case(self, case: Case, extracted_fields: List[ExtractedField], 
                   case_start_char: int) -> CaseScore:
        """Score a single case."""
        case_score = CaseScore(case_id=case.case_id)
        
        # Group extracted fields by label
        extracted_by_label: Dict[str, List[ExtractedField]] = {}
        for field in extracted_fields:
            extracted_by_label.setdefault(field.label, []).append(field)
        
        # Score each annotation
        for annotation in case.annotations:
            # Skip start_of_case and end_of_case annotations for evaluation
            if annotation.label in ["start_of_case", "end_of_case"]:
                continue
            
            # Find matching extracted field(s)
            matching_fields = extracted_by_label.get(annotation.label, [])
            
            # For grouped labels (case_number, parties), we need to match by group
            if annotation.group is not None:
                matching_fields = [f for f in matching_fields if f.group == annotation.group]
            
            # Find best match
            best_match = None
            best_overlap = False
            best_exact = False
            
            for field in matching_fields:
                # Adjust field positions to be relative to volume (not case)
                field_start_vol = case_start_char + field.start_char
                field_end_vol = case_start_char + field.end_char
                
                # Check overlap
                overlap = self._spans_overlap(
                    annotation.start_char, annotation.end_char,
                    field_start_vol, field_end_vol
                )
                
                # Check exact match
                exact = (annotation.text.strip() == field.text.strip() and 
                        overlap)  # And positions match
                
                if exact:
                    best_match = field
                    best_exact = True
                    best_overlap = True
                    break
                elif overlap and not best_overlap:
                    best_match = field
                    best_overlap = True
                    best_exact = False
                elif not best_match:
                    best_match = field
                    best_overlap = False
                    best_exact = False
            
            # Create field score
            if best_match:
                field_score = FieldScore(
                    label=annotation.label,
                    expected_text=annotation.text,
                    actual_text=best_match.text,
                    exact_match=best_exact,
                    overlap=best_overlap,
                    detected=True,
                    expected_group=annotation.group,
                    actual_group=best_match.group
                )
            else:
                # No match found
                field_score = FieldScore(
                    label=annotation.label,
                    expected_text=annotation.text,
                    actual_text=None,
                    exact_match=False,
                    overlap=False,
                    detected=False,
                    expected_group=annotation.group,
                    actual_group=None
                )
            
            case_score.fields.append(field_score)
        
        return case_score

    def _spans_overlap(self, a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
        """Check if two character spans overlap."""
        return a_start < b_end and b_start < a_end
                   