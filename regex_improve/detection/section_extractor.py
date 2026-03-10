import re
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

# Add regex_improve/ to path so we can import from detection.preprocess and detection.boundary_fsm
_REGEX_IMPROVE_DIR = Path(__file__).resolve().parent.parent
if str(_REGEX_IMPROVE_DIR) not in sys.path:
    sys.path.insert(0, str(_REGEX_IMPROVE_DIR))

from detection.preprocess import VolumePreprocessor
from detection.boundary_fsm import CaseBoundary, CaseNumber

# Import Annotation from gui.models for type hints
try:
    from gui.models import Annotation
except ImportError:
    # Define a minimal Annotation class if gui.models is not available
    @dataclass
    class Annotation:
        label: str
        text: str
        start_line: int
        end_line: int
        start_char: int
        end_char: int
        start_page: int = 0
        end_page: int = 0
        group: Optional[int] = None
        confidence: float = 1.0


# Module-level regex constants
RE_SYLLABUS = re.compile(r'^SYLLABUS\s*$')
RE_COUNSEL_HEADER = re.compile(r'^APPEARANCES?\s+OF\s+COUNSEL\s*$', re.IGNORECASE)
RE_DOC_TYPE = re.compile(
    r'^(?:DECISION|RESOLUTION|'
    r'D\s+E\s+C\s+I\s+S\s+I\s+O\s+N|'
    r'R\s+E\s+S\s+O\s+L\s+U\s+T\s+I\s+O\s+N)\s*$'
)
RE_PONENTE = re.compile(
    r'^([A-Z][A-Z\s,.\'\-]+?),\s*(?:C\.?\s*J\.?\s*|J\.?\s*)[,:;]+\s*$'
)
RE_PER_CURIAM = re.compile(r'^PER\s+CURIAM\s*[,:;]*\s*$', re.IGNORECASE)
RE_SO_ORDERED = re.compile(r'^SO\s*ORDERED\s*[.,;]?\s*$', re.IGNORECASE)
RE_SEPARATE_OPINION = re.compile(
    r'^([A-Z][A-Z\s,.\'\-]+?),\s*(?:C\.?\s*J\.?\s*|J\.?\s*),?\s*'
    r'(?:concurring|dissenting|separate)\b',
    re.IGNORECASE
)


@dataclass
class ExtractedCase:
    case_id: str
    annotations: List[Annotation] = field(default_factory=list)
    confidence: float = 1.0
    notes: str = ""


