# Annotation GUI — Task Board

## How This Works
- **Architect** (Claude Code) writes tasks here with full specs
- **Worker** (Cline/DeepSeek) reads tasks and implements them
- Architect reviews completed tasks and updates status
- Never delete tasks — archive under ## Done / Archived
- Tasks must be completed in order (respect dependencies)

---

## Active Tasks

### T1: Project Scaffolding + Constants + Data Model
**Status:** TODO
**Depends on:** (none)
**Files to create:**
- `regex_improve/annotate_gui.py`
- `regex_improve/gui/__init__.py`
- `regex_improve/gui/constants.py`
- `regex_improve/gui/models.py`

**Description:**
Create the project skeleton, label/color/shortcut definitions, and the full data model for annotations.

#### `regex_improve/annotate_gui.py`
Minimal entry point. Will be extended in T3.
```python
#!/usr/bin/env python3
"""SC Decisions — Case Annotation GUI"""
import sys
import os

# Ensure gui/ package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    # Placeholder until T3 creates app.py
    print("GUI not yet implemented. Waiting for T3.")

if __name__ == "__main__":
    main()
```

#### `regex_improve/gui/__init__.py`
Empty file. Just makes `gui/` a package.

#### `regex_improve/gui/constants.py`
Define a `LabelDef` dataclass and the full `LABELS` list. Also define config constants.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class LabelDef:
    key: str              # internal identifier, e.g. "case_number"
    display_name: str     # human-readable, e.g. "Case Number"
    shortcut_display: str # shown in UI, e.g. "Ctrl+2"
    tk_binding: str       # Tkinter event string, e.g. "<Control-Key-2>"
    color: str            # hex background color for highlights
    selection_type: str   # "cursor" (marks whole line) or "selection" (requires text selection)
    button_text: str      # label on the side panel button, e.g. "[2] Case Number"
```

The full `LABELS` list (define in this exact order):

| key | display_name | shortcut_display | tk_binding | color | selection_type | button_text |
|-----|-------------|-----------------|-----------|-------|---------------|-------------|
| `start_of_case` | Start of Case | Ctrl+1 | `<Control-Key-1>` | `#FFD700` | cursor | `[1] Start Case` |
| `case_number` | Case Number | Ctrl+2 | `<Control-Key-2>` | `#87CEEB` | selection | `[2] Case Number` |
| `date` | Date of Decision | Ctrl+3 | `<Control-Key-3>` | `#98FB98` | selection | `[3] Date` |
| `division` | Division | Ctrl+4 | `<Control-Key-4>` | `#DDA0DD` | selection | `[4] Division` |
| `parties` | Parties | Ctrl+5 | `<Control-Key-5>` | `#F0E68C` | selection | `[5] Parties` |
| `start_syllabus` | Start of Syllabus | Ctrl+6 | `<Control-Key-6>` | `#FFA07A` | cursor | `[6] Start Syllabus` |
| `end_syllabus` | End of Syllabus | Ctrl+7 | `<Control-Key-7>` | `#FFA07A` | cursor | `[7] End Syllabus` |
| `counsel` | Counsel Names | Ctrl+8 | `<Control-Key-8>` | `#B0C4DE` | selection | `[8] Counsel` |
| `ponente` | Ponente Name | Ctrl+9 | `<Control-Key-9>` | `#FFB6C1` | selection | `[9] Ponente` |
| `doc_type` | Document Type | Ctrl+0 | `<Control-Key-0>` | `#E6E6FA` | selection | `[0] Doc Type` |
| `start_decision` | Start of Decision | Ctrl+Shift+D | `<Control-Shift-Key-D>` | `#C8FFC8` | cursor | `[D] Start Decision` |
| `end_decision` | End of Decision | Ctrl+Shift+E | `<Control-Shift-Key-E>` | `#C8FFC8` | cursor | `[E] End Decision` |
| `votes` | Votes | Ctrl+Shift+V | `<Control-Shift-Key-V>` | `#FFDAB9` | selection | `[V] Votes` |
| `start_opinion` | Start of Opinion | Ctrl+Shift+O | `<Control-Shift-Key-O>` | `#D8BFD8` | cursor | `[O] Start Opinion` |
| `end_opinion` | End of Opinion | Ctrl+Shift+P | `<Control-Shift-Key-P>` | `#D8BFD8` | cursor | `[P] End Opinion` |
| `end_of_case` | End of Case | Ctrl+Shift+X | `<Control-Shift-Key-X>` | `#FFD700` | cursor | `[X] End Case` |

Also define these convenience constants:
```python
LABEL_MAP = {label.key: label for label in LABELS}

# Labels that use the group field (all others have group=None)
GROUPED_LABELS = {"case_number", "parties"}

# Annotation file path (relative to cwd, which is regex_improve/)
ANNOTATION_FILE = "annotations.json"
SAMPLES_DIR = "samples"
IMPROVED_REGEX_FILE = "improved_regex.py"
```

#### `regex_improve/gui/models.py`
Define the core data model classes. Use `dataclasses` from stdlib.

