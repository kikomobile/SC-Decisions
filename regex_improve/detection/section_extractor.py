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
from detection.justice_registry import load_justices
from .pattern_registry import get_era_config

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

# Cached justice registry for WHEREFORE fallback
_KNOWN_JUSTICES = None

def _get_known_justices():
    """Load and cache known justice surnames for WHEREFORE fallback."""
    global _KNOWN_JUSTICES
    if _KNOWN_JUSTICES is None:
        _KNOWN_JUSTICES = load_justices()
    return _KNOWN_JUSTICES

def _line_has_justice_surname(text, justices):
    """Check if a line contains any known justice surname (loose match)."""
    text_upper = text.upper()
    for surname in justices:
        if surname.upper() in text_upper:
            return True
    return False


@dataclass
class ExtractedCase:
    case_id: str
    annotations: List[Annotation] = field(default_factory=list)
    confidence: float = 1.0
    notes: str = ""


class SectionExtractor:
    """Extracts all annotation labels within each case boundary."""
    
    def __init__(self, preprocessor: VolumePreprocessor, vol_num: Optional[int] = None):
        self.preprocessor = preprocessor
        self.loader = preprocessor.loader
        self.vol_num: Optional[int] = vol_num
        self.config = get_era_config(vol_num)
    
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
            # Get page numbers - FIX-6: Convert char offset to line number first
            start_page = self.loader.get_page(self.loader.char_to_line(cn.start_char))
            end_page = self.loader.get_page(self.loader.char_to_line(cn.end_char - 1))
            
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
            # Get page numbers - FIX-6: Convert char offset to line number first
            start_page = self.loader.get_page(self.loader.char_to_line(boundary.date_start_char))
            end_page = self.loader.get_page(self.loader.char_to_line(boundary.date_end_char - 1))
            
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

                # ERA-2: skip votes-continuation lines from previous case
                # (e.g., Vol 421 case 5 where case 4's votes wrap past bracket)
                if self.config.votes_extend_past_boundary:
                    justices_skip = _get_known_justices()
                    while parties_start_idx < len(lines):
                        _, skip_text = lines[parties_start_idx]
                        if not skip_text.strip():
                            parties_start_idx += 1
                            continue
                        if self.config.re_votes_content.search(skip_text) and \
                           _line_has_justice_surname(skip_text, justices_skip):
                            parties_start_idx += 1
                            continue
                        break

                if parties_start_idx < len(lines):
                    # FIX-5: Smart parties extraction with footnote protection
                    # Parties blocks end with a legal designation like "respondents.", "petitioner.", etc.
                    # When footnotes from the previous case appear on the same page, they get absorbed.
                    # Stop parties when we hit:
                    # (a) RE_SYLLABUS or RE_DOC_TYPE (existing)
                    # (b) A line ending with a legal designation (RE_PARTIES_END), then blank line
                    # (c) Footnote-like lines (start with digit+space, quote, or asterisk)
                    # FIX-234-4: Parties extraction with "vs." + second designation requirement
                    parties_end_idx = parties_start_idx
                    seen_first_designation = False
                    seen_vs = False

                    while parties_end_idx < len(lines):
                        line_num, text = lines[parties_end_idx]

                        # Stop condition (a): RE_SYLLABUS or RE_DOC_TYPE — always stop
                        if self.config.re_syllabus.match(text) or self.config.re_doc_type.match(text):
                            break

                        # Track "vs." lines
                        if self.config.re_vs_line.match(text) or 'vs.' in text.lower():
                            seen_vs = True

                        # Check if this line ends with a legal designation
                        if self.config.re_parties_end.search(text):
                            if not seen_first_designation:
                                if seen_vs:
                                    # Already past vs. — this is the terminal designation
                                    parties_end_idx += 1
                                    while parties_end_idx < len(lines) and not lines[parties_end_idx][1].strip():
                                        parties_end_idx += 1
                                    break
                                else:
                                    seen_first_designation = True
                            else:
                                # Second designation — terminal (e.g. "respondents.")
                                parties_end_idx += 1
                                while parties_end_idx < len(lines) and not lines[parties_end_idx][1].strip():
                                    parties_end_idx += 1
                                break

                        # Stop at footnote-like lines only after terminal designation
                        if self.config.re_footnote_start.match(text):
                            if seen_first_designation and seen_vs:
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

                            # ERA-2: detect pre-header parties (parties before division/bracket)
                            if parties_text.lstrip().upper().startswith('VS'):
                                self._detect_pre_header_parties(extracted_case, boundary)

        # Process remaining sections sequentially
        # We'll scan through lines and extract sections as we encounter them
        current_idx = 0
        while current_idx < len(lines):
            line_num, text = lines[current_idx]
            
            # Check for syllabus (skip for era5 which has has_syllabus=False)
            if self.config.has_syllabus and self.config.re_syllabus.match(text):
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
                    if self.config.re_counsel_header.match(end_text) or self.config.re_doc_type.match(end_text):
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
            if self.config.re_counsel_header.match(text):
                counsel_start_idx = current_idx
                # FIX-4: Smart counsel extraction with early termination
                # The counsel block has a predictable structure:
                # Line 1: "APPEARANCES OF COUNSEL" (or "APPEARANCE OF COUNSEL")
                # Lines 2+: Attorney names with "for petitioner/respondent/..." designations
                # Stop counsel when we hit:
                # (a) RE_DOC_TYPE
                # (b) Two consecutive blank lines
                # (c) A line that matches RE_DIVISION or RE_CASE_BRACKET (next case boundary)
                # (d) 30 lines scanned without finding any "for" designation (safety limit)
                counsel_end_idx = current_idx + 1
                lines_scanned = 0
                max_lines_to_scan = 30
                consecutive_blank_lines = 0
                seen_designation = False
                
                while counsel_end_idx < len(lines) and lines_scanned < max_lines_to_scan:
                    end_line_num, end_text = lines[counsel_end_idx]
                    
                    # Stop condition (a): RE_DOC_TYPE
                    if self.config.re_doc_type.match(end_text):
                        break
                    
                    # Stop condition (c): RE_DIVISION or RE_CASE_BRACKET (next case)
                    if self.config.re_division.match(end_text) or self.config.re_case_bracket.match(end_text):
                        break
                    
                    # Check for blank line
                    if not end_text.strip():
                        consecutive_blank_lines += 1
                        # Stop condition (b): Two consecutive blank lines
                        if consecutive_blank_lines >= 2 and seen_designation:
                            # Go back to last non-blank line
                            while counsel_end_idx > counsel_start_idx + 1 and not lines[counsel_end_idx-1][1].strip():
                                counsel_end_idx -= 1
                            break
                    else:
                        consecutive_blank_lines = 0
                        lines_scanned += 1
                        
                        # Check if this line contains an attorney designation
                        if self.config.re_counsel_designation.search(end_text):
                            seen_designation = True
                        
                        # If we've seen a designation and this line doesn't have one,
                        # it might be the end of the counsel block
                        if seen_designation and not self.config.re_counsel_designation.search(end_text):
                            # Check if this looks like a continuation of an attorney name
                            # (e.g., multi-line attorney entries)
                            # Simple heuristic: if line is short (< 50 chars) and doesn't start with footnote marker
                            if len(end_text.strip()) < 50 and not self.config.re_footnote_start.match(end_text):
                                # Might still be part of counsel (e.g., second line of attorney name)
                                pass
                            else:
                                # Probably not part of counsel, stop here
                                break
                    
                    counsel_end_idx += 1
                
                # If we never saw a designation (unusual formatting), fall back to RE_DOC_TYPE termination
                if not seen_designation:
                    # Reset and use original logic (stop at RE_DOC_TYPE)
                    counsel_end_idx = current_idx + 1
                    while counsel_end_idx < len(lines):
                        end_line_num, end_text = lines[counsel_end_idx]
                        if self.config.re_doc_type.match(end_text):
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
            if self.config.re_doc_type.match(text):
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
                    
                    ponente_match = self.config.re_ponente.match(next_text)
                    per_curiam_match = self.config.re_per_curiam.match(next_text)
                    
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
                # FIX-3: Track the LAST match, not the first, to avoid matching quoted
                # "SO ORDERED." from lower court orders within the decision text
                end_decision_line = None
                end_decision_text = None
                
                for i, (line_num, text) in enumerate(decision_lines):
                    if self.config.re_so_ordered.match(text):
                        end_decision_line = line_num
                        end_decision_text = text
                        # Do NOT break - continue to find the last occurrence
                    # Check for other ending patterns
                    elif re.search(r'is\s+(ACQUITTED|DISMISSED|AFFIRMED)\.\s*No costs\.', text, re.IGNORECASE):
                        end_decision_line = line_num
                        end_decision_text = text
                        # Do NOT break - continue to find the last occurrence
                    elif re.search(r'This decision is immediately executory\.', text, re.IGNORECASE):
                        end_decision_line = line_num
                        end_decision_text = text
                        # Do NOT break - continue to find the last occurrence
                    elif re.search(r'It is so ordered\.', text, re.IGNORECASE):
                        end_decision_line = line_num
                        end_decision_text = text
                        # Do NOT break - continue to find the last occurrence
                
                # If no explicit end marker found, use WHEREFORE fallback (FIX-234-1)
                if not end_decision_line:
                    # WHEREFORE fallback: find the LAST "WHEREFORE" paragraph that is
                    # followed within ~20 lines by justice surnames (votes block).
                    justices = _get_known_justices()
                    wherefore_candidates = []
                    for i, (line_num, text) in enumerate(decision_lines):
                        if self.config.re_wherefore.match(text):
                            wherefore_candidates.append((i, line_num, text))
                    
                    # Check candidates in reverse (last first)
                    for cand_idx, cand_line, cand_text in reversed(wherefore_candidates):
                        found_justice = False
                        for look_idx in range(cand_idx + 1, min(cand_idx + 21, len(decision_lines))):
                            look_text = decision_lines[look_idx][1]
                            if _line_has_justice_surname(look_text, justices):
                                found_justice = True
                                break
                        if found_justice:
                            # Found the dispositif WHEREFORE. Scan forward to find last
                            # non-blank line before the first justice-surname line.
                            para_end_line = cand_line
                            para_end_text = cand_text
                            for scan_idx in range(cand_idx + 1, min(cand_idx + 21, len(decision_lines))):
                                scan_line_num, scan_text = decision_lines[scan_idx]
                                if _line_has_justice_surname(scan_text, justices):
                                    break
                                if scan_text.strip():
                                    para_end_line = scan_line_num
                                    para_end_text = scan_text
                            end_decision_line = para_end_line
                            end_decision_text = para_end_text
                            break
                    
                    # Ultimate fallback: last non-blank content line
                    if not end_decision_line:
                        for line_num, text in decision_lines:
                            if text.strip():
                                end_decision_line = line_num
                                end_decision_text = text
                
                if end_decision_line:
                    end_decision_ann = self._make_annotation(
                        label="end_decision",
                        text=end_decision_text,
                        start_line=end_decision_line,
                        end_line=end_decision_line,
                        group=None
                    )
                    extracted_case.annotations.append(end_decision_ann)
                    
                    # FIX-1: Extract votes with strict termination strategy
                    votes_start_line = end_decision_line + 1
                    votes_lines = []
                    
                    # Find the index of votes_start_line in lines list
                    votes_start_idx = -1
                    for i, (line_num, text) in enumerate(lines):
                        if line_num >= votes_start_line:
                            votes_start_idx = i
                            break
                    
                    if votes_start_idx >= 0:
                        # Collect votes with strict termination conditions
                        consecutive_blank_lines = 0
                        non_blank_votes_count = 0
                        max_non_blank_lines = self.config.votes_max_non_blank_lines
                        in_votes_section = False
                        votes_end_idx = votes_start_idx
                        separate_opinion_idx = None  # Track where RE_SEPARATE_OPINION was found

                        for i in range(votes_start_idx, len(lines)):
                            line_num, text = lines[i]
                            
                            # Stop conditions (in order of priority):
                            # 1. RE_SEPARATE_OPINION (existing check)
                            if self.config.re_separate_opinion.match(text):
                                separate_opinion_idx = i
                                break
                            
                            # 2. RE_DIVISION or RE_CASE_BRACKET (next case start)
                            if self.config.re_division.match(text) or self.config.re_case_bracket.match(text):
                                break
                            
                            # 3. Two consecutive blank lines (double blank = section break)
                            if not text.strip():
                                consecutive_blank_lines += 1
                                if consecutive_blank_lines >= 2 and in_votes_section:
                                    # ERA-2: look ahead past blank gap for more justice names
                                    if self.config.votes_continuation_lookahead > 0:
                                        found_more = False
                                        justices_la = _get_known_justices()
                                        for look_i in range(i + 1, min(i + 1 + self.config.votes_continuation_lookahead, len(lines))):
                                            look_text = lines[look_i][1]
                                            if look_text.strip() and _line_has_justice_surname(look_text, justices_la):
                                                found_more = True
                                                break
                                        if found_more:
                                            consecutive_blank_lines = 0
                                            continue
                                    # Go back to last non-blank line
                                    while votes_end_idx > votes_start_idx and not lines[votes_end_idx-1][1].strip():
                                        votes_end_idx -= 1
                                    break
                            else:
                                consecutive_blank_lines = 0
                                
                                # 4. Maximum 15 non-blank lines
                                non_blank_votes_count += 1
                                if non_blank_votes_count > max_non_blank_lines:
                                    break
                                
                                # FIX-234-2: Check if this line contains a justice surname (loose)
                                justices = _get_known_justices()
                                has_justice = _line_has_justice_surname(text, justices)
                                
                                # Check if this line looks like a votes line (existing regex)
                                is_votes_line = self.config.re_votes_content.search(text) is not None
                                
                                # Skip footnote lines
                                if self.config.re_footnote_start.match(text):
                                    if in_votes_section:
                                        if not has_justice:
                                            # ERA-2: look ahead past footnotes for more justice names
                                            if self.config.votes_continuation_lookahead > 0:
                                                found_more = False
                                                justices_la = _get_known_justices()
                                                for look_i in range(i + 1, min(i + 1 + self.config.votes_continuation_lookahead, len(lines))):
                                                    look_text = lines[look_i][1]
                                                    if look_text.strip() and _line_has_justice_surname(look_text, justices_la):
                                                        found_more = True
                                                        break
                                                if found_more:
                                                    continue  # skip footnote, more votes ahead
                                            break
                                        # Has justice surname despite footnote-like start - keep
                                    else:
                                        continue
                                
                                # Determine if line belongs in votes
                                if has_justice:
                                    # Has justice surname - definitely votes
                                    in_votes_section = True
                                    votes_lines.append((line_num, text))
                                    votes_end_idx = i + 1
                                elif is_votes_line:
                                    # Looks like votes line but no justice surname
                                    if len(text.strip()) < 50:
                                        # Short line that looks like votes - include cautiously
                                        in_votes_section = True
                                        votes_lines.append((line_num, text))
                                        votes_end_idx = i + 1
                                    else:
                                        # Long line that looks like votes but no justice surname
                                        # Could be false positive (e.g., "Billedo" in footnote)
                                        if in_votes_section:
                                            # Already in votes section, this might be the end
                                            break
                                        # Not yet in votes section, skip
                                        pass
                                elif in_votes_section:
                                    # In votes but no justice surname and no votes keyword
                                    if len(text.strip()) < 50:
                                        # Short line - include cautiously
                                        votes_lines.append((line_num, text))
                                        votes_end_idx = i + 1
                                    else:
                                        # Long line without justice reference = not votes
                                        break
                                else:
                                    # Not yet in votes section, skip leading non-votes lines
                                    pass
                        
                        # Remove trailing blank lines from votes_lines
                        while votes_lines and not votes_lines[-1][1].strip():
                            votes_lines.pop()

                        # ERA-2: extend votes past case boundary if incomplete
                        if self.config.votes_extend_past_boundary and votes_lines:
                            votes_lines = self._try_extend_votes_past_boundary(
                                votes_lines, boundary)

                        # Create votes annotation if we found any votes lines
                        if votes_lines:
                            start_line_num = votes_lines[0][0]
                            end_line_num = votes_lines[-1][0]
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
                        
                        # Check for separate opinions — find ALL, not just the first
                        RE_SEP_OPINION_HEADER = re.compile(r'^SEPARATE\s+OPINION\s*$', re.IGNORECASE)

                        opinion_scan_start = separate_opinion_idx if separate_opinion_idx is not None else votes_end_idx
                        if opinion_scan_start is None or opinion_scan_start >= len(lines):
                            opinion_scan_start = votes_end_idx if votes_end_idx > votes_start_idx else votes_start_idx

                        # Collect all opinion start indices
                        # Note: do NOT terminate at re_case_bracket — case citations
                        # like "[G.R. No. 12345. Jan 1, 2000]" are common in opinion bodies
                        # and would cause early termination (e.g. Estrada case, Vol 421).
                        opinion_starts = []
                        for scan_idx in range(opinion_scan_start, len(lines)):
                            scan_line_num, scan_text = lines[scan_idx]
                            if self.config.re_division.match(scan_text):
                                break
                            if self.config.re_separate_opinion.match(scan_text) or RE_SEP_OPINION_HEADER.match(scan_text):
                                opinion_starts.append(scan_idx)

                        # Deduplicate: header + attribution within 3 lines = keep header only
                        deduped_starts = []
                        skip_next = set()
                        for i, idx in enumerate(opinion_starts):
                            if idx in skip_next:
                                continue
                            deduped_starts.append(idx)
                            if RE_SEP_OPINION_HEADER.match(lines[idx][1]):
                                for j in range(i + 1, len(opinion_starts)):
                                    if opinion_starts[j] - idx <= 3:
                                        skip_next.add(opinion_starts[j])
                                    else:
                                        break
                        opinion_starts = deduped_starts

                        if opinion_starts:
                            for op_i, op_start_idx in enumerate(opinion_starts):
                                op_start_line, op_start_text = lines[op_start_idx]

                                start_opinion_ann = self._make_annotation(
                                    label="start_opinion",
                                    text=op_start_text.strip(),
                                    start_line=op_start_line,
                                    end_line=op_start_line,
                                    group=None
                                )
                                extracted_case.annotations.append(start_opinion_ann)

                                # end_opinion = last non-blank before next opinion or end of case
                                if op_i + 1 < len(opinion_starts):
                                    end_search_limit = opinion_starts[op_i + 1]
                                else:
                                    end_search_limit = len(lines)

                                last_nonblank_line = op_start_line
                                last_nonblank_text = op_start_text
                                for search_idx in range(op_start_idx + 1, end_search_limit):
                                    s_line, s_text = lines[search_idx]
                                    if self.config.re_division.match(s_text):
                                        break
                                    if s_text.strip():
                                        last_nonblank_line = s_line
                                        last_nonblank_text = s_text

                                end_opinion_ann = self._make_annotation(
                                    label="end_opinion",
                                    text=last_nonblank_text.strip(),
                                    start_line=last_nonblank_line,
                                    end_line=last_nonblank_line,
                                    group=None
                                )
                                extracted_case.annotations.append(end_opinion_ann)

                            # end_of_case = end_opinion of the last opinion
                            end_of_case_ann = self._make_annotation(
                                label="end_of_case",
                                text=last_nonblank_text.strip(),
                                start_line=last_nonblank_line,
                                end_line=last_nonblank_line,
                                group=None
                            )
                            extracted_case.annotations.append(end_of_case_ann)
                        else:
                            # No separate opinions
                            if votes_lines:
                                last_votes_line_num, last_votes_text = votes_lines[-1]
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

    def _try_extend_votes_past_boundary(self, votes_lines, boundary):
        """Extend votes past case boundary when they wrap around next case header.

        Handles ERA-2 formatting where the votes of one case are split by the
        next case's division header and bracket, e.g. G.R. Nos. 132875-76 in
        Vol 421 where "SECOND DIVISION" and "[G.R. No. 132916...]" appear in
        the middle of the votes block.
        """
        if not votes_lines:
            return votes_lines

        last_text = votes_lines[-1][1].rstrip()
        has_termination = bool(re.search(r'(?:concur|dissent)', last_text, re.IGNORECASE))
        ends_incomplete = last_text.endswith(',') or last_text.lower().rstrip().endswith(' and')

        if has_termination and not ends_incomplete:
            return votes_lines  # votes are already complete

        justices = _get_known_justices()
        max_extension = 15

        for line_num in range(boundary.end_line + 1,
                              min(boundary.end_line + max_extension + 1,
                                  self.loader.total_lines + 1)):
            text = self.loader.get_line_text(line_num)
            if self.preprocessor.is_noise(line_num):
                continue
            if not text.strip():
                continue
            # Skip embedded division headers and brackets from next case
            if self.config.re_division.match(text) or self.config.re_case_bracket.match(text):
                continue
            if _line_has_justice_surname(text, justices):
                votes_lines.append((line_num, text))
                if re.search(r'(?:concur|dissent)', text, re.IGNORECASE):
                    break  # found proper termination
            else:
                break  # non-justice line = end of extension

        return votes_lines

    def _detect_pre_header_parties(self, case, boundary):
        """Fix cases where parties appear before the division/bracket header.

        Pattern (e.g. Estrada vs. Sandiganbayan, Vol 421):
            JOSEPH EJERCITO ESTRADA, pétitioner,  <- pre-header parties
            Estrada vs. Sandiganbayan              <- noise
            EN BANC                                <- division
            [G.R. No. 148560. Nov 19, 2001]        <- bracket
            VS.                                    <- post-bracket parties
            SANDIGANBAYAN..., respondents.          <- parties end
        """
        party_desig = re.compile(
            r'(?:respond.n.s?|p.titioners?|plaintiffs?|defendants?|'
            r'appellants?|appellees?|accused)\s*[.,;]*\s*$',
            re.IGNORECASE
        )

        pre_lines = []
        found_designation = False
        consecutive_blanks = 0

        for line_num in range(boundary.start_line - 1,
                              max(boundary.start_line - 10, 0), -1):
            if line_num < 1:
                break
            text = self.loader.get_line_text(line_num)
            if self.preprocessor.is_noise(line_num):
                continue
            if not text.strip():
                consecutive_blanks += 1
                if consecutive_blanks >= 3 and pre_lines:
                    break  # large gap = definitely past the pre-header
                continue
            consecutive_blanks = 0
            # Stop at previous-case signals
            if self.config.re_so_ordered.match(text):
                break
            if self.config.re_votes_content.search(text) and \
               _line_has_justice_surname(text, _get_known_justices()):
                break
            if party_desig.search(text):
                found_designation = True
            pre_lines.insert(0, (line_num, text))

        if not found_designation or not pre_lines:
            return

        # Extend parties annotation backwards to include pre-header text
        new_start_line = pre_lines[0][0]
        new_start_char = self.loader.line_col_to_char(new_start_line, 0)

        for ann in case.annotations:
            if ann.label == "parties":
                ann.text = self.loader.text[new_start_char:ann.end_char]
                ann.start_line = new_start_line
                ann.start_char = new_start_char
                ann.start_page = self.loader.get_page(new_start_line)
                break

        # Update start_of_case to the pre-header line
        first_text = pre_lines[0][1].strip()
        line_text = self.loader.get_line_text(new_start_line)
        pos = line_text.find(first_text[:20])
        first_start_char = self.loader.line_col_to_char(
            new_start_line, max(pos, 0))

        for ann in case.annotations:
            if ann.label == "start_of_case":
                ann.text = first_text
                ann.start_line = new_start_line
                ann.end_line = new_start_line
                ann.start_char = first_start_char
                ann.end_char = first_start_char + len(first_text)
                ann.start_page = self.loader.get_page(new_start_line)
                ann.end_page = ann.start_page
                break

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
        
        # Get page numbers - FIX-6: Convert char offset to line number first
        start_page = self.loader.get_page(self.loader.char_to_line(start_char))
        end_page = self.loader.get_page(self.loader.char_to_line(end_char - 1))  # exclusive end
        
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