class SectionExtractor:
    """Extracts all annotation labels within each case boundary."""
    
    def __init__(self, preprocessor: VolumePreprocessor):
        self.preprocessor = preprocessor
        self.loader = preprocessor.loader
    
    def extract_all(self, boundaries: List[CaseBoundary]) -> List[ExtractedCase]:
        """Extract annotations for all case boundaries."""
        extracted_cases = []
        
        for i, boundary in enumerate(boundaries):
            # Generate case_id: vol{N}_case_{i}
            # Extract volume number from filename (e.g., "Volume_226.txt" -> 226)
            vol_match = re.search(r'Volume_(\d+)', self.preprocessor.volume_name)
            vol_num = vol_match.group(1) if vol_match else "unknown"
            case_id = f"vol{vol_num}_case_{i}"
            
            extracted_case = self._extract_case(boundary, case_id)
            extracted_cases.append(extracted_case)
        
        return extracted_cases
    
    def _extract_case(self, boundary: CaseBoundary, case_id: str) -> ExtractedCase:
        """Extract all annotations for a single case."""
        extracted_case = ExtractedCase(case_id=case_id)
        
        # 1. start_of_case and division (same line and text)
        start_line = boundary.start_line
        division_text = boundary.division_text
        
        # Create start_of_case annotation
        start_ann = self._make_annotation(
            label="start_of_case",
            text=division_text,
            start_line=start_line,
            end_line=start_line,
            group=None
        )
        extracted_case.annotations.append(start_ann)
        
        # Create division annotation (identical coordinates)
        division_ann = self._make_annotation(
            label="division",
            text=division_text,
            start_line=start_line,
            end_line=start_line,
            group=None
        )
        extracted_case.annotations.append(division_ann)
        
        # 2. case_number annotations (from boundary.case_numbers)
        for cn in boundary.case_numbers:
            # Convert char offsets to line numbers
            start_line_num = self.loader.char_to_line(cn.start_char)
            end_line_num = self.loader.char_to_line(cn.end_char - 1)  # exclusive end
            # Get page numbers
            start_page = self.loader.get_page(cn.start_char)
            end_page = self.loader.get_page(cn.end_char - 1)
            
            case_num_ann = Annotation(
                label="case_number",
                text=cn.text,
                start_line=start_line_num,
                end_line=end_line_num,
                start_char=cn.start_char,
                end_char=cn.end_char,
                start_page=start_page,
                end_page=end_page,
                group=cn.group
            )
            extracted_case.annotations.append(case_num_ann)
        
        # 3. date annotation
        if boundary.date_text:
            # Convert char offsets to line numbers
            start_line_num = self.loader.char_to_line(boundary.date_start_char)
            end_line_num = self.loader.char_to_line(boundary.date_end_char - 1)
            # Get page numbers
            start_page = self.loader.get_page(boundary.date_start_char)
            end_page = self.loader.get_page(boundary.date_end_char - 1)
            
            date_ann = Annotation(
                label="date",
                text=boundary.date_text,
                start_line=start_line_num,
                end_line=end_line_num,
                start_char=boundary.date_start_char,
                end_char=boundary.date_end_char,
                start_page=start_page,
                end_page=end_page,
                group=None
            )
            extracted_case.annotations.append(date_ann)
        
        # Get content lines for this case
        content_lines = self.preprocessor.get_content_lines(
            boundary.start_line, boundary.end_line
        )
        
        if not content_lines:
            return extracted_case
        
        # Convert to list of (line_num, text) for easier processing
        lines = [(line_num, text) for line_num, text in content_lines]
        
        # Find the bracket line(s) using the case_numbers from boundary
        # Each CaseNumber has full_bracket_text and char offsets
        # We need to find which line each bracket is on
        bracket_line_nums = []
        for cn in boundary.case_numbers:
            # Get line number from start_char
            bracket_line_num = self.loader.char_to_line(cn.start_char)
            bracket_line_nums.append(bracket_line_num)
        
        # Extract parties - text after the last bracket until syllabus or doc_type
        if bracket_line_nums:
            last_bracket_line_num = max(bracket_line_nums)  # Use the last bracket (for consolidated cases)
            
            # Find the index of the last bracket line in our lines list
            last_bracket_idx = -1
            for i, (line_num, text) in enumerate(lines):
                if line_num == last_bracket_line_num:
                    last_bracket_idx = i
                    break
            
            if last_bracket_idx >= 0:
                # Find start of parties (line after last bracket)
                parties_start_idx = last_bracket_idx + 1
                if parties_start_idx < len(lines):
                    # Find end of parties (before syllabus or doc_type)
                    parties_end_idx = parties_start_idx
                    while parties_end_idx < len(lines):
                        line_num, text = lines[parties_end_idx]
                        if RE_SYLLABUS.match(text) or RE_DOC_TYPE.match(text):
                            break
                        parties_end_idx += 1
                    
                    # Extract parties text
                    if parties_end_idx > parties_start_idx:
                        parties_lines = lines[parties_start_idx:parties_end_idx]
                        # Remove leading/trailing blank lines
                        while parties_lines and not parties_lines[0][1].strip():
                            parties_lines.pop(0)
                        while parties_lines and not parties_lines[-1][1].strip():
                            parties_lines.pop()
                        
                        if parties_lines:
                            start_line_num = parties_lines[0][0]
                            end_line_num = parties_lines[-1][0]
                            # Get exact text from volume
                            start_char = self.loader.line_col_to_char(start_line_num, 0)
                            end_line_text = self.loader.get_line_text(end_line_num)
                            end_char = self.loader.line_col_to_char(end_line_num, len(end_line_text))
                            parties_text = self.loader.text[start_char:end_char]
                            
                            # Create parties annotation
                            parties_ann = self._make_annotation(
                                label="parties",
                                text=parties_text,
                                start_line=start_line_num,
                                end_line=end_line_num,
                                start_char=start_char,
                                end_char=end_char,
                                group=0  # TODO: handle consolidated cases with group assignment
                            )
                            extracted_case.annotations.append(parties_ann)
        
        # Process remaining sections sequentially
        # We'll scan through lines and extract sections as we encounter them
        current_idx = 0
        while current_idx < len(lines):
            line_num, text = lines[current_idx]
            
            # Check for syllabus
            if RE_SYLLABUS.match(text):
                # start_syllabus
                syllabus_start_ann = self._make_annotation(
                    label="start_syllabus",
                    text="SYLLABUS",
                    start_line=line_num,
                    end_line=line_num,
                    group=None
                )
                extracted_case.annotations.append(syllabus_start_ann)
                
                # Find end_syllabus
                end_syllabus_idx = current_idx + 1
                while end_syllabus_idx < len(lines):
                    end_line_num, end_text = lines[end_syllabus_idx]
                    if RE_COUNSEL_HEADER.match(end_text) or RE_DOC_TYPE.match(end_text):
                        break
                    end_syllabus_idx += 1
                
                # Go back to find last non-blank line before counsel/doc_type
                end_syllabus_line_idx = end_syllabus_idx - 1
                while end_syllabus_line_idx > current_idx and not lines[end_syllabus_line_idx][1].strip():
                    end_syllabus_line_idx -= 1
                
                if end_syllabus_line_idx > current_idx:
                    end_line_num, end_text = lines[end_syllabus_line_idx]
                    end_syllabus_ann = self._make_annotation(
                        label="end_syllabus",
                        text=end_text.strip(),
                        start_line=end_line_num,
                        end_line=end_line_num,
                        group=None
                    )
                    extracted_case.annotations.append(end_syllabus_ann)
                
                current_idx = end_syllabus_idx
                continue
            
            # Check for counsel header
            if RE_COUNSEL_HEADER.match(text):
                counsel_start_idx = current_idx
                counsel_end_idx = current_idx + 1
                while counsel_end_idx < len(lines):
                    end_line_num, end_text = lines[counsel_end_idx]
                    if RE_DOC_TYPE.match(end_text):
                        break
                    counsel_end_idx += 1
                
                # Get counsel text
                start_line_num = lines[counsel_start_idx][0]
                end_line_num = lines[counsel_end_idx - 1][0] if counsel_end_idx > counsel_start_idx + 1 else start_line_num
                start_char = self.loader.line_col_to_char(start_line_num, 0)
                end_line_text = self.loader.get_line_text(end_line_num)
                end_char = self.loader.line_col_to_char(end_line_num, len(end_line_text))
                counsel_text = self.loader.text[start_char:end_char]
                
                counsel_ann = self._make_annotation(
                    label="counsel",
                    text=counsel_text,
                    start_line=start_line_num,
                    end_line=end_line_num,
                    start_char=start_char,
                    end_char=end_char,
                    group=None
                )
                extracted_case.annotations.append(counsel_ann)
                
                current_idx = counsel_end_idx
                continue
            
            # Check for doc_type
            if RE_DOC_TYPE.match(text):
                doc_type_ann = self._make_annotation(
                    label="doc_type",
                    text=text.strip(),
                    start_line=line_num,
                    end_line=line_num,
                    group=None
                )
                extracted_case.annotations.append(doc_type_ann)
                
                # Look for ponente in next 1-3 lines
                ponente_found = False
                for offset in range(1, 4):
                    if current_idx + offset >= len(lines):
                        break
                    next_line_num, next_text = lines[current_idx + offset]
                    if not next_text.strip():
                        continue
                    
                    ponente_match = RE_PONENTE.match(next_text)
                    per_curiam_match = RE_PER_CURIAM.match(next_text)
                    
                    if ponente_match:
                        ponente_text = ponente_match.group(1).strip()
                        ponente_ann = self._make_annotation(
                            label="ponente",
                            text=ponente_text,
                            start_line=next_line_num,
                            end_line=next_line_num,
                            group=None
                        )
                        extracted_case.annotations.append(ponente_ann)
                        ponente_found = True
                        current_idx += offset
                        break
                    elif per_curiam_match:
                        ponente_ann = self._make_annotation(
                            label="ponente",
                            text="PER CURIAM",
                            start_line=next_line_num,
                            end_line=next_line_num,
                            group=None
                        )
                        extracted_case.annotations.append(ponente_ann)
                        ponente_found = True
                        current_idx += offset
                        break
                
                # If ponente not found, skip ahead
                if not ponente_found:
                    current_idx += 1
                continue
            
            # Check for start_decision (first non-blank line after ponente/doc_type)
            # We'll handle this after we've found doc_type and ponente
            # For now, just increment
            current_idx += 1
        
        # Now we need to find start_decision, end_decision, votes, etc.
        # We'll do a second pass focusing on the decision section
        
        # Find doc_type annotation to know where decision section starts
        doc_type_ann = None
        for ann in extracted_case.annotations:
            if ann.label == "doc_type":
                doc_type_ann = ann
                break
        
        if doc_type_ann:
            # Find ponente annotation
            ponente_ann = None
            for ann in extracted_case.annotations:
                if ann.label == "ponente":
                    ponente_ann = ann
                    break
            
            # Find start_decision: first non-blank line after ponente (or after doc_type if no ponente)
            search_start_line = ponente_ann.end_line + 1 if ponente_ann else doc_type_ann.end_line + 1
            
            # Get content lines from search_start_line to end of case
            decision_lines = []
            for line_num, text in lines:
                if line_num >= search_start_line:
                    decision_lines.append((line_num, text))
            
            # Find start_decision (first non-blank line)
            start_decision_line = None
            start_decision_text = None
            for line_num, text in decision_lines:
                if text.strip():
                    start_decision_line = line_num
                    start_decision_text = text
                    break
            
            if start_decision_line:
                start_decision_ann = self._make_annotation(
                    label="start_decision",
                    text=start_decision_text,
                    start_line=start_decision_line,
                    end_line=start_decision_line,
                    group=None
                )
                extracted_case.annotations.append(start_decision_ann)
                
                # Find end_decision
                # Scan for SO ORDERED or other ending patterns
                end_decision_line = None
                end_decision_text = None
                
                for i, (line_num, text) in enumerate(decision_lines):
                    if RE_SO_ORDERED.match(text):
                        end_decision_line = line_num
                        end_decision_text = text
                        break
                    # Check for other ending patterns
                    if re.search(r'is\s+(ACQUITTED|DISMISSED|AFFIRMED)\.\s*No costs\.', text, re.IGNORECASE):
                        end_decision_line = line_num
                        end_decision_text = text
                        break
                    if re.search(r'This decision is immediately executory\.', text, re.IGNORECASE):
                        end_decision_line = line_num
                        end_decision_text = text
                        break
                    if re.search(r'It is so ordered\.', text, re.IGNORECASE):
                        end_decision_line = line_num
                        end_decision_text = text
                        break
                
                # If no explicit end marker found, use last content line before votes
                if not end_decision_line:
                    # Look for votes pattern (justice names after decision)
                    # For now, use a simple heuristic: last non-blank line before a line with "concur" or "dissenting"
                    last_content_line = None
                    last_content_text = None
                    for line_num, text in decision_lines:
                        if text.strip():
                            last_content_line = line_num
                            last_content_text = text
                    
                    if last_content_line:
                        end_decision_line = last_content_line
                        end_decision_text = last_content_text
                
                if end_decision_line:
                    end_decision_ann = self._make_annotation(
                        label="end_decision",
                        text=end_decision_text,
                        start_line=end_decision_line,
                        end_line=end_decision_line,
                        group=None
                    )
                    extracted_case.annotations.append(end_decision_ann)
                    
                    # Extract votes: lines after end_decision until separate opinion or end of case
                    votes_start_line = end_decision_line + 1
                    votes_lines = []
                    for line_num, text in lines:
                        if line_num >= votes_start_line and line_num <= boundary.end_line:
                            votes_lines.append((line_num, text))
                    
                    # Find where votes end (separate opinion or end of case)
                    votes_end_idx = 0
                    while votes_end_idx < len(votes_lines):
                        line_num, text = votes_lines[votes_end_idx]
                        if RE_SEPARATE_OPINION.match(text):
                            break
                        votes_end_idx += 1
                    
                    votes_text_lines = []
                    if votes_end_idx > 0:
                        votes_text_lines = votes_lines[:votes_end_idx]
                        # Remove trailing blank lines
                        while votes_text_lines and not votes_text_lines[-1][1].strip():
                            votes_text_lines.pop()
                        
                        if votes_text_lines:
                            start_line_num = votes_text_lines[0][0]
                            end_line_num = votes_text_lines[-1][0]
                            start_char = self.loader.line_col_to_char(start_line_num, 0)
                            end_line_text = self.loader.get_line_text(end_line_num)
                            end_char = self.loader.line_col_to_char(end_line_num, len(end_line_text))
                            votes_text = self.loader.text[start_char:end_char]
                            
                            votes_ann = self._make_annotation(
                                label="votes",
                                text=votes_text,
                                start_line=start_line_num,
                                end_line=end_line_num,
                                start_char=start_char,
                                end_char=end_char,
                                group=None
                            )
                            extracted_case.annotations.append(votes_ann)
                    
                    # Check for separate opinions
                    if votes_end_idx < len(votes_lines):
                        # There's a separate opinion
                        sep_opinion_line_num, sep_opinion_text = votes_lines[votes_end_idx]
                        start_opinion_ann = self._make_annotation(
                            label="start_opinion",
                            text=sep_opinion_text,
                            start_line=sep_opinion_line_num,
                            end_line=sep_opinion_line_num,
                            group=None
                        )
                        extracted_case.annotations.append(start_opinion_ann)
                        
                        # Find end_opinion (last non-blank line before next start_opinion or end of case)
                        opinion_lines = votes_lines[votes_end_idx:]
                        end_opinion_idx = 0
                        while end_opinion_idx < len(opinion_lines):
                            line_num, text = opinion_lines[end_opinion_idx]
                            # Check if this is another separate opinion
                            if end_opinion_idx > 0 and RE_SEPARATE_OPINION.match(text):
                                break
                            end_opinion_idx += 1
                        
                        # Go back to find last non-blank line
                        last_opinion_idx = end_opinion_idx - 1
                        while last_opinion_idx >= 0 and not opinion_lines[last_opinion_idx][1].strip():
                            last_opinion_idx -= 1
                        
                        if last_opinion_idx >= 0:
                            end_line_num, end_text = opinion_lines[last_opinion_idx]
                            end_opinion_ann = self._make_annotation(
                                label="end_opinion",
                                text=end_text.strip(),
                                start_line=end_line_num,
                                end_line=end_line_num,
                                group=None
                            )
                            extracted_case.annotations.append(end_opinion_ann)
                            
                            # end_of_case is same as end_opinion
                            end_of_case_ann = self._make_annotation(
                                label="end_of_case",
                                text=end_text.strip(),
                                start_line=end_line_num,
                                end_line=end_line_num,
                                group=None
                            )
                            extracted_case.annotations.append(end_of_case_ann)
                        else:
                            # No end_opinion found, use end_decision as end_of_case
                            end_of_case_ann = self._make_annotation(
                                label="end_of_case",
                                text=end_decision_text,
                                start_line=end_decision_line,
                                end_line=end_decision_line,
                                group=None
                            )
                            extracted_case.annotations.append(end_of_case_ann)
                    else:
                        # No separate opinion, end_of_case is last line of votes or end_decision
                        if votes_text_lines:
                            last_votes_line_num, last_votes_text = votes_text_lines[-1]
                            end_of_case_ann = self._make_annotation(
                                label="end_of_case",
                                text=last_votes_text.strip(),
                                start_line=last_votes_line_num,
                                end_line=last_votes_line_num,
                                group=None
                            )
                        else:
                            end_of_case_ann = self._make_annotation(
                                label="end_of_case",
                                text=end_decision_text,
                                start_line=end_decision_line,
                                end_line=end_decision_line,
                                group=None
                            )
                        extracted_case.annotations.append(end_of_case_ann)
        
        return extracted_case
    
    def _make_annotation(self, label: str, text: str,
                        start_line: int, end_line: int,
                        start_char: int = None, end_char: int = None,
                        group: Optional[int] = None) -> Annotation:
        """Create Annotation with all coordinate fields."""
        
        # If char offsets not provided, compute from line numbers
        if start_char is None or end_char is None:
            # For single-line annotations
            if start_line == end_line:
                line_text = self.loader.get_line_text(start_line)
                # Find text in line (first 40 chars for matching)
                search_text = text[:40]
                pos = line_text.find(search_text)
                if pos == -1:
                    # Text not found, use start of line
                    start_char = self.loader.line_col_to_char(start_line, 0)
                else:
                    start_char = self.loader.line_col_to_char(start_line, pos)
                end_char = start_char + len(text)
            else:
                # Multi-line annotation
                start_char = self.loader.line_col_to_char(start_line, 0)
                # Get end of last line
                end_line_text = self.loader.get_line_text(end_line)
                end_char = self.loader.line_col_to_char(end_line, len(end_line_text))
        
        # Get page numbers
        start_page = self.loader.get_page(start_char)
        end_page = self.loader.get_page(end_char - 1)  # exclusive end
        
        return Annotation(
            label=label,
            text=text,
            start_line=start_line,
            end_line=end_line,
            start_char=start_char,
            end_char=end_char,
            start_page=start_page,
            end_page=end_page,
            group=group
        )