```python
from dataclasses import dataclass, field
from typing import Optional, List, Dict
import json
from pathlib import Path

@dataclass
class Annotation:
    """A single annotated span or cursor position."""
    label: str              # key from constants.LABELS, e.g. "case_number"
    text: str               # selected text (for "selection" type) or full line text (for "cursor" type)
    group: Optional[int]    # 0, 1, 2... for case_number/parties; None for all others
    start_char: int         # 0-based character offset from start of file
    end_char: int           # 0-based character offset (exclusive)
    start_line: int         # 1-based line number
    end_line: int           # 1-based line number
    start_page: int         # page number derived from nearest preceding page marker
    end_page: int           # page number

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> 'Annotation': ...

@dataclass
class Case:
    """A single case (possibly consolidated) with its annotations."""
    case_id: str                         # "vol421_case_0"
    annotations: List[Annotation] = field(default_factory=list)
    status: str = "in_progress"          # "in_progress" | "complete" | "exported"
    notes: str = ""

    @property
    def is_consolidated(self) -> bool:
        """True if more than one case_number annotation exists."""
        return len(self.get_annotations_by_label("case_number")) > 1

    def add_annotation(self, annotation: Annotation) -> None:
        """Append annotation to the list."""
        self.annotations.append(annotation)

    def remove_annotation(self, index: int) -> None:
        """Remove annotation at the given index."""
        if 0 <= index < len(self.annotations):
            del self.annotations[index]

    def get_annotations_by_label(self, label: str) -> List[Annotation]:
        """Return all annotations matching the given label key."""
        return [a for a in self.annotations if a.label == label]

    def get_start_line(self) -> Optional[int]:
        """Return line number of the start_of_case annotation, or None."""
        starts = self.get_annotations_by_label("start_of_case")
        return starts[0].start_line if starts else None

    def get_end_line(self) -> Optional[int]:
        """Return line number of the end_of_case annotation, or None."""
        ends = self.get_annotations_by_label("end_of_case")
        return ends[0].start_line if ends else None

    def next_group_index(self) -> int:
        """Return the next available group index (max existing group + 1, or 0)."""
        groups = [a.group for a in self.annotations
                  if a.group is not None]
        return max(groups) + 1 if groups else 0

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> 'Case': ...

@dataclass
class VolumeData:
    """All annotation data for one volume file."""
    volume: str                          # filename, e.g. "Volume_421.txt"
    cases: List[Case] = field(default_factory=list)

    def add_case(self, case: Case) -> None:
        """Append a case, keeping cases sorted by start_line."""
        self.cases.append(case)
        self.cases.sort(key=lambda c: c.get_start_line() or 0)

    def remove_case(self, case_id: str) -> None:
        """Remove a case by its case_id."""
        self.cases = [c for c in self.cases if c.case_id != case_id]

    def get_case_at_line(self, line: int) -> Optional[Case]:
        """Return the case whose start_line <= line <= end_line, or None."""
        for case in self.cases:
            sl = case.get_start_line()
            el = case.get_end_line()
            if sl is not None and sl <= line:
                if el is None or line <= el:
                    return case
        return None

    def get_case_by_id(self, case_id: str) -> Optional[Case]:
        """Return the case with the given ID, or None."""
        for case in self.cases:
            if case.case_id == case_id:
                return case
        return None

    def generate_case_id(self) -> str:
        """Generate the next case_id like 'vol421_case_5'."""
        # Extract volume number from filename
        import re
        m = re.search(r'(\d+)', self.volume)
        vol_num = m.group(1) if m else "0"
        existing = len(self.cases)
        return f"vol{vol_num}_case_{existing}"

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> 'VolumeData': ...

class AnnotationStore:
    """Top-level container: manages all volumes' annotation data."""

    def __init__(self):
        self.volumes: Dict[str, VolumeData] = {}  # filename -> VolumeData

    def get_volume(self, filename: str) -> Optional[VolumeData]:
        """Return VolumeData for the given filename, or None."""
        return self.volumes.get(filename)

    def ensure_volume(self, filename: str) -> VolumeData:
        """Return existing VolumeData or create a new empty one."""
        if filename not in self.volumes:
            self.volumes[filename] = VolumeData(volume=filename)
        return self.volumes[filename]

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict. Structure:
        {
            "format_version": 2,
            "volumes": {
                "Volume_421.txt": { "volume": "...", "cases": [...] },
                ...
            }
        }
        """
        return {
            "format_version": 2,
            "volumes": {
                name: vol.to_dict() for name, vol in self.volumes.items()
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'AnnotationStore':
        """Deserialize from dict. Must handle format_version=2 structure."""
        store = cls()
        volumes_data = data.get("volumes", {})
        for name, vol_dict in volumes_data.items():
            store.volumes[name] = VolumeData.from_dict(vol_dict)
        return store
```

**Important implementation notes for the `to_dict`/`from_dict` methods:**
- `Annotation.to_dict()` returns a plain dict with all fields. `group` should be serialized as `null` (Python `None`) when not applicable.
- `Annotation.from_dict()` must handle missing `group` key gracefully (default to `None`).
- All `to_dict` methods must produce JSON-serializable output (no custom objects).
- All `from_dict` methods are `@classmethod` that return a new instance.

**Acceptance Criteria:**
- [ ] `python -c "from gui.constants import LABELS, LABEL_MAP; print(len(LABELS))"` prints `16` (run from `regex_improve/`)
- [ ] `python -c "from gui.models import Annotation, Case, VolumeData, AnnotationStore; print('OK')"` prints `OK`
- [ ] `Case.is_consolidated` returns `False` for a case with 0-1 case_number annotations, `True` for 2+
- [ ] `Case.next_group_index()` returns 0 for empty case, 1 after adding group=0 annotation, 2 after group=1
- [ ] `AnnotationStore.to_dict()` → `AnnotationStore.from_dict()` round-trips correctly (create store with sample data, serialize, deserialize, compare)
- [ ] `python annotate_gui.py` runs without error (prints placeholder message)

---

### T2: Volume Loader + Page Index Builder
**Status:** TODO
**Depends on:** T1
**Files to create:**
- `regex_improve/gui/volume_loader.py`

**Description:**
Load a `.txt` volume file and build all index structures needed for coordinate conversion between Tkinter positions, character offsets, line numbers, and page numbers.

```python
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
        ...

    def char_to_line(self, char_offset: int) -> int:
        """Convert a 0-based character offset to a 1-based line number.
        Use bisect_right on self.line_starts to find the line.
        bisect_right returns the insertion point; the line is (insertion_point - 1).
        Return value is 1-based (add 1 to 0-based index).
        """
        ...

    def line_col_to_char(self, line: int, col: int) -> int:
        """Convert 1-based line number + 0-based column to 0-based char offset.
        Formula: self.line_starts[line - 1] + col
        """
        ...

    def tk_index_to_char(self, tk_index: str) -> int:
        """Convert Tkinter index string "line.col" to char offset.
        Parse the string, then call line_col_to_char.
        Tkinter lines are 1-based, columns are 0-based.
        """
        ...

    def char_to_tk_index(self, char_offset: int) -> str:
        """Convert char offset to Tkinter index string "line.col".
        line = char_to_line(char_offset) (1-based)
        col = char_offset - line_starts[line - 1]
        Return f"{line}.{col}"
        """
        ...

    def get_page(self, line: int) -> int:
        """Get the page number for a 1-based line number.
        Convert to 0-based. Use bisect_right on page_break_lines
        to find the nearest preceding page marker.
        If no page marker precedes this line, return 0.
        """
        ...

    def get_line_text(self, line: int) -> str:
        """Get the text of a 1-based line number. Returns empty string if out of range."""
        idx = line - 1
        if 0 <= idx < len(self.lines):
            return self.lines[idx]
        return ""
```

**Acceptance Criteria:**
- [ ] Loading `samples/Volume_960.txt` succeeds and `total_lines` equals the `wc -l` count (35186)
- [ ] `line_starts[0]` == 0 (first line starts at char 0)
- [ ] `char_to_line(0)` returns 1 (first char is on line 1)
- [ ] For any line L, `char_to_line(line_starts[L-1])` == L (round-trip)
- [ ] `tk_index_to_char("1.0")` returns 0
- [ ] `char_to_tk_index(0)` returns `"1.0"`
- [ ] `get_page(326)` for Volume_960 returns 16 (line 326 is after `--- Page 16 ---` at line 322)
- [ ] `get_page(1)` returns 1 (line 1 is after `--- Page 1 ---` at line 1, or the marker IS line 1)
- [ ] Page markers are correctly detected despite surrounding content
- [ ] Write a `if __name__ == "__main__"` test block that loads a sample volume and prints: total lines, total pages, a few char↔line round-trip checks

