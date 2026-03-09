import re
from pathlib import Path
from typing import Tuple, List, Dict, Optional
import bisect

# Regex for page markers in the text
RE_PAGE_MARKER = re.compile(r'^--- Page (\d+) ---$')


class VolumeLoader:
    """Loads a volume text file and provides coordinate conversion utilities."""

    def __init__(self):
        self.text: str = ""                     # full file text (newlines normalized to \n)
        self.lines: List[str] = []              # lines split by \n (0-indexed internally)
        self.line_starts: List[int] = []        # line_starts[i] = char offset of start of line i (0-indexed)
        self.page_break_lines: List[int] = []   # sorted list of 0-indexed line numbers with page markers
        self.page_break_pages: List[int] = []   # corresponding page numbers (parallel to page_break_lines)
        self.total_lines: int = 0
        self.filename: str = ""

    def load(self, path: Path) -> str:
        """Load a volume file. Returns the full text.

        Steps:
        1. Read file as UTF-8
        2. Normalize line endings: replace \r\n and \r with \n
        3. Split into lines
        4. Build line_starts: for each line i, line_starts[i] = sum of (len(line) + 1) for all preceding lines
           (the +1 accounts for the \n character)
        5. Scan for page markers: lines matching RE_PAGE_MARKER
           Store as two parallel sorted lists: page_break_lines and page_break_pages
        6. Set self.text, self.lines, self.total_lines, self.filename
        7. Return self.text
        """
        # Read file as UTF-8
        with open(path, 'r', encoding='utf-8') as f:
            raw_text = f.read()
        
        # Normalize line endings
        self.text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Remove trailing newline if present to match wc -l behavior
        if self.text.endswith('\n'):
            self.text = self.text[:-1]
        
        # Split into lines
        self.lines = self.text.split('\n')
        self.total_lines = len(self.lines)
        self.filename = path.name
        
        # Build line_starts
        self.line_starts = []
        current_pos = 0
        for line in self.lines:
            self.line_starts.append(current_pos)
            current_pos += len(line) + 1  # +1 for the newline character
        
        # Scan for page markers
        self.page_break_lines = []
        self.page_break_pages = []
        for i, line in enumerate(self.lines):
            match = RE_PAGE_MARKER.match(line)
            if match:
                page_num = int(match.group(1))
                self.page_break_lines.append(i)
                self.page_break_pages.append(page_num)
        
        return self.text

    def char_to_line(self, char_offset: int) -> int:
        """Convert a 0-based character offset to a 1-based line number.
        Use bisect_right on self.line_starts to find the line.
        bisect_right returns the insertion point; the line is (insertion_point - 1).
        Return value is 1-based (add 1 to 0-based index).
        """
        if not self.line_starts:
            return 1
        
        # Find the insertion point
        idx = bisect.bisect_right(self.line_starts, char_offset) - 1
        
        # Clamp to valid range
        idx = max(0, min(idx, len(self.line_starts) - 1))
        
        # Convert to 1-based
        return idx + 1

    def line_col_to_char(self, line: int, col: int) -> int:
        """Convert 1-based line number + 0-based column to 0-based char offset.
        Formula: self.line_starts[line - 1] + col
        """
        if line < 1 or line > len(self.line_starts):
            raise ValueError(f"Line {line} out of range (1-{len(self.line_starts)})")
        
        line_idx = line - 1
        line_start = self.line_starts[line_idx]
        line_length = len(self.lines[line_idx])
        
        # Clamp column to line length
        col = max(0, min(col, line_length))
        
        return line_start + col

    def tk_index_to_char(self, tk_index: str) -> int:
        """Convert Tkinter index string "line.col" to char offset.
        Parse the string, then call line_col_to_char.
        Tkinter lines are 1-based, columns are 0-based.
        Special case: "line.end" means end of line.
        """
        try:
            line_str, col_str = tk_index.split('.')
            line = int(line_str)
            
            if col_str == "end":
                # Get the length of the line
                if line < 1 or line > len(self.lines):
                    raise ValueError(f"Line {line} out of range")
                line_idx = line - 1
                return self.line_starts[line_idx] + len(self.lines[line_idx])
            else:
                col = int(col_str)
                return self.line_col_to_char(line, col)
        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid Tkinter index: {tk_index}") from e

    def char_to_tk_index(self, char_offset: int) -> str:
        """Convert char offset to Tkinter index string "line.col".
        line = char_to_line(char_offset) (1-based)
        col = char_offset - line_starts[line - 1]
        Return f"{line}.{col}"
        """
        line = self.char_to_line(char_offset)
        line_idx = line - 1
        
        if line_idx < 0 or line_idx >= len(self.line_starts):
            return "1.0"
        
        line_start = self.line_starts[line_idx]
        col = char_offset - line_start
        
        # Clamp column to line length
        line_length = len(self.lines[line_idx])
        col = max(0, min(col, line_length))
        
        return f"{line}.{col}"

    def get_page(self, line: int) -> int:
        """Get the page number for a 1-based line number.
        Convert to 0-based. Use bisect_right on page_break_lines
        to find the nearest preceding page marker.
        If no page marker precedes this line, return 0.
        """
        if line < 1 or not self.page_break_lines:
            return 0
        
        line_idx = line - 1
        
        # Find the rightmost page marker at or before this line
        idx = bisect.bisect_right(self.page_break_lines, line_idx) - 1
        
        if idx >= 0:
            return self.page_break_pages[idx]
        else:
            return 0

    def get_line_text(self, line: int) -> str:
        """Get the text of a 1-based line number. Returns empty string if out of range."""
        idx = line - 1
        if 0 <= idx < len(self.lines):
            return self.lines[idx]
        return ""


