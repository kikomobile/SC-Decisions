import re
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Add regex_improve/ to path so we can import from detection.preprocess
_REGEX_IMPROVE_DIR = Path(__file__).resolve().parent.parent
if str(_REGEX_IMPROVE_DIR) not in sys.path:
    sys.path.insert(0, str(_REGEX_IMPROVE_DIR))

from detection.preprocess import VolumePreprocessor


# Module-level regex constants
# More flexible division regex to handle OCR errors
# Allow: EN BANC, ENBANC, EN BAN C, etc.
# Allow: FIRST DIVISION, FIRST DIVISLON, FIRST DIVISIION, etc.
RE_DIVISION = re.compile(
    r'^(EN\s*BAN\s*C|(?:FIRST|SECOND|THIRD)\s+DIVIS[ILO]*[ILO]+N)\s*$',
    re.IGNORECASE
)

# RE_CASE_BRACKET must match all variants listed in TASKS.md
# Pattern: opening bracket [({, then case type prefix, then case number, 
# then separator, then date, then closing bracket ])}
# Handle OCR errors: comma for period in "No," and weird bracket patterns
# Handle nested brackets like {Adm. Matter Nos. ...]. May 30, 1986]
# Use greedy date match to capture everything up to the last closing bracket
# Allow trailing characters after closing bracket (OCR errors like underscore)
RE_CASE_BRACKET = re.compile(
    r'^[\[\(\{]'
    r'(?:G\.\s*R\.\s*No[\.\s,]*s?[\.\s,]*|A\.\s*M\.\s*No[\.\s,]*s?[\.\s,]*|Adm\.\s*(?:Matter|Case)\s*No[\.\s,]*s?[\.\s,]*)'
    r'\s*([\w\-/&\s\.]+?)'  # case number (non-greedy)
    r'[\.\s,]+'             # separator between case number and date
    r'(.+)'                 # date text (greedy match - everything up to closing bracket)
    r'[\]\)\}]'
    r'.*$',  # Allow any characters after closing bracket (OCR errors)
    re.IGNORECASE
)


@dataclass
class CaseNumber:
    text: str                # "G.R. No. 50545" — raw case number with prefix
    full_bracket_text: str   # "[G.R. No. 50545. May 23, 1986]" — full bracket line
    group: int               # 0 for primary, 1+ for consolidated
    start_char: int          # char offset of case number text in volume
    end_char: int            # char offset end


@dataclass
class CaseBoundary:
    start_line: int          # 1-based line of division header
    end_line: int            # 1-based estimated end (before next case start or EOF)
    division_text: str       # "EN BANC", "SECOND DIVISION", etc.
    case_numbers: list[CaseNumber] = field(default_factory=list)
    date_text: str = ""      # raw date from bracket (not parsed)
    date_start_char: int = 0
    date_end_char: int = 0