---

### T3: Main Window Skeleton + Menu Bar
**Status:** TODO
**Depends on:** T1
**Files to create:**
- `regex_improve/gui/app.py`
**Files to modify:**
- `regex_improve/annotate_gui.py` (update to import and launch `AnnotationApp`)

**Description:**
Create the main application window with menu bar, three-panel layout (main text area + right panel + status bar), and file open dialog. The text panels will be placeholder frames filled in by later tasks.

```python
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from gui.constants import SAMPLES_DIR, ANNOTATION_FILE

class AnnotationApp:
    """Main application class. Creates the Tk root and orchestrates all components."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SC Decisions — Case Annotation Tool")
        self.root.geometry("1400x800")
        self.root.minsize(900, 600)

        # State
        self.current_file: Optional[Path] = None  # currently loaded volume path

        # Build UI
        self._create_menu_bar()
        self._create_layout()

    def _create_menu_bar(self):
        """Create the menu bar with File, Annotate, Export, Test, Help menus.

        File menu:
          - Open Volume... (Ctrl+O) — opens file picker filtered to *.txt in SAMPLES_DIR
          - Save (Ctrl+S) — saves annotations (wired in T10)
          - Separator
          - Exit

        Annotate menu:
          - (placeholder items — wired in T9)
          - Mark Start of Case (Ctrl+1)
          - ... (one entry per label from LABELS)
          - Delete Selected Annotation (Delete key)

        Export menu:
          - Export as JSON
          - Export as Markdown

        Test menu:
          - Run Evaluation → Regex

        Help menu:
          - Keyboard Shortcuts — shows a dialog listing all shortcuts
          - About
        """
        ...

    def _create_layout(self):
        """Create the three-panel layout using a PanedWindow.

        Layout:
        ┌────────────────────────────────┬───────────────────┐
        │   main_frame (expandable)      │ right_frame       │
        │   (will hold TextPanel in T4)  │ (fixed ~300px)    │
        │                                │ (SidePanel in T7) │
        ├────────────────────────────────┴───────────────────┤
        │   status_frame (will hold StatusBar in T13)        │
        └───────────────────────────────────────────────────-─┘

        Use tk.PanedWindow(orient=tk.HORIZONTAL) for the main/right split.
        The status bar frame is packed at the bottom with fill=X.
        The paned window fills the remaining space.

        For now, put placeholder labels in each frame:
        - main_frame: Label("Text panel — see T4")
        - right_frame: Label("Side panel — see T7")
        - status_frame: Label("Status bar — see T13")
        """
        ...

    def open_volume(self):
        """File → Open Volume handler.
        1. Show file picker (initialdir=SAMPLES_DIR, filetypes=[("Text files", "*.txt")])
        2. If user selects a file, store path in self.current_file
        3. Update window title to include filename
        4. (T4+ will wire up actual text loading)
        """
        ...

    def run(self):
        """Start the Tkinter main loop."""
        self.root.mainloop()
```

**Update `annotate_gui.py`:**
```python
#!/usr/bin/env python3
"""SC Decisions — Case Annotation GUI"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import AnnotationApp

def main():
    app = AnnotationApp()
    app.run()

if __name__ == "__main__":
    main()
```

**Acceptance Criteria:**
- [ ] `python annotate_gui.py` (from `regex_improve/`) opens a window with title "SC Decisions — Case Annotation Tool"
- [ ] Menu bar has File, Annotate, Export, Test, Help menus
- [ ] File → Open Volume shows a file picker dialog starting in `samples/`
- [ ] File → Exit closes the window
- [ ] Help → Keyboard Shortcuts shows a dialog listing all label shortcuts from `constants.LABELS`
- [ ] Window is resizable with min size 900x600
- [ ] Three-panel layout visible with placeholder text

---

### T4: Text Panel with Line Numbers + Scrolling
**Status:** TODO
**Depends on:** T2, T3
**Files to create:**
- `regex_improve/gui/text_panel.py`
**Files to modify:**
- `regex_improve/gui/app.py` (replace main_frame placeholder with TextPanel)

**Description:**
Build the scrollable text display with a line number gutter. This is the most performance-critical component — must handle 80k+ lines without freezing.

```python
import tkinter as tk
from tkinter import font as tkfont

class TextPanel(tk.Frame):
    """Main text display with line number gutter and synchronized scrolling."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # Create a monospace font for both text and gutter
        self.text_font = tkfont.Font(family="Consolas", size=10)
        # Fallback: ("Courier New", 10) if Consolas unavailable

        # Create widgets:
        # 1. self.gutter — tk.Canvas, fixed width ~60px, for line numbers
        # 2. self.text — tk.Text, read-only (state=DISABLED during display,
        #    temporarily NORMAL during insert/tag operations)
        # 3. self.scrollbar — tk.Scrollbar, vertical
        #
        # Layout (pack or grid):
        #   [gutter] [text___________________________] [scrollbar]
        #
        # Scrollbar commands:
        #   scrollbar.config(command=self._on_scrollbar)
        #   text.config(yscrollcommand=self._on_text_scroll)
        #
        # The gutter Canvas does NOT have its own scrollbar.
        # It redraws based on text widget's visible area.
        ...

    def load_text(self, text: str) -> None:
        """Load volume text into the widget.
        1. Enable text widget (state=NORMAL)
        2. Delete all existing content
        3. Insert full text in one call: self.text.insert('1.0', text)
        4. Disable text widget (state=DISABLED)
        5. Scroll to top
        6. Trigger gutter redraw
        """
        ...

    def get_selection(self) -> tuple | None:
        """Get current text selection as (start_index, end_index) Tk index strings.
        Returns None if no selection exists.
        Use: self.text.tag_ranges(tk.SEL)
        """
        ...

    def get_cursor_position(self) -> str:
        """Get current cursor position as Tk index string.
        Return self.text.index(tk.INSERT)
        """
        ...

    def get_current_line(self) -> int:
        """Get 1-based line number at cursor.
        Parse self.text.index(tk.INSERT) to extract line number.
        """
        ...

    def apply_tag(self, tag_name: str, start: str, end: str) -> None:
        """Apply a named tag to a text range.
        Temporarily enable text widget if needed, apply tag, re-disable.
        Tag configurations (colors) should be pre-created via configure_tag().
        """
        ...

    def remove_tag(self, tag_name: str, start: str = None, end: str = None) -> None:
        """Remove a named tag. If start/end are None, remove from entire text."""
        ...

    def configure_tag(self, tag_name: str, **kwargs) -> None:
        """Configure a tag's visual properties (background, foreground, etc.).
        Delegates to self.text.tag_configure(tag_name, **kwargs).
        """
        ...

    def scroll_to_line(self, line: int) -> None:
        """Scroll to make the given line visible and roughly centered.
        Use self.text.see(f"{line}.0") then adjust to center.
        """
        ...

    def _on_scrollbar(self, *args) -> None:
        """Called when user drags scrollbar. Move text and redraw gutter."""
        self.text.yview(*args)
        self._redraw_line_numbers()

    def _on_text_scroll(self, first, last) -> None:
        """Called when text widget scrolls. Update scrollbar and redraw gutter."""
        self.scrollbar.set(first, last)
        self._redraw_line_numbers()

    def _redraw_line_numbers(self) -> None:
        """Redraw only the visible line numbers in the gutter Canvas.

        Algorithm:
        1. Clear the canvas: self.gutter.delete("all")
        2. Get first visible line: self.text.index("@0,0") → parse line number
        3. Get last visible line: self.text.index(f"@0,{self.text.winfo_height()}") → parse line number
        4. For each visible line number:
           a. Get its y-coordinate: self.text.dinfo(f"{line}.0") returns (x, y, w, h, baseline)
              — if dinfo returns None, the line is not visible; skip
           b. Draw text on canvas: self.gutter.create_text(width-5, y, anchor="ne",
              text=str(line), font=self.text_font, fill="#606060")
        5. This method must be fast — it runs on every scroll event.
        """
        ...

    def _on_configure(self, event) -> None:
        """Called on widget resize. Redraw gutter."""
        self._redraw_line_numbers()
```

