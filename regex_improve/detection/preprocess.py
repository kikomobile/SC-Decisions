import re
import sys
from pathlib import Path
from typing import Optional

# Add regex_improve/ to path so gui.volume_loader is importable
_REGEX_IMPROVE_DIR = Path(__file__).resolve().parent.parent
if str(_REGEX_IMPROVE_DIR) not in sys.path:
    sys.path.insert(0, str(_REGEX_IMPROVE_DIR))

from gui.volume_loader import VolumeLoader

# Module-level regex constants
RE_PAGE_MARKER = re.compile(r'^--- Page \d+ ---$')
RE_VOLUME_HEADER = re.compile(r'^VOL[.,]\s*\d+.*\d+\s*$')
RE_PHILIPPINE_REPORTS = re.compile(r'^\d+\s+PHILIPPINE REPORTS\s*$')
RE_SHORT_TITLE = re.compile(
    r'^[A-Z][A-Za-z\s,.\'\"\-\u2018\u2019\u201c\u201d]+'
    r'(?:v|y|V|Y)s?\.'
    r'[A-Za-z\s,.\'\"\-\u2018\u2019\u201c\u201d]+$'
)
# Division header regex (used to prevent marking division headers as noise)
RE_DIVISION = re.compile(
    r'^(EN\s*BAN\s*C|(?:FIRST|SECOND|THIRD)\s+DIVIS[ILO]*[ILO]+N)\s*$',
    re.IGNORECASE
)
RE_SYLLABUS_HEADER = re.compile(r'^SY[IL]?LABUS\s*$', re.IGNORECASE)


class VolumePreprocessor:
    """Preprocesses volume text to classify noise lines without modifying the text."""

    def __init__(self):
        self.loader: VolumeLoader = VolumeLoader()
        self.noise_mask: list[bool] = []
        self.volume_name: str = ""

    def load(self, path: Path) -> str:
        """Load volume via self.loader.load(path), set self.volume_name = path.name,
        call self._classify_noise(), return the full unmodified text.
        """
        text = self.loader.load(path)
        self.volume_name = path.name
        self._classify_noise()
        return text

    def _classify_noise(self) -> None:
        """Build self.noise_mask (same length as self.loader.lines).
        
        A line is noise if:
        - Pass 1 (definite noise): Matches RE_PAGE_MARKER, RE_VOLUME_HEADER, or RE_PHILIPPINE_REPORTS.
        - Pass 2 (contextual noise): Matches RE_SHORT_TITLE AND the previous non-blank line 
          (scanning backward) was already marked as noise in pass 1.
        - Pass 3 (sandwiched blanks): A blank line is noise if both the nearest preceding 
          non-blank line AND the nearest following non-blank line are already marked as noise.
        """
        lines = self.loader.lines
        total_lines = len(lines)
        
        # Initialize noise_mask with False
        self.noise_mask = [False] * total_lines
        
        # Pass 1: definite noise
        for i, line in enumerate(lines):
            if (RE_PAGE_MARKER.match(line) or 
                RE_VOLUME_HEADER.match(line) or 
                RE_PHILIPPINE_REPORTS.match(line)):
                self.noise_mask[i] = True
        
        # Pass 2: contextual noise (short titles)
        for i, line in enumerate(lines):
            # Skip division headers and syllabus headers - they're not noise even if they match RE_SHORT_TITLE
            if RE_DIVISION.match(line) or RE_SYLLABUS_HEADER.match(line):
                continue
                
            if RE_SHORT_TITLE.match(line):
                # Find previous non-blank line
                prev_idx = i - 1
                while prev_idx >= 0 and lines[prev_idx].strip() == "":
                    prev_idx -= 1
                
                # If previous non-blank line is noise (from pass 1), mark this as noise
                if prev_idx >= 0 and self.noise_mask[prev_idx]:
                    self.noise_mask[i] = True
        
        # Pass 3: sandwiched blank lines
        for i, line in enumerate(lines):
            if line.strip() == "" and not self.noise_mask[i]:
                # Find nearest preceding non-blank line
                prev_idx = i - 1
                while prev_idx >= 0 and lines[prev_idx].strip() == "":
                    prev_idx -= 1
                
                # Find nearest following non-blank line
                next_idx = i + 1
                while next_idx < total_lines and lines[next_idx].strip() == "":
                    next_idx += 1
                
                # Check if both neighbors are noise
                if (prev_idx >= 0 and self.noise_mask[prev_idx] and
                    next_idx < total_lines and self.noise_mask[next_idx]):
                    self.noise_mask[i] = True

    def is_noise(self, line_1based: int) -> bool:
        """Check if a 1-based line number is noise."""
        if line_1based < 1 or line_1based > len(self.noise_mask):
            return False
        return self.noise_mask[line_1based - 1]

    def get_content_lines(self, start_line: int, end_line: int) -> list[tuple[int, str]]:
        """Return non-noise lines in range [start_line, end_line] (1-based inclusive)
        as (line_number, text) tuples.
        """
        result = []
        for line_num in range(start_line, end_line + 1):
            if line_num < 1 or line_num > len(self.noise_mask):
                continue
            if not self.noise_mask[line_num - 1]:
                text = self.loader.lines[line_num - 1]
                result.append((line_num, text))
        return result


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
    text = preprocessor.load(volume_path)
    
    # Print statistics
    total_lines = len(preprocessor.loader.lines)
    noise_count = sum(preprocessor.noise_mask)
    content_count = total_lines - noise_count
    
    print(f"Loaded: {preprocessor.volume_name}")
    print(f"Total lines: {total_lines:,}")
    print(f"Noise lines: {noise_count:,}")
    print(f"Content lines: {content_count:,}")
    print()
    
    # Print first 20 noise lines with their line numbers
    print("First 20 noise lines:")
    count = 0
    for i, is_noise in enumerate(preprocessor.noise_mask):
        if is_noise:
            line_num = i + 1
            line_text = preprocessor.loader.lines[i]
            print(f"  {line_num:6d}: {repr(line_text[:80])}")
            count += 1
            if count >= 20:
                break
    print()
    
    # Assertions
    print("Running assertions...")
    
    # Assert: line 1 (`--- Page 1 ---`) IS noise
    assert preprocessor.is_noise(1), f"Line 1 should be noise: {preprocessor.loader.lines[0]}"
    print("Line 1 is noise")
    
    # Assert: line 421 (`SECOND DIVISION`) is NOT noise
    assert not preprocessor.is_noise(421), f"Line 421 should NOT be noise: {preprocessor.loader.lines[420]}"
    print("Line 421 is not noise")
    
    # Assert: line 453 (`--- Page 19 ---`) IS noise
    assert preprocessor.is_noise(453), f"Line 453 should be noise: {preprocessor.loader.lines[452]}"
    print("Line 453 is noise")
    
    # Assert: line 454 (`2 PHILIPPINE REPORTS`) IS noise
    assert preprocessor.is_noise(454), f"Line 454 should be noise: {preprocessor.loader.lines[453]}"
    print("Line 454 is noise")
    
    # Assert: line 456 (`Milano vs. Employees' Compensation Commission`) IS noise
    assert preprocessor.is_noise(456), f"Line 456 should be noise: {preprocessor.loader.lines[455]}"
    print("Line 456 is noise")
    
    print("\nAll tests passed!")