if __name__ == "__main__":
    """Test block."""
    # Navigate to project root to find downloads/Volume_226.txt
    project_root = Path(__file__).resolve().parent.parent.parent
    volume_path = project_root / "downloads" / "Volume_226.txt"
    
    if not volume_path.exists():
        print(f"Error: {volume_path} not found")
        sys.exit(1)
    
    # Load and preprocess
    preprocessor = VolumePreprocessor()
    preprocessor.load(volume_path)
    
    # Detect boundaries
    from detection.boundary_fsm import CaseBoundaryDetector
    detector = CaseBoundaryDetector(preprocessor)
    boundaries = detector.detect()
    
    print(f"Detected {len(boundaries)} boundaries")
    
    # Extract sections
    extractor = SectionExtractor(preprocessor)
    extracted_cases = extractor.extract_all(boundaries)
    
    print(f"Extracted {len(extracted_cases)} cases")
    
    # Print per-label annotation counts
    label_counts = {}
    for case in extracted_cases:
        for ann in case.annotations:
            label_counts[ann.label] = label_counts.get(ann.label, 0) + 1
    
    print("\nPer-label annotation counts:")
    for label, count in sorted(label_counts.items()):
        print(f"  {label}: {count}")
    
    # Print case 0 annotations in detail
    if extracted_cases:
        print(f"\nCase 0 (ID: {extracted_cases[0].case_id}) annotations:")
        for ann in extracted_cases[0].annotations:
            print(f"  {ann.label}: '{ann.text}' (lines {ann.start_line}-{ann.end_line})")