**Wire into `app.py`:**
- Import `TextPanel` and `VolumeLoader`
- Replace the main_frame placeholder with a `TextPanel` instance
- In `open_volume()`: use `VolumeLoader` to load the file, then call `text_panel.load_text(loader.text)`
- Store the `VolumeLoader` instance as `self.loader` for coordinate conversions later

**Important performance notes for the implementer:**
- The `text.dinfo()` method returns layout info only for lines currently rendered. For lines outside the visible viewport, it returns `None`. This is why we only draw visible lines.
- Do NOT use `text.get("1.0", "end")` to count lines — use the stored `loader.total_lines`.
- Bind `<Configure>` on the text widget to trigger gutter redraw on resize.
- Bind `<MouseWheel>` (Windows) and `<Button-4>/<Button-5>` (Linux) on the text widget to trigger gutter redraw after scroll.
- The text widget should have `wrap=tk.NONE` (no word wrap) and a horizontal scrollbar is optional but nice to have.
- Set `text.config(state=tk.DISABLED)` after loading to prevent user edits. Before applying tags, temporarily set `state=tk.NORMAL`.
- **Critical**: You do NOT need to set state=NORMAL to apply tags. Tags can be applied to a DISABLED text widget in Tkinter. Only `insert` and `delete` operations require NORMAL state.

**Acceptance Criteria:**
- [ ] Opening a volume loads the full text into the text panel
- [ ] Line numbers appear in the gutter, synchronized with scrolling
- [ ] Scrolling through Volume_121.txt (80k lines) is smooth — no visible lag
- [ ] Line numbers update correctly when scrolling via scrollbar, mouse wheel, and keyboard (arrow keys, Page Up/Down)
- [ ] Gutter redraws correctly on window resize
- [ ] Text is read-only — user cannot type into it
- [ ] Text uses monospace font (Consolas or Courier New)
- [ ] User can select text with mouse (selection highlight visible)

---

### T5: Highlight/Selection System + Label Assignment
**Status:** TODO
**Depends on:** T1, T2, T4
**Files to create:**
- `regex_improve/gui/highlight_manager.py`
- `regex_improve/gui/file_io.py`
**Files to modify:**
- `regex_improve/gui/app.py` (wire highlight manager, handle label assignment)

**Description:**
Build the system that handles: user selects text → presses label button/shortcut → annotation is created, highlight tag applied, annotation stored. Also implement load/save for annotations.json.

#### `regex_improve/gui/highlight_manager.py`
```python
from gui.constants import LABELS, LABEL_MAP, GROUPED_LABELS
from gui.models import Annotation, Case, VolumeData, AnnotationStore
from gui.volume_loader import VolumeLoader

class HighlightManager:
    """Manages the creation and display of annotation highlights."""

    def __init__(self, text_panel, loader: VolumeLoader, store: AnnotationStore, volume_data: VolumeData):
        self.text_panel = text_panel
        self.loader = loader
        self.store = store
        self.volume_data = volume_data
        self._tag_counter = 0  # for unique tag names
        self._setup_tag_colors()

    def _setup_tag_colors(self):
        """Pre-configure a Tkinter tag for each label's color.
        Tag name pattern: "label_{key}" with background=color.
        """
        for label_def in LABELS:
            self.text_panel.configure_tag(
                f"label_{label_def.key}",
                background=label_def.color
            )

    def create_annotation(self, label_key: str) -> Annotation | None:
        """Create an annotation from the current selection or cursor position.

        Steps:
        1. Look up the LabelDef for label_key
        2. If selection_type == "selection":
           a. Get selection from text_panel.get_selection()
           b. If no selection, show warning messagebox and return None
           c. Get selected text via text_panel.text.get(start, end)
        3. If selection_type == "cursor":
           a. Get cursor line via text_panel.get_current_line()
           b. Set start = f"{line}.0", end = f"{line}.end"
           c. Get line text
        4. Convert Tk indices to char offsets via loader.tk_index_to_char()
        5. Derive line numbers via loader.char_to_line()
        6. Derive page numbers via loader.get_page()
        7. Determine group value:
           - If label_key not in GROUPED_LABELS → group = None
           - If label_key == "case_number" → handle via _assign_case_number_group()
           - If label_key == "parties" → handle via _assign_parties_group()
        8. Create Annotation object
        9. Find the active case at this position (or create one for start_of_case)
        10. Add annotation to case
        11. Apply visual highlight tag
        12. Return the annotation
        """
        ...

    def _find_or_create_case(self, label_key: str, line: int) -> Case | None:
        """Find the case that contains this line, or create one if label is start_of_case.

        Logic:
        - If label_key == "start_of_case":
          - Check no existing case already starts at this line
          - Create new Case with generated case_id
          - Add to volume_data
          - Return the new case
        - If label_key == "end_of_case":
          - Find the nearest preceding case that has a start_of_case but no end_of_case
          - If found, return it. If not, show warning and return None.
        - For all other labels:
          - Find the case at this line via volume_data.get_case_at_line(line)
          - If no case found, show warning: "No case at this position. Mark Start of Case first."
          - Return the case or None
        """
        ...

    def _assign_case_number_group(self, case: Case) -> int:
        """Determine group index for a new case_number annotation.
        - If case has 0 existing case_numbers → return 0
        - If case has 1+ existing case_numbers → prompt user:
          "Add as consolidated case number? (Group N)"
          - If yes → return case.next_group_index()
          - If no → return None (signal to caller to abort)
        """
        ...

    def _assign_parties_group(self, case: Case) -> int:
        """Determine group index for a new parties annotation.
        - If case is not consolidated (0-1 case_numbers) → return 0
        - If case is consolidated → prompt user:
          "Which case number does this parties block belong to?"
          Show existing case_numbers with their group indices as options.
          Return the selected group index.
        """
        ...

    def remove_annotation(self, case: Case, annotation_index: int) -> None:
        """Remove an annotation from a case and remove its highlight tag.
        1. Get the annotation at annotation_index
        2. Remove the Tkinter tag for this annotation
        3. Call case.remove_annotation(annotation_index)
        """
        ...

    def apply_all_highlights(self) -> None:
        """Re-apply all highlight tags for the current volume.
        Called after loading a volume that already has annotations.
        Iterate all cases → all annotations → apply tag.
        """
        ...

    def _apply_highlight(self, annotation: Annotation) -> None:
        """Apply a highlight tag for a single annotation.
        Convert char offsets to Tk indices, apply tag with label's color.
        """
        start_tk = self.loader.char_to_tk_index(annotation.start_char)
        end_tk = self.loader.char_to_tk_index(annotation.end_char)
        self.text_panel.apply_tag(f"label_{annotation.label}", start_tk, end_tk)
```