if __name__ == "__main__":
    """Test block that loads a sample volume and prints diagnostics."""
    import sys
    from pathlib import Path
    
    # Get the path to samples directory
    samples_dir = Path(__file__).parent.parent / "samples"
    volume_path = samples_dir / "Volume_960.txt"
    
    if not volume_path.exists():
        print(f"Error: {volume_path} not found")
        sys.exit(1)
    
    # Load the volume
    loader = VolumeLoader()
    try:
        text = loader.load(volume_path)
        print(f"Loaded: {volume_path.name}")
        print(f"Total lines: {loader.total_lines:,}")
        print(f"Total pages: {len(loader.page_break_lines)}")
        print(f"First page marker: line {loader.page_break_lines[0] + 1 if loader.page_break_lines else 'none'}")
        print(f"Last page marker: line {loader.page_break_lines[-1] + 1 if loader.page_break_lines else 'none'}")
        print()
        
        # Test basic properties
        print("Basic tests:")
        print(f"  line_starts[0] == 0: {loader.line_starts[0] == 0}")
        print(f"  char_to_line(0) == 1: {loader.char_to_line(0) == 1}")
        
        # Test round-trip for first few lines
        print("\nRound-trip tests (char ↔ line):")
        for line in [1, 10, 100, 1000]:
            char_offset = loader.line_starts[line - 1]
            computed_line = loader.char_to_line(char_offset)
            print(f"  Line {line}: char_offset={char_offset}, char_to_line({char_offset})={computed_line} {'✓' if computed_line == line else '✗'}")
        
        # Test Tkinter index conversion
        print("\nTkinter index tests:")
        tk_index = "1.0"
        char_offset = loader.tk_index_to_char(tk_index)
        tk_index_back = loader.char_to_tk_index(char_offset)
        print(f"  tk_index_to_char('{tk_index}') = {char_offset}")
        print(f"  char_to_tk_index({char_offset}) = '{tk_index_back}' {'✓' if tk_index == tk_index_back else '✗'}")
        
        # Test page number lookup
        print("\nPage number tests:")
        test_lines = [1, 326, 1000]
        for line in test_lines:
            page = loader.get_page(line)
            print(f"  Line {line}: page {page}")
        
        # Test specific acceptance criteria
        print("\nAcceptance criteria tests:")
        print(f"  get_page(326) == 16: {loader.get_page(326) == 16}")
        print(f"  get_page(1) == 1: {loader.get_page(1) == 1}")
        
        # Test line 322 should be page 16 marker
        if 322 <= loader.total_lines:
            line_322_text = loader.get_line_text(322)
            print(f"\nLine 322 text: {repr(line_322_text[:50])}...")
        
    except Exception as e:
        print(f"Error loading volume: {e}")
        import traceback
        traceback.print_exc()