class CaseBoundaryDetector:
    """Finite-state machine to detect case boundaries in volume text."""
    
    # FSM states
    SEEKING = "SEEKING"
    EXPECTING_BRACKET = "EXPECTING_BRACKET"
    FOUND_BRACKET = "FOUND_BRACKET"
    
    def __init__(self, preprocessor: VolumePreprocessor):
        self.preprocessor = preprocessor
        self.loader = preprocessor.loader
        
    def detect(self) -> list[CaseBoundary]:
        """Detect all case boundaries in the volume."""
        boundaries = []
        state = self.SEEKING
        current_boundary: Optional[CaseBoundary] = None
        bracket_search_limit = 10  # lines to search for bracket after division (increased from 5)
        consolidated_search_limit = 10  # lines to search for second bracket (increased from 3)
        
        # Get all content lines (skip noise)
        total_lines = self.loader.total_lines
        line_idx = 1  # 1-based line index
        
        while line_idx <= total_lines:
            line_text = self.loader.get_line_text(line_idx)
            
            # Check if line is noise
            is_noise = self.preprocessor.is_noise(line_idx)
            
            if state == self.SEEKING:
                # Looking for a division header
                division_match = RE_DIVISION.match(line_text)
                if division_match:
                    # Found division header, start new boundary
                    current_boundary = CaseBoundary(
                        start_line=line_idx,
                        end_line=0,  # will be set later
                        division_text=division_match.group(1).upper()
                    )
                    state = self.EXPECTING_BRACKET
                    bracket_lines_searched = 0
                line_idx += 1
                
            elif state == self.EXPECTING_BRACKET:
                # Found division header, now looking for case bracket
                # Skip noise lines when searching for brackets (brackets are not noise)
                if not is_noise:
                    bracket_match = RE_CASE_BRACKET.match(line_text)
                    if bracket_match:
                        # Found bracket! Extract case number and date
                        case_num_text_raw = bracket_match.group(1).strip()
                        date_text_raw = bracket_match.group(2).strip()
                        
                        # Reconstruct full case number text with prefix
                        # The regex matched the prefix but didn't capture it separately
                        # We need to extract it from the full bracket line
                        full_bracket = line_text.strip()
                        
                        # Find the case number text within the bracket
                        # It starts after the opening bracket and prefix
                        bracket_opener = full_bracket[0]  # '[', '(', or '{'
                        # Find where the case number likely starts (after "G.R. No." etc.)
                        # Simple approach: take everything from opening bracket to date separator
                        case_num_with_prefix = self._extract_case_number_from_bracket(full_bracket, date_text_raw)
                        
                        # Create CaseNumber object
                        case_number = CaseNumber(
                            text=case_num_with_prefix,
                            full_bracket_text=full_bracket,
                            group=0,  # primary case
                            start_char=self._find_case_number_start_char(line_idx, case_num_with_prefix),
                            end_char=self._find_case_number_end_char(line_idx, case_num_with_prefix)
                        )
                        
                        # Extract date position
                        date_start_char, date_end_char = self._find_date_in_bracket(
                            line_idx, full_bracket, date_text_raw
                        )
                        
                        current_boundary.case_numbers.append(case_number)
                        current_boundary.date_text = date_text_raw
                        current_boundary.date_start_char = date_start_char
                        current_boundary.date_end_char = date_end_char
                        
                        state = self.FOUND_BRACKET
                        consolidated_lines_searched = 0
                        line_idx += 1
                        continue
                
                # If we get here, either line is noise or not a bracket
                if bracket_lines_searched >= bracket_search_limit:
                    # Didn't find bracket within limit, revert to SEEKING
                    state = self.SEEKING
                    current_boundary = None
                else:
                    bracket_lines_searched += 1
                    
                line_idx += 1
                
            elif state == self.FOUND_BRACKET:
                # Found first bracket, check for consolidated case
                if line_text.strip() == "":
                    # Skip blank lines
                    line_idx += 1
                    consolidated_lines_searched += 1
                    continue
                
                # Skip noise lines when searching for consolidated brackets
                if is_noise:
                    line_idx += 1
                    consolidated_lines_searched += 1
                    continue
                
                # Check if this line is a bracket
                bracket_match = RE_CASE_BRACKET.match(line_text)
                if bracket_match and consolidated_lines_searched < consolidated_search_limit:
                    # Found second bracket (consolidated case)
                    case_num_text_raw = bracket_match.group(1).strip()
                    date_text_raw = bracket_match.group(2).strip()
                    full_bracket = line_text.strip()
                    
                    case_num_with_prefix = self._extract_case_number_from_bracket(full_bracket, date_text_raw)
                    
                    case_number = CaseNumber(
                        text=case_num_with_prefix,
                        full_bracket_text=full_bracket,
                        group=1,  # consolidated case
                        start_char=self._find_case_number_start_char(line_idx, case_num_with_prefix),
                        end_char=self._find_case_number_end_char(line_idx, case_num_with_prefix)
                    )
                    
                    current_boundary.case_numbers.append(case_number)
                    # Note: date_text already set from first bracket
                    line_idx += 1
                    consolidated_lines_searched += 1
                    continue
                
                # If we get here, line is not a bracket (but not blank or noise either)
                # Continue searching for brackets up to the limit
                if consolidated_lines_searched >= consolidated_search_limit:
                    # Reached limit, finish this boundary
                    boundaries.append(current_boundary)
                    state = self.SEEKING
                    current_boundary = None
                    # Don't increment line_idx here - let the next iteration process this line
                else:
                    # Haven't reached limit yet, continue searching
                    line_idx += 1
                    consolidated_lines_searched += 1
        
        # Set end lines for all boundaries
        for i in range(len(boundaries)):
            if i < len(boundaries) - 1:
                boundaries[i].end_line = boundaries[i + 1].start_line - 1
            else:
                boundaries[i].end_line = total_lines
        
        return boundaries
    
    def _extract_case_number_from_bracket(self, bracket_line: str, date_text: str) -> str:
        """Extract the full case number text (with prefix) from bracket line."""
        # Find the position of the date in the bracket line
        date_pos = bracket_line.find(date_text)
        if date_pos == -1:
            # Fallback: take everything from opening bracket to last period before date-ish text
            # Look for patterns like ". May" or ", May"
            date_pattern = r'[\.\s,]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
            match = re.search(date_pattern, bracket_line, re.IGNORECASE)
            if match:
                date_pos = match.start()
            else:
                # Last resort: take everything up to closing bracket
                date_pos = len(bracket_line) - 1
        
        # Extract case number part (from after opening bracket to before date)
        case_part = bracket_line[1:date_pos].strip()  # Skip opening bracket
        # Remove trailing separator characters
        case_part = case_part.rstrip('., ')
        return case_part
    
    def _find_case_number_start_char(self, line_num: int, case_number_text: str) -> int:
        """Find the start character offset of case number text in the volume."""
        line_text = self.loader.get_line_text(line_num)
        # Find the position of case_number_text within the line
        pos = line_text.find(case_number_text)
        if pos == -1:
            # Fallback: use the line start (after opening bracket)
            pos = 1  # Skip opening bracket
        return self.loader.line_col_to_char(line_num, pos)
    
    def _find_case_number_end_char(self, line_num: int, case_number_text: str) -> int:
        """Find the end character offset of case number text in the volume."""
        start_char = self._find_case_number_start_char(line_num, case_number_text)
        return start_char + len(case_number_text)
    
    def _find_date_in_bracket(self, line_num: int, bracket_line: str, date_text: str) -> tuple[int, int]:
        """Find the start and end character offsets of date text in bracket line."""
        line_text = self.loader.get_line_text(line_num)
        pos = line_text.find(date_text)
        if pos == -1:
            # Try to find date by looking for month names
            month_pattern = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}'
            match = re.search(month_pattern, line_text, re.IGNORECASE)
            if match:
                date_text = match.group()
                pos = match.start()
            else:
                # Last resort: approximate position
                # Date is usually at the end before closing bracket
                closing_bracket_pos = max(line_text.rfind(']'), line_text.rfind(')'), line_text.rfind('}'))
                if closing_bracket_pos > 0:
                    # Assume date is last 20 characters before closing bracket
                    pos = max(0, closing_bracket_pos - 20)
                    date_text = line_text[pos:closing_bracket_pos].strip()
                else:
                    pos = len(line_text) - 20
                    date_text = line_text[pos:].strip()
        
        start_char = self.loader.line_col_to_char(line_num, pos)
        end_char = start_char + len(date_text)
        return start_char, end_char


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
    detector = CaseBoundaryDetector(preprocessor)
    boundaries = detector.detect()
    
    # Print results
    print(f"Total boundaries found: {len(boundaries)}")
    print()
    
    print("First 5 boundaries:")
    for i, boundary in enumerate(boundaries[:5]):
        case_nums = [cn.text for cn in boundary.case_numbers]
        print(f"  {i}: line {boundary.start_line}, division={boundary.division_text}, "
              f"case_numbers={case_nums}, date={boundary.date_text}")
    print()
    
    # Find and print consolidated case boundaries
    consolidated = [b for b in boundaries if len(b.case_numbers) > 1]
    print(f"Consolidated case boundaries: {len(consolidated)}")
    for i, boundary in enumerate(consolidated[:3]):  # Show first 3
        case_nums = [cn.text for cn in boundary.case_numbers]
        print(f"  Line {boundary.start_line}: {case_nums}")
    print()
    
    # Assertions
    print("Running assertions...")
    
    # Assert: 72 boundaries found
    assert len(boundaries) == 72, f"Expected 72 boundaries, found {len(boundaries)}"
    print("[OK] 72 boundaries found")
    
    # Assert: first boundary at line 421 with case_number text containing "50545"
    first_boundary = boundaries[0]
    assert first_boundary.start_line == 421, f"First boundary at line {first_boundary.start_line}, expected 421"
    assert any("50545" in cn.text for cn in first_boundary.case_numbers), \
        f"Case number 50545 not found in first boundary: {[cn.text for cn in first_boundary.case_numbers]}"
    print("[OK] First boundary at line 421 with case_number containing '50545'")
    
    # Assert: boundary near line 18707 has 2 case_numbers (consolidated)
    # Find boundary with start_line closest to 18707
    target_boundary = None
    for boundary in boundaries:
        if abs(boundary.start_line - 18707) <= 100:  # Within 100 lines
            target_boundary = boundary
            break
    
    assert target_boundary is not None, "No boundary found near line 18707"
    assert len(target_boundary.case_numbers) >= 2, \
        f"Expected at least 2 case_numbers near line 18707, found {len(target_boundary.case_numbers)}"
    print(f"[OK] Boundary near line {target_boundary.start_line} has {len(target_boundary.case_numbers)} case_numbers")
    
    # Assert: boundary at line 2902 detects `{Adm. Matter...}` bracket
    # Find boundary around line 2902
    adm_boundary = None
    for boundary in boundaries:
        if 2800 <= boundary.start_line <= 3000:
            adm_boundary = boundary
            break
    
    assert adm_boundary is not None, "No boundary found around line 2902"
    # Check if any case number contains "Adm. Matter"
    has_adm_matter = any("Adm. Matter" in cn.text or "Adm. Matter" in cn.full_bracket_text 
                         for cn in adm_boundary.case_numbers)
    assert has_adm_matter, f"No Adm. Matter bracket found in boundary at line {adm_boundary.start_line}"
    print(f"[OK] Boundary at line {adm_boundary.start_line} has Adm. Matter bracket")
    
    print("\nAll tests passed!")