#### `regex_improve/gui/file_io.py`
```python
import json
import os
import tempfile
from pathlib import Path
from gui.models import AnnotationStore

class FileIO:
    """Handles loading and saving annotations.json with atomic writes."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> AnnotationStore:
        """Load annotations from file.
        - If file doesn't exist, return empty AnnotationStore
        - If file exists, read JSON and deserialize:
          - Check for "format_version" key
          - If format_version == 2 → use AnnotationStore.from_dict()
          - If no format_version (old format) → show warning, return empty store
            (old format migration is out of scope — user can re-annotate)
        """
        ...

    def save(self, store: AnnotationStore) -> None:
        """Save annotations to file using atomic write.
        1. Serialize store to dict via store.to_dict()
        2. Write JSON to a temp file in the same directory
           (use tempfile.NamedTemporaryFile with delete=False, dir=self.path.parent)
        3. os.replace(temp_path, self.path) — atomic on all platforms
        4. This ensures no data corruption if the process crashes mid-write
        """
        ...
```

**Wire into `app.py`:**
- In `open_volume()`, after loading text:
  1. Create `FileIO` and load `AnnotationStore`
  2. Get or create `VolumeData` for the opened file
  3. Create `HighlightManager` with all dependencies
  4. Call `highlight_manager.apply_all_highlights()` (for resuming work on a previously annotated volume)
- Add a method `assign_label(label_key: str)` that calls `highlight_manager.create_annotation(label_key)`
- Wire each Annotate menu item to call `assign_label` with the appropriate label key

**Acceptance Criteria:**
- [ ] Select text, click a label → text gets colored background matching the label's color
- [ ] Cursor-position labels (start_of_case, end_of_case, etc.) highlight the entire line without requiring selection
- [ ] Attempting to annotate outside a case boundary shows a warning
- [ ] start_of_case creates a new case in the AnnotationStore
- [ ] end_of_case closes the case — subsequent annotations at lines after the end go to the next case or warn
- [ ] Annotations persist: save, close, reopen volume → highlights reappear
- [ ] Character offsets in saved annotations match the actual text positions
- [ ] Atomic save: killing the process mid-save does not corrupt annotations.json
- [ ] Old-format annotations.json shows a warning (not a crash)

---

### T6: Consolidated Case + Multi-Party Workflow
**Status:** TODO
**Depends on:** T5
**Files to create:**
- `regex_improve/gui/dialogs.py`
**Files to modify:**
- `regex_improve/gui/highlight_manager.py` (wire dialogs into group assignment methods)

**Description:**
Implement the prompt dialogs for consolidated case number assignment and party-to-case-number linking.

#### `regex_improve/gui/dialogs.py`
```python
import tkinter as tk
from tkinter import simpledialog, messagebox
from typing import Optional, List, Tuple

def ask_consolidated(parent: tk.Tk, group_index: int) -> bool:
    """Show a Yes/No dialog: 'Add as consolidated case number? (Group {group_index})'
    Returns True if user clicks Yes, False otherwise.
    Use messagebox.askyesno().
    """
    ...

def ask_party_group(parent: tk.Tk, case_numbers: List[Tuple[int, str]]) -> Optional[int]:
    """Show a dialog asking which case number this parties block belongs to.

    Args:
        case_numbers: list of (group_index, case_number_text) tuples
                      e.g. [(0, "G.R. No. 132724"), (1, "G.R. No. 132800")]

    Shows a dialog with radio buttons, one per case number:
        "Which case number does this parties block belong to?"
        ○ [Group 0] G.R. No. 132724
        ○ [Group 1] G.R. No. 132800
        [OK] [Cancel]

    Returns the selected group index, or None if cancelled.

    Implementation: Create a tk.Toplevel with radio buttons and OK/Cancel buttons.
    Use a tk.IntVar for the selection.
    """
    ...

def show_warning(parent: tk.Tk, title: str, message: str) -> None:
    """Show a warning dialog. Wrapper around messagebox.showwarning()."""
    ...
```

**Wire into `highlight_manager.py`:**
- `_assign_case_number_group()` calls `dialogs.ask_consolidated()` when case already has 1+ case_numbers
- `_assign_parties_group()` calls `dialogs.ask_party_group()` when case is consolidated
- Both methods need access to `self.root` (the Tk root widget) — pass it via the HighlightManager constructor

**Acceptance Criteria:**
- [ ] Adding a second case_number to a case shows the consolidated prompt
- [ ] Clicking "Yes" assigns the next group index; "No" aborts the annotation
- [ ] Adding parties to a consolidated case (2+ case_numbers) shows the group selection dialog
- [ ] The dialog lists all existing case_numbers with their group indices
- [ ] Selecting a group and clicking OK returns the correct index
- [ ] Clicking Cancel aborts the parties annotation
- [ ] Non-consolidated cases (single case_number) auto-assign parties group=0 with no prompt
- [ ] `is_consolidated` property on Case updates automatically when second case_number is added

---

### T7: Side Panel — Annotation List + Case Navigator
**Status:** TODO
**Depends on:** T5
**Files to create:**
- `regex_improve/gui/side_panel.py`
**Files to modify:**
- `regex_improve/gui/app.py` (replace right_frame placeholder with SidePanel)

**Description:**
Build the right panel with two sections: Case Navigator (top) and Annotation List (bottom).

```python
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable
from gui.constants import LABELS, LABEL_MAP
from gui.models import Case, VolumeData

class SidePanel(tk.Frame):
    """Right panel containing case navigator, annotation list, and label buttons."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, width=300, **kwargs)
        self.pack_propagate(False)  # Maintain fixed width

        # Callbacks (set by app.py after construction)
        self.on_navigate: Optional[Callable[[int], None]] = None  # called with case index
        self.on_label_click: Optional[Callable[[str], None]] = None  # called with label key
        self.on_delete: Optional[Callable[[], None]] = None
        self.on_annotation_click: Optional[Callable[[int], None]] = None  # click item in list

        self._create_case_navigator()
        self._create_annotation_list()
        self._create_label_buttons()

    def _create_case_navigator(self):
        """Create the case navigation section at the top.

        Layout:
        ┌───────────────────────────┐
        │  Case Navigator           │
        │  [◄]  Case 0/0  [►]      │
        │  Status: (none)           │
        │  Notes: [text entry]      │
        └───────────────────────────┘

        - self.nav_frame: LabelFrame with title "Case Navigator"
        - self.prev_btn: Button "◄" — calls self._navigate(-1)
        - self.next_btn: Button "►" — calls self._navigate(+1)
        - self.case_label: Label showing "Case N/M"
        - self.status_label: Label showing case status
        - self.notes_entry: Entry widget for case notes

        State:
        - self._current_case_index: int = -1 (no case selected)
        - self._total_cases: int = 0
        """
        ...

    def _create_annotation_list(self):
        """Create the scrollable annotation list.

        Layout:
        ┌───────────────────────────┐
        │  Annotations              │
        │  ┌───────────────────────┐│
        │  │ ☑ [case_number] G.R.  ││
        │  │ ☑ [date] November... ││
        │  │ ☐ [division] FIRST.. ││
        │  │ ...                   ││
        │  └───────────────────────┘│
        │  [Delete Selected]        │
        └───────────────────────────┘

        Use a ttk.Treeview with columns: checkbox, label, text (truncated).
        Or simpler: a tk.Listbox with Checkbutton widgets.

        Recommended approach: Use a tk.Frame with a Canvas+Scrollbar for scrollable
        content. Each annotation is a row with a Checkbutton (for selection)
        and a Label (showing "label: text_preview").

        Simpler approach (preferred): Use a ttk.Treeview with checkbutton column.
        Columns: "#0" (tree), "label", "text", "group"
        Each row represents one annotation.
        - Clicking a row scrolls the main text to that annotation's position
        - Selection (via checkbuttons or Treeview selection) enables Delete

        self.annotation_tree: ttk.Treeview
        self.delete_btn: Button "Delete Selected"
        """
        ...

    def _create_label_buttons(self):
        """Create the label assignment buttons.

        Layout:
        ┌───────────────────────────┐
        │  Labels                   │
        │  [1] Start Case           │
        │  [2] Case Number          │
        │  [3] Date                 │
        │  ...                      │
        │  [X] End Case             │
        └───────────────────────────┘

        One button per label in LABELS. Button text = label.button_text.
        Button background tinted with label.color.
        Clicking calls self.on_label_click(label.key).
        """
        ...

    def update_case_display(self, case: Optional[Case], index: int, total: int):
        """Update the case navigator and annotation list for the given case.

        Args:
            case: The currently viewed Case, or None
            index: 0-based index of this case in the volume (display as 1-based)
            total: total number of cases in the volume

        Updates:
        1. Case label: "Case {index+1}/{total}" or "No cases" if total==0
        2. Status label: case.status or "(none)"
        3. Notes entry: case.notes or ""
        4. Annotation list: clear and repopulate with case.annotations
           Each row: label display_name, text (truncated to ~30 chars), group (if not None)
        5. Enable/disable ◄/► buttons based on index bounds
        """
        ...

    def _navigate(self, direction: int):
        """Navigate to previous (-1) or next (+1) case.
        Update self._current_case_index and call self.on_navigate callback.
        """
        ...

    def get_selected_annotation_indices(self) -> list[int]:
        """Return indices of selected annotations in the treeview."""
        ...
```

**Wire into `app.py`:**
- Create `SidePanel` in the right_frame
- Set callbacks:
  - `side_panel.on_navigate` → scroll text_panel to case start line
  - `side_panel.on_label_click` → call `assign_label(key)`
  - `side_panel.on_delete` → delete selected annotations via highlight_manager
  - `side_panel.on_annotation_click` → scroll text_panel to annotation position
- After any annotation add/remove, call `side_panel.update_case_display()`

**Acceptance Criteria:**
- [ ] Side panel has fixed ~300px width, doesn't resize with window
- [ ] Case navigator shows "Case N/M" with working ◄/► buttons
- [ ] ◄ button disabled at case 1, ► disabled at last case
- [ ] Annotation list shows all annotations for the current case with label name and truncated text
- [ ] Clicking an annotation in the list scrolls the main text to its position
- [ ] Label buttons are displayed with tinted backgrounds matching their colors
- [ ] Clicking a label button triggers annotation creation (same as keyboard shortcut)
- [ ] Delete Selected removes checked annotations from both the list and the data model
- [ ] Annotation list updates immediately when annotations are added or removed

---

### T8: Visual Separators Between Cases
**Status:** TODO
**Depends on:** T5, T7
**Files to modify:**
- `regex_improve/gui/highlight_manager.py` (add separator logic)
- `regex_improve/gui/app.py` (trigger separator refresh on annotation changes)

**Description:**
When both Start of Case and End of Case are marked, apply visual separators to make case boundaries obvious in the text panel.

**Implementation approach:**
1. Define two special tags in `_setup_tag_colors()`:
   - `"case_separator_start"`: `background="#FFD700"` (gold), full line, `font=bold`
   - `"case_separator_end"`: `background="#FFD700"` (gold), full line, `font=bold`

2. Add method `refresh_separators()` to `HighlightManager`:
   ```python
   def refresh_separators(self):
       """Remove all separator tags, then re-apply for all complete cases.
       A case is "complete" if it has both start_of_case and end_of_case annotations.
       For each complete case:
         - Apply case_separator_start tag to the entire start_of_case line
         - Apply case_separator_end tag to the entire end_of_case line
       """
   ```

3. Call `refresh_separators()` after every annotation add/remove.

4. The gold highlight should span the full line width. Use the tag config:
   ```python
   self.text_panel.configure_tag("case_separator_start",
       background="#FFD700", font=bold_font,
       selectbackground="#FFD700")
   self.text_panel.configure_tag("case_separator_end",
       background="#FFD700", font=bold_font,
       selectbackground="#FFD700")
   ```

**Acceptance Criteria:**
- [ ] When both Start and End of Case are marked, the start line gets a gold background
- [ ] The end line also gets a gold background
- [ ] Incomplete cases (only start, no end) do not show separators
- [ ] Deleting a start_of_case or end_of_case annotation removes the separator
- [ ] Separators are visible when scrolling through the document
- [ ] Multiple cases show distinct separation between each pair

---

### T9: Keyboard Shortcut System
**Status:** TODO
**Depends on:** T5, T7
**Files to modify:**
- `regex_improve/gui/app.py` (bind all keyboard shortcuts)

**Description:**
Bind all keyboard shortcuts from `constants.LABELS` to the annotation assignment function. Handle platform-specific binding quirks.

**Implementation:**
1. In `app.py.__init__()`, after creating all components, call `_bind_shortcuts()`
2. `_bind_shortcuts()`:
   ```python
   def _bind_shortcuts(self):
       """Bind keyboard shortcuts for all labels.
       For each label in LABELS:
           self.root.bind(label.tk_binding, lambda e, k=label.key: self.assign_label(k))

       Also bind:
       - Delete key → delete selected annotations
       - Ctrl+S → save
       - Ctrl+Z → undo last annotation (nice to have, can be deferred)

       Platform note (Windows):
       - Ctrl+Shift+letter bindings: Tkinter on Windows may generate the
         keysym as uppercase (e.g., 'D' not 'd'). Bind BOTH cases:
           self.root.bind("<Control-Shift-Key-D>", handler)
           self.root.bind("<Control-Shift-Key-d>", handler)
       - Ctrl+number bindings should work as-is.
       - Return "break" from handlers to prevent default Tkinter behavior
         (e.g., prevent Ctrl+Shift+V from also pasting)
       """
   ```

3. Each shortcut handler should:
   - Call `self.assign_label(label_key)`
   - Return `"break"` to prevent event propagation

**Acceptance Criteria:**
- [ ] All 16 label shortcuts work (Ctrl+1-0 and Ctrl+Shift+D/E/V/O/P/X)
- [ ] Ctrl+Shift+V does NOT paste — it assigns the Votes label
- [ ] Ctrl+Shift+X does NOT cut — it assigns End of Case
- [ ] Ctrl+S saves annotations
- [ ] Delete key deletes selected annotations from the side panel
- [ ] Shortcuts work regardless of focus (text panel or side panel)
- [ ] Help → Keyboard Shortcuts dialog reflects actual bindings

---

### T10: Auto-Save + File I/O Wiring
**Status:** TODO
**Depends on:** T5, T7
**Files to modify:**
- `regex_improve/gui/app.py` (wire auto-save after every annotation change)
- `regex_improve/gui/highlight_manager.py` (trigger save callback after mutations)

**Description:**
Wire the auto-save system so that `annotations.json` is written after every annotation add/remove/modify.

**Implementation:**
1. Add an `on_change` callback to `HighlightManager`:
   ```python
   class HighlightManager:
       def __init__(self, ..., on_change: Callable = None):
           self.on_change = on_change
   ```

2. Call `self.on_change()` at the end of:
   - `create_annotation()` (after successful annotation creation)
   - `remove_annotation()` (after successful removal)

3. In `app.py`, set `on_change` to a method that:
   - Calls `self.file_io.save(self.store)`
   - Updates the status bar (T13) to show "Saved"
   - Updates the side panel display

4. Also wire File → Save menu to the same save method.

5. On volume open, if `annotations.json` exists:
   - Load annotations via `FileIO.load()`
   - Re-apply all highlights via `highlight_manager.apply_all_highlights()`
   - Initialize case navigator to first case (if any)

**Acceptance Criteria:**
- [ ] Every annotation add/delete automatically writes annotations.json
- [ ] Closing and reopening a volume restores all annotations and highlights
- [ ] File → Save works manually
- [ ] The save is atomic (temp file + rename)
- [ ] If annotations.json doesn't exist, it's created on first annotation
- [ ] No data loss if the application is force-killed (last save is intact)

---

### T11: Export System — Pluggable Exporters
**Status:** TODO
**Depends on:** T1, T5
**Files to create:**
- `regex_improve/gui/exporters.py`
**Files to modify:**
- `regex_improve/gui/app.py` (wire Export menu items)

**Description:**
Implement the pluggable export system with JSON and Markdown exporters.

```python
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
from gui.models import AnnotationStore, Case, Annotation, VolumeData
from gui.volume_loader import VolumeLoader

class BaseExporter(ABC):
    """Abstract base class for annotation exporters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable exporter name."""
        ...

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """File extension without dot, e.g. 'json', 'md'."""
        ...

    @abstractmethod
    def export(self, store: AnnotationStore, output_path: Path,
               loaders: dict[str, VolumeLoader] = None) -> None:
        """Export annotations to the given path.
        Args:
            store: the full annotation store
            output_path: path to write the export file
            loaders: optional dict of {volume_filename: VolumeLoader} for raw text access
        """
        ...

class JsonExporter(BaseExporter):
    """Exports annotations as JSON (identical to annotations.json format)."""

    @property
    def name(self) -> str:
        return "JSON"

    @property
    def file_extension(self) -> str:
        return "json"

    def export(self, store, output_path, loaders=None):
        """Write store.to_dict() as formatted JSON."""
        ...

class MarkdownExporter(BaseExporter):
    """Exports ground truth as human/LLM-readable markdown report."""

    @property
    def name(self) -> str:
        return "Markdown"

    @property
    def file_extension(self) -> str:
        return "md"

    def export(self, store, output_path, loaders=None):
        """Generate markdown report for all annotated cases.

        For each volume in the store:
          For each case in the volume:
            Output a section like:

            ### Volume_421.txt — Case 3 (consolidated: 2 case numbers)

            **Boundaries:** lines {start_line}–{end_line} (pages {start_page}–{end_page})

            **Case Numbers:**
              - [group 0] `{text}` (line {line}, chars {start_char}-{end_char})
              - [group 1] `{text}` (line {line}, chars {start_char}-{end_char})

            **Parties:**
              - [group 0] `{text}` (lines {start_line}-{end_line})
              - [group 1] `{text}` (lines {start_line}-{end_line})

            **Date:** `{text}` (line {line}, chars {start_char}-{end_char})
            **Division:** `{text}` (line {line})
            **Ponente:** `{text}` (line {line})
            **Document Type:** `{text}` (line {line})
            **Votes:** `{text}` (lines {start_line}-{end_line})

            If loaders is provided for this volume, also output:
            ```
            Raw text around case start (±5 lines):
            {line_number}| {line_text}
            ...
            ```

        Fields that have no annotations should show "(not annotated)".
        Grouped labels (case_number, parties) show each group separately.
        Non-grouped labels show once.
        """
        ...
```

**Wire into `app.py`:**
- Export → Export as JSON: prompt for save location (default: `annotation_exports/ground_truth_{timestamp}.json`)
- Export → Export as Markdown: prompt for save location (default: `annotation_exports/ground_truth_{timestamp}.md`)
- Both use `filedialog.asksaveasfilename()` with appropriate default name

**Acceptance Criteria:**
- [ ] Export → JSON creates a valid JSON file matching the `format_version: 2` structure
- [ ] Export → Markdown creates a readable report with all annotated fields
- [ ] Grouped fields (case_number, parties) show group indices in the markdown
- [ ] Un-annotated fields show "(not annotated)"
- [ ] Raw text excerpts appear when volume loaders are available
- [ ] Character offsets and line numbers in the markdown match the actual annotation data
- [ ] Timestamp in default filename uses format `YYYYMMDD_HHMMSS`
- [ ] Export directory (`annotation_exports/`) is created if it doesn't exist

---

### T12: Extraction Method Evaluation Framework
**Status:** TODO
**Depends on:** T5, T11
**Files to create:**
- `regex_improve/gui/evaluation.py`
**Files to modify:**
- `regex_improve/gui/app.py` (wire Test menu)

**Description:**
Implement the pluggable evaluation system that tests extraction methods against ground truth annotations.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import importlib.util
import re
from pathlib import Path

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
        ...

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
        ...

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
        ...

    def recall(self, label: str = None) -> float:
        """Compute recall (correct detections / total expected)."""
        ...

    def f1(self, label: str = None) -> float:
        """Compute F1 score."""
        ...

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
        ...

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
        ...

    def _spans_overlap(self, a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
        """Check if two character spans overlap."""
        return a_start < b_end and b_start < a_end
```

**Wire into `app.py`:**
- Test → Run Evaluation → Regex:
  1. Instantiate `RegexMethod(Path(IMPROVED_REGEX_FILE))`
  2. Create `EvaluationRunner(self.store, {self.loader.filename: self.loader})`
  3. Run evaluation
  4. Show results in a new Toplevel window:
     - Display the summary table
     - Below: expandable per-case details showing expected vs actual
  5. Option to export results as JSON

**Acceptance Criteria:**
- [ ] Test → Regex loads `improved_regex.py` dynamically (reimports each time)
- [ ] If `improved_regex.py` defines no patterns, falls back to annotate_tool.py patterns
- [ ] Evaluation runs against all complete cases (with both start/end boundaries)
- [ ] Results dialog shows per-field precision/recall/F1 table
- [ ] Per-case breakdown shows expected vs actual for each field
- [ ] Exact match, overlap, and detection are scored correctly
- [ ] Consolidated cases: each case_number group is scored independently
- [ ] Results can be exported as JSON
- [ ] Empty annotations (no complete cases) show an appropriate message

---

### T13: Status Bar + Polish
**Status:** TODO
**Depends on:** T4, T7, T10
**Files to create:**
- `regex_improve/gui/status_bar.py`
**Files to modify:**
- `regex_improve/gui/app.py` (replace status_frame placeholder, wire updates)

**Description:**
Add the status bar and polish the overall integration.

#### `regex_improve/gui/status_bar.py`
```python
import tkinter as tk

class StatusBar(tk.Frame):
    """Bottom status bar showing current file, cursor position, and case count."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # Three labels, left-aligned with separators
        self.file_label = tk.Label(self, text="No file loaded", anchor=tk.W,
                                   relief=tk.SUNKEN, padx=5)
        self.position_label = tk.Label(self, text="Line 0", anchor=tk.W,
                                       relief=tk.SUNKEN, padx=5)
        self.case_label = tk.Label(self, text="0 cases", anchor=tk.W,
                                   relief=tk.SUNKEN, padx=5)

        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.position_label.pack(side=tk.LEFT, fill=tk.X)
        self.case_label.pack(side=tk.LEFT, fill=tk.X)

    def update_file(self, filename: str):
        """Update the filename display."""
        self.file_label.config(text=filename)

    def update_position(self, line: int, page: int = 0):
        """Update the cursor position display.
        Shows: 'Line 12,051 | Page 251'
        """
        line_str = f"Line {line:,}"
        if page > 0:
            line_str += f" | Page {page}"
        self.position_label.config(text=line_str)

    def update_cases(self, annotated: int, total_complete: int):
        """Update the case count display.
        Shows: '16 cases (12 complete)'
        """
        self.case_label.config(text=f"{annotated} cases ({total_complete} complete)")
```

**Wire into `app.py`:**
- Create `StatusBar` in status_frame, pack at bottom with `fill=X`
- Update file label when a volume is opened
- Update position on cursor movement:
  - Bind `<ButtonRelease-1>` and `<KeyRelease>` on text_panel.text to update position
  - Get current line from text_panel, get page from loader
- Update case count after annotation changes

**Polish items (all in `app.py`):**
1. **Window close handler**: Bind `WM_DELETE_WINDOW` to save before closing
2. **Focus management**: After opening a volume, set focus to text_panel.text
3. **Menu state**: Disable Annotate/Export/Test menus when no volume is loaded; enable on volume open
4. **Error handling**: Wrap file operations in try/except, show messagebox on errors
5. **Page marker styling**: Configure a tag `"page_marker"` with `foreground="#999999"` (gray). After loading text, find all `--- Page N ---` lines and apply this tag.

**Acceptance Criteria:**
- [ ] Status bar shows filename, cursor line/page, and case counts
- [ ] Cursor position updates as user clicks or uses keyboard in the text panel
- [ ] Page number in status bar is correct (matches nearest preceding page marker)
- [ ] Case count updates when cases are added/removed
- [ ] Page marker lines (`--- Page N ---`) appear in gray
- [ ] Menus are disabled when no file is loaded
- [ ] Closing the window saves any unsaved annotations
- [ ] No unhandled exceptions on normal workflows (open, annotate, save, close)

---

## Review Protocol

After each task is implemented, the architect (Claude Code) will:

1. **Read all created/modified files** — verify they match the spec
2. **Run the acceptance criteria** — test each criterion
3. **Check for:**
   - Import errors (run `python -c "from gui.X import Y"`)
   - Naming mismatches (do class/method names match the spec?)
   - Missing `to_dict`/`from_dict` round-trip correctness
   - Tkinter layout issues (run the GUI visually)
   - Edge cases: empty volume, no annotations, single-line selection
4. **Update TASKS.md** — mark status as DONE or REVISION_NEEDED with notes
5. **Issue next task** — paste the next task spec into Cline's chat

---

## Done / Archived

### Task 001: Backport annotate_tool regex improvements into notebook 04
**Status:** ARCHIVED (superseded by restructuring plan)

---
