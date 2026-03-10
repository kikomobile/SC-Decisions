# TASKS.md — Detection Pipeline Implementation

**Reference:** `DETECTION_PLAN.md` for architecture diagrams, cost model, and design rationale.
**Ground truth:** `regex_improve/annotation_exports/ground_truth_20260309_144413.json` (72 cases, Volume 226)
**Test volume:** `downloads/Volume_226.txt` (33,443 lines, ~1.4MB)

---

## How This Works
- **Architect** (Claude Code) writes tasks here with full specs
- **Worker** (Cline/DeepSeek) reads tasks and implements them
- Architect reviews completed tasks and updates status
- Never delete tasks — archive under Completed sections
- Tasks must be completed in order (respect dependencies)

---

## Completed Tasks (Annotation GUI)

- [x] **GUI-1**: Project scaffolding + constants + data model (`gui/__init__.py`, `gui/constants.py`, `gui/models.py`, `annotate_gui.py`) — LabelDef dataclass, 16 label definitions, Annotation/Case/VolumeData/AnnotationStore
- [x] **GUI-2**: Volume loader (`gui/volume_loader.py`) — O(1) line↔char↔page coordinate conversion using bisect
- [x] **GUI-3**: Main app window + text panel + side panel (`gui/app.py`, `gui/text_panel.py`, `gui/side_panel.py`) — Tk composition root, scrollable text with canvas gutter, case navigator
- [x] **GUI-4**: Highlight manager + dialogs (`gui/highlight_manager.py`, `gui/dialogs.py`) — Tag-based color coding, consolidated case prompts, party group linking
- [x] **GUI-5**: File I/O + status bar (`gui/file_io.py`, `gui/status_bar.py`) — Atomic JSON writes (temp→replace), bottom status bar
- [x] **GUI-6**: Exporters + evaluation framework (`gui/exporters.py`, `gui/evaluation.py`) — JSON/Markdown export, ExtractionMethod protocol, RegexMethod, EvaluationRunner with P/R/F1

---

## Detection Pipeline Tasks

All new files live under `regex_improve/detection/`.
Import `VolumeLoader` from `gui.volume_loader` (option A — shared dependency).
Standalone scorer reads JSON only (option B — no gui dependency for scorer).
DeepSeek API key is required (pipeline fails with clear error if missing).

---

### T1: Package Scaffold + Preprocessor

**Status:** DONE
**Review notes:** 33,443 lines, 2,361 noise (7.1%), 31,082 content. All 5 assertions pass. Post-review fix: `RE_SHORT_TITLE` changed from `(v|y|u)s?` with `re.IGNORECASE` to `(?:v|y|V|Y)s?\.` without IGNORECASE — original regex matched nearly all prose lines, causing cascading false noise after page breaks. Added `RE_SYLLABUS_HEADER` exclusion in Pass 2 alongside `RE_DIVISION`.
**Depends on:** GUI-2 (VolumeLoader — already complete)
**Files to create:**
- `regex_improve/detection/__init__.py`
- `regex_improve/detection/preprocess.py`

**Description:**
Create the detection package and the preprocessor that classifies "noise lines" — page markers, volume headers, short-title lines, and PHILIPPINE REPORTS headers. These lines are NOT stripped (that would destroy character offsets). Instead, build a parallel boolean array `noise_mask` so the FSM (T2) can skip them during parsing.

#### `regex_improve/detection/__init__.py`
Empty file. Makes `detection/` a package.

#### `regex_improve/detection/preprocess.py`

```python
import re
import sys
from pathlib import Path
from typing import Optional

# Add regex_improve/ to path so gui.volume_loader is importable
_REGEX_IMPROVE_DIR = Path(__file__).resolve().parent.parent
if str(_REGEX_IMPROVE_DIR) not in sys.path:
    sys.path.insert(0, str(_REGEX_IMPROVE_DIR))

from gui.volume_loader import VolumeLoader
```

**Module-level regex constants:**
```python
RE_PAGE_MARKER = re.compile(r'^--- Page \d+ ---$')
RE_VOLUME_HEADER = re.compile(r'^VOL[.,]\s*\d+.*\d+\s*$')
RE_PHILIPPINE_REPORTS = re.compile(r'^\d+\s+PHILIPPINE REPORTS\s*$')
RE_SHORT_TITLE = re.compile(r'^[A-Z][A-Za-z\s,.\'\-]+(vs?\.|VS\.)[A-Za-z\s,.\'\-]+$')
```

**Class `VolumePreprocessor`:**

Fields:
- `loader: VolumeLoader` — initialized in constructor
- `noise_mask: list[bool]` — `noise_mask[i]` = True if line i (0-indexed) is noise
- `volume_name: str`

Methods:

1. `load(self, path: Path) -> str` — Load volume via `self.loader.load(path)`, set `self.volume_name = path.name`, call `self._classify_noise()`, return the full unmodified text.

2. `_classify_noise(self)` — Build `self.noise_mask` (same length as `self.loader.lines`). A line is noise if:
   - **Pass 1 (definite noise):** Matches `RE_PAGE_MARKER`, `RE_VOLUME_HEADER`, or `RE_PHILIPPINE_REPORTS`.
   - **Pass 2 (contextual noise):** Matches `RE_SHORT_TITLE` AND the previous non-blank line (scanning backward) was already marked as noise in pass 1. This prevents false positives on party name lines that contain "vs.".
   - **Pass 3 (sandwiched blanks):** A blank line is noise if both the nearest preceding non-blank line AND the nearest following non-blank line are already marked as noise. This catches the blank lines between `--- Page NNN ---` and `VOL. 226, ...`.

3. `is_noise(self, line_1based: int) -> bool` — Check if a 1-based line number is noise.

4. `get_content_lines(self, start_line: int, end_line: int) -> list[tuple[int, str]]` — Return non-noise lines in range `[start_line, end_line]` (1-based inclusive) as `(line_number, text)` tuples.

**`if __name__ == "__main__"` test block:**
- Navigate to project root to find `downloads/Volume_226.txt`
- Load it, print: total lines, noise lines count, content lines count
- Print first 20 noise lines with their line numbers
- Assert: line 1 (`--- Page 1 ---`) IS noise
- Assert: line 421 (`SECOND DIVISION`) is NOT noise
- Assert: line 453 (`--- Page 19 ---`) IS noise
- Assert: line 454 (`2 PHILIPPINE REPORTS`) IS noise
- Assert: line 456 (`Milano vs. Employees' Compensation Commission`) IS noise

**Constraints:**
- Do NOT strip or modify the loaded text. `load()` returns the exact same string as `VolumeLoader.load()`.
- `noise_mask` must be exactly `len(self.loader.lines)` long.
- Short-title detection MUST require the contextual check (previous non-blank line is noise). Without it, party name lines like `LYDIA D. MILANO, petitioner, vs. EMPLOYEES'...` would be falsely flagged.
- Use `list[bool]` not `List[bool]` (Python 3.10+).
- Do not import anything from `gui/` except `volume_loader`.

---

### T2: Case Boundary FSM

**Status:** DONE
**Review notes:** 72/72 boundaries detected, all start_lines exact match. 72/74 case_number text exact (97.3%), 68/72 date text exact (94.4%). Known minor issues: (a) Adm. Matter with `&` in number truncated — regex non-greedy group stops at `&`, (b) 3 dates include trailing period from bracket, (c) consolidated case_47 second CN missed (17-line gap exceeds search limit). All are low-frequency edge cases handled by downstream confidence scoring + LLM fallback.
**Depends on:** T1
**Files to create:**
- `regex_improve/detection/boundary_fsm.py`

**Description:**
Finite-state machine that processes volume lines, skipping noise lines, to detect where each case starts and ends. Extracts case_number and date from bracket lines. Handles OCR bracket variants and consolidated cases.

#### Key patterns from Volume 226

Division headers (72 total, at these lines): `EN BANC` (31), `SECOND DIVISION` (28), `FIRST DIVISION` (12), `FIRST DIVISLON` (1 — OCR error).

Case bracket variants observed:
```
[G.R. No. 50545. May 23, 1986]           — standard
[G.R. No, 56191. May 27, 1986]           — comma for period (5×)
(G.R. No. 64548. July 7, 1986]           — parenthesis opener
{G.R. No. 69208. May 28, 1986]           — curly brace opener
[G.R. No. 63409. May 30, [986]           — [986 for 1986
{Adm. Matter Nos. R-278-RTJ & R-309-RTJ]. May 30, 1986]  — Adm. Matter
[Adm. Case No. 2756. June 5, 1986]       — Adm. Case
[Adm. Matter No. 84-3-886-0. July 7, 1986] — Adm. Matter No.
(G.R. No. 64559, July 7, 1986)           — parentheses both sides
[G.R. No. 63559, May 30, 1986]           — comma before date
```

Consolidated cases: vol226_case_45 at line 18707 has two brackets on lines 18708 and 18714; vol226_case_47 has a similar pattern.

#### `regex_improve/detection/boundary_fsm.py`

**Module-level regex constants:**
```python
RE_DIVISION = re.compile(
    r'^(EN\s+BANC|(?:FIRST|SECOND|THIRD)\s+DIVIS[IO]+N)\s*$',
    re.IGNORECASE
)
```

For `RE_CASE_BRACKET` — must match all variants above. Approach: match the opening bracket char `[\[\(\{]`, then the case type prefix (`G.R. No` / `A.M. No.` / `Adm. Matter` / `Adm. Case`), then the case number, then separator, then date, then closing bracket `[\]\)\}]`. The regex should capture three groups: (1) full case type + number text, (2) date text.

Design the regex carefully — test it against every bracket variant listed above. The case number portion can contain: digits, hyphens, slashes, ampersands, spaces, periods, and letters (e.g., "L-44570", "R-278-RTJ & R-309-RTJ", "84-3-886-0"). Use a non-greedy match: `([\w\-/&\s\.]+?)` stopping before the date.

**Data classes:**
```python
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
```

**Class `CaseBoundaryDetector`:**

Constructor: takes `VolumePreprocessor`.

Method `detect() -> list[CaseBoundary]`:

FSM states:
- `SEEKING` — looking for a division header on a non-noise content line
- `EXPECTING_BRACKET` — found division header, now looking for a case bracket within the next 5 non-noise lines. If 5 lines pass without a bracket match, revert to `SEEKING` (was likely body text mentioning "EN BANC")
- `FOUND_BRACKET` — found first bracket, check next 3 non-noise non-blank lines for a second bracket (consolidated case). If found, add as `group=1`. Then transition to `SEEKING` for the next case.

After detecting all boundaries, set `end_line` for each:
- `boundaries[i].end_line = boundaries[i+1].start_line - 1`
- Last case: `end_line = preprocessor.loader.total_lines`

For extracting case_number text from the bracket: the full bracket contains both the case type prefix and number, then a separator, then the date. To get just the case_number text (e.g., "G.R. No. 50545"), find the position of the date within the bracket line and take everything from the opening bracket content to the separator before the date. The `start_char` and `end_char` should point to the case_number text's position in the volume (use `loader.line_col_to_char()` + column offset within the line).

**`if __name__ == "__main__"` test block:**
- Load `downloads/Volume_226.txt` via `VolumePreprocessor`
- Run `detect()`
- Print: total boundaries found
- Print first 5 boundaries: `(start_line, division, case_numbers, date)`
- Print consolidated case boundaries
- Assert: 72 boundaries found
- Assert: first boundary at line 421 with case_number text containing "50545"
- Assert: boundary near line 18707 has 2 case_numbers (consolidated)
- Assert: boundary at line 2902 detects `{Adm. Matter...}` bracket

**Constraints:**
- `RE_DIVISION` must match `FIRST DIVISLON` (OCR error at line 20420). The pattern `DIVIS[IO]+N` handles DIVISION, DIVISLON, DIVISIION.
- Do NOT parse the date into a datetime. Store raw text. Date parsing is for T5 (OCR correction).
- The bracket regex must NOT match case number citations in body text (e.g., `G.R. No. 65856, January 17, 1986` appearing mid-paragraph at line 510). The key difference: case header brackets are on their own line (or the line starts with the bracket). Body citations appear mid-line and lack the `[({` prefix. Use `^` anchor or check that the bracket starts near the beginning of the line (column < 5).
- TOC lines (pages 1-17, roughly lines 1-420) also contain case references. The FSM naturally avoids these because they don't have division headers immediately preceding them. No special handling needed.
- Do NOT import from gui/ directly — use the preprocessor.

---

### T3: Section Extractor

**Status:** DONE
**Review notes:** 96.7% F1 (953 TP, 29 FP, 37 FN) against 72-case ground truth. Perfect (100% F1): division, start_of_case, counsel, doc_type, start_opinion. Near-perfect (98-99%): case_number, date, ponente, start_syllabus, start_decision. Good (93-97%): end_syllabus (96.5%), parties (95.9%), votes (94.4%), end_decision (93.1%). Known remaining issues: (a) end_of_case at 81.9% F1 — cascading from imprecise end boundary, (b) votes text includes noise lines in multi-line char spans (53/68 text match), (c) case_67 start_syllabus missed ("SYILABUS" OCR — T5 fix), (d) ponente case_59 missed (1 FN). All handled by T5/T6/T7.
**Depends on:** T2
**Files to create:**
- `regex_improve/detection/section_extractor.py`

**Description:**
Given case boundaries from the FSM, extract all 16 annotation labels within each case. Processes each case as a sequential scan through its content lines, following the known section ordering.

#### Section ordering (from ground truth analysis)

```
division header (start_of_case)
  → [G.R. No. ... Date] bracket (case_number + date)
  → [optional: second bracket for consolidated case]
  → party names block (parties)
  → SYLLABUS (start_syllabus)
  → syllabus body
  → last line of syllabus (end_syllabus)
  → [optional: APPEARANCES OF COUNSEL → counsel names (counsel)]
  → DECISION or RESOLUTION (doc_type)
  → SURNAME, J.: (ponente) or PER CURIAM:
  → first line of opinion body (start_decision)
  → opinion body
  → SO ORDERED. (end_decision)
  → justice concurrence list (votes)
  → [optional: SURNAME, C.J., concurring/dissenting: (start_opinion)]
  → [optional: opinion body → last line (end_opinion)]
  → last annotation in case (end_of_case)
```

#### `regex_improve/detection/section_extractor.py`

**Module-level regex constants:**
```python
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
```

**Data class:**
```python
@dataclass
class ExtractedCase:
    case_id: str
    annotations: list[Annotation] = field(default_factory=list)
    confidence: float = 1.0
    notes: str = ""
```

**Class `SectionExtractor`:**

Constructor: takes `VolumePreprocessor`.

Method `extract_all(self, boundaries: list[CaseBoundary]) -> list[ExtractedCase]`:
- Iterate over boundaries with enumerate to generate case_ids: `vol{N}_case_{i}`
- For each boundary, call `_extract_case()`

Method `_extract_case(self, boundary: CaseBoundary, case_id: str) -> ExtractedCase`:

Process the case line by line using `self.preprocessor.get_content_lines(start, end)`. Use a state variable to track which section we're in.

**Extraction steps (in order):**

1. **start_of_case** — Line = `boundary.start_line`, text = `boundary.division_text`. Create Annotation.

2. **division** — Same line and text as start_of_case. Create separate Annotation with identical coordinates.

3. **case_number** — From `boundary.case_numbers`. For each `CaseNumber`, create an Annotation with `label="case_number"`, `text=cn.text`, `group=cn.group`, and char offsets from the CaseNumber object.

4. **date** — From `boundary.date_text`, offsets from `boundary.date_start_char/end_char`.

5. **parties** — Scan from the line AFTER the last case bracket line. Collect all non-blank content lines until hitting a line matching `RE_SYLLABUS` or `RE_DOC_TYPE` (whichever comes first). Join collected lines with `\n`. Trim leading/trailing blank lines from the collected text.
   - For **consolidated cases** (boundary has 2+ case_numbers): there are separate party blocks. The first party block ends where the second bracket line is. The second party block starts after the second bracket. Assign `group=0` to the first block, `group=1` to the second.
   - For **non-consolidated cases**: `group=0`.
   - **Critical:** use `self.preprocessor.loader.text[start_char:end_char]` to get the exact text (preserves original newlines and spacing).

6. **start_syllabus** — Scan for `RE_SYLLABUS`. If found, text = "SYLLABUS". If not found (modern volumes), skip steps 6-7.

7. **end_syllabus** — Scan forward from start_syllabus. Find the LAST non-blank content line before the first occurrence of `RE_COUNSEL_HEADER` or `RE_DOC_TYPE`. That line's text is end_syllabus.

8. **counsel** — Scan for `RE_COUNSEL_HEADER`. If found, the span starts at that header line and extends through all subsequent non-blank lines until hitting `RE_DOC_TYPE`. The annotation text includes the header itself (e.g., "APPEARANCES OF COUNSEL\n\nRoldan B. Dalman for petitioner."). Use `loader.text[start_char:end_char]` for exact text. If not found, skip (counsel is optional — absent in 34/72 Vol 226 cases).

9. **doc_type** — Scan for `RE_DOC_TYPE`. Text = the matched text (e.g., "DECISION", "RESOLUTION"). For spaced variants like "D E C I S I O N", store the text as it appears in the volume.

10. **ponente** — Scan the 1-3 non-blank content lines after the doc_type line.
    - If `RE_PONENTE` matches: extract group 1 (the surname portion). The annotation text is the surname only (e.g., "GUTIERREZ, JR." not "GUTIERREZ, JR., J.:").
    - If `RE_PER_CURIAM` matches: text = "PER CURIAM".
    - If neither matches within 3 lines: ponente is absent (2 cases in Vol 226).

11. **start_decision** — First non-blank content line after the ponente line (or after doc_type if no ponente). Text = full text of that line.

12. **end_decision** — Scan forward from start_decision for `RE_SO_ORDERED`. Also check for variant endings:
    - Lines ending with pattern `is (ACQUITTED|DISMISSED|AFFIRMED)\.\s*No costs\.`
    - `This decision is immediately executory.`
    - `It is so ordered.` (case-insensitive)
    If no match found by end_line, use the last content line before the votes block.

13. **votes** — Lines immediately after end_decision. Scan from `end_decision_line + 1`. Collect non-blank content lines until:
    - A line matches `RE_SEPARATE_OPINION`, OR
    - `end_line` is reached
    Join with `\n`. The votes block includes notes like "Teehankee, C.J., files a separate opinion..." — those are part of votes. The break: a NEW non-blank line starting with a SURNAME + ", C.J./J., concurring/dissenting:" starts the opinion.

14. **start_opinion** — If `RE_SEPARATE_OPINION` matched after votes, record it. Text = full line.

15. **end_opinion** — Last non-blank content line before `end_line` (or before the next `start_opinion` if multiple opinions). Text = full line text.

16. **end_of_case** — The last annotation position:
    - If opinion exists: same position as end_opinion.
    - If no opinion: same position as the last line of votes.
    Text = text of that line.

**Helper method `_make_annotation()`:**
```python
def _make_annotation(self, label: str, text: str,
                     start_line: int, end_line: int,
                     start_char: int = None, end_char: int = None,
                     group: int | None = None) -> Annotation:
    """Create Annotation with all coordinate fields.

    If start_char/end_char not provided, compute from line numbers:
    - start_char: find `text` (first 40 chars) within the line to get column, then
      loader.line_col_to_char(start_line, col)
    - end_char: start_char + len(text) for single-line, or
      loader.line_col_to_char(end_line, len(end_line_text)) for multi-line

    For multi-line annotations (parties, counsel, votes):
    - Prefer using loader.text[start_char:end_char] to verify the text matches.
    - start_page, end_page from loader.get_page()
    """
```

**`if __name__ == "__main__"` test block:**
- Load Volume_226.txt, detect boundaries, extract all cases
- Print: total cases, per-label annotation counts
- Print case 0 annotations in detail
- Spot-check case 0: `start_of_case` text = "SECOND DIVISION" at line 421, `case_number` = "G.R. No. 50545", `date` = "May 23, 1986", `ponente` = "GUTIERREZ, JR.", `doc_type` = "DECISION", `end_decision` = "SO ORDERED."

**Constraints:**
- Multi-line annotation text (parties, counsel, votes) must be the EXACT text from the volume file. Use `self.preprocessor.loader.text[start_char:end_char]` — do NOT reconstruct by joining lines (that may add/remove whitespace).
- For ponente: extract ONLY the surname. Ground truth stores "GUTIERREZ, JR." not "GUTIERREZ, JR., J.:".
- For start_of_case and division: create TWO separate Annotations with identical coordinates (they share the same text and position in the ground truth).
- Do NOT strip trailing periods from end_decision. "SO ORDERED." includes the period.
- For consolidated cases where parsing parties per group is too complex: implement the simple case first (all parties as group=0), add a `# TODO: split consolidated parties by group` comment. Getting the boundary right is more important than the group assignment.
- Skip any section that's not found — don't crash. Missing sections are expected (34 cases lack counsel, 2 lack ponente, 66 lack separate opinions).

---

### T4: Standalone Scorer

**Status:** DONE
**Review notes:** 94.5% micro-averaged F1 (P=0.9491, R=0.9414) on Volume 226 ground truth. Perfect F1 (1.000): start_of_case, division, doc_type, start_opinion. Near-perfect (>0.97): case_number, date, parties, start_syllabus, ponente, start_decision. Good: end_syllabus (0.965), end_decision (0.931). Weaker: votes (0.792), end_of_case (0.819), end_opinion (0.667), counsel (0.816). 40/72 cases are perfect matches. Scorer is fully standalone with zero external dependencies. CLI works: `python -m detection.scorer --predicted pred.json --ground-truth gt.json [--iou 0.8] [--json]`.
**Depends on:** None (reads JSON files only)
**Files created:**
- `regex_improve/detection/scorer.py`

**Description:**
IoU-based span matching scorer. Reads predicted and ground truth JSON files (both in format_version=2 schema), compares annotations per label, and outputs precision/recall/F1. Completely independent from the GUI's `evaluation.py`.

#### `regex_improve/detection/scorer.py`

**Constants:**
```python
POSITION_LABELS = {
    "start_of_case", "start_syllabus", "start_decision",
    "end_decision", "start_opinion", "end_opinion", "end_of_case"
}
GROUPED_LABELS = {"case_number", "parties"}
ALL_LABELS = [
    "start_of_case", "case_number", "date", "division", "parties",
    "start_syllabus", "end_syllabus", "counsel", "ponente", "doc_type",
    "start_decision", "end_decision", "votes", "start_opinion",
    "end_opinion", "end_of_case"
]
```

**Functions:**

1. `compute_iou(a_start, a_end, b_start, b_end) -> float` — Intersection over Union for two character spans. Returns 0.0 if no overlap, 1.0 if identical. Handle edge case where union=0.

2. `match_spans(gt_anns, pred_anns, iou_threshold, is_position_label) -> tuple[int, int, int]` — Greedy matching: for each GT annotation, find the best IoU prediction. Each prediction matches at most one GT. For position labels, any overlap (IoU > 0) counts as a match. For content labels, IoU >= threshold required. Returns (TP, FP, FN).

3. `match_grouped_spans(gt_anns, pred_anns, iou_threshold) -> tuple[int, int, int]` — For grouped labels (case_number, parties). First try matching by group index (gt group 0 → pred group 0). If groups don't align, fall back to best-IoU matching. Returns (TP, FP, FN).

4. `score_volume(predicted_path, ground_truth_path, iou_threshold=0.8) -> dict` — Main scoring function.
   - Load both JSONs
   - Match cases between predicted and ground truth. Strategy: for each GT case with annotations, find the predicted case whose `start_of_case` annotation `start_char` is closest. This handles case_id mismatches.
   - Skip GT cases with 0 annotations (vol226_case_7 and vol226_case_46).
   - For each matched case pair, for each label: collect GT and predicted annotations, run appropriate matcher, accumulate TP/FP/FN.
   - Handle missing labels: if GT has label X but prediction doesn't → FN. If prediction has label X but GT doesn't → FP. If neither has it → no effect.
   - Compute per-label P/R/F1 and micro-averaged aggregates.

   Returns:
   ```python
   {
       "per_label": {
           "start_of_case": {"precision": float, "recall": float, "f1": float, "tp": int, "fp": int, "fn": int},
           ...
       },
       "micro_avg": {"precision": float, "recall": float, "f1": float},
       "per_case": {
           "vol226_case_0": {
               "matched_labels": ["start_of_case", "case_number", ...],
               "missed_labels": [...],
               "extra_labels": [...]
           },
           ...
       }
   }
   ```

5. CLI entry point in `if __name__ == "__main__"`:
   ```
   python -m detection.scorer --predicted pred.json --ground-truth gt.json [--iou 0.8] [--json]
   ```
   Default output: formatted table. With `--json`: machine-readable JSON to stdout.

**Constraints:**
- Do NOT import from gui/ or from other detection/ modules. Scorer is fully standalone — only reads JSON.
- Do NOT use `openai` or `rapidfuzz`. This module has zero external dependencies (stdlib + json only).
- Case matching by `start_char` proximity must handle the edge case where predicted has more or fewer cases than GT. Unmatched GT cases count as all-FN. Unmatched predicted cases count as all-FP.
- P/R/F1 computation: if TP+FP=0, precision=0. If TP+FN=0, recall=0. If P+R=0, F1=0.

---

### T5: OCR Post-Correction

**Status:** DONE
**Review notes:** All 5 corrector functions pass spec assertions. `correct_case_number`: comma→period works. `correct_division`: DIVISLON/DIVISIION→DIVISION works, only applies for known division names. `correct_date`: period→comma and bracket digits ([986→1986) work. `correct_ponente`: fuzzy match via rapidfuzz at score_cutoff=85 (TEEWMHANKEE→TEEHANKEE at 90%), PER CURIAM normalization, exact matches unchanged. `correct_end_decision`: SOORDERED.→SO ORDERED., trailing comma→period. `correct_annotations` dispatcher routes by label, skips parties/votes/counsel/body text, creates copies (no mutation). Minor nit: redundant `import re` on line 86 (already at top).
**Depends on:** None (standalone corrections)
**Files created:**
- `regex_improve/detection/ocr_correction.py`

**Description:**
Rule-based correction of known OCR errors in extracted annotations. Each correction is logged for auditing.

#### `regex_improve/detection/ocr_correction.py`

**Master justice name list (1986–2024, starting with Vol 226 names):**
```python
KNOWN_JUSTICES = [
    "ABAD SANTOS", "ALAMPAY", "CRUZ", "FERIA", "FERNAN",
    "GUTIERREZ, JR.", "MELENCIO-HERRERA", "NARVASA", "PARAS",
    "TEEHANKEE", "YAP",
    # Extend as more volumes are processed
]
```

**Data class:**
```python
@dataclass
class Correction:
    field_label: str    # which annotation label was corrected
    original: str       # original text
    corrected: str      # corrected text
    rule: str           # which rule triggered this
```

**Correction functions** — each takes raw text, returns `(corrected_text, list[Correction])`:

1. `correct_case_number(text)` — Fix `G.R. No,` → `G.R. No.` (comma to period).

2. `correct_date(text)` — Fix period-for-comma after day (`May 30. 1986` → `May 30, 1986`). Fix bracket digits (`[986` → `1986`, `(986` → `1986`).

3. `correct_division(text)` — Fix `DIVISLON` → `DIVISION`, `DIVISIION` → `DIVISION`. Use regex replacement: `re.sub(r'DIVIS\w+N', 'DIVISION', text)` but only if the result is a known division name.

4. `correct_ponente(text)` — Fuzzy match against `KNOWN_JUSTICES` using `rapidfuzz.process.extractOne(text, KNOWN_JUSTICES, score_cutoff=85)`. If match found, return the known justice name. Also normalize `PER CURIAM,;:` → `PER CURIAM`. If no match above 85% similarity, leave unchanged.

5. `correct_end_decision(text)` — Fix `SOORDERED.` → `SO ORDERED.`, `SO ORDERED,` → `SO ORDERED.`.

**Dispatcher:**
```python
def correct_annotations(annotations: list[dict]) -> tuple[list[dict], list[Correction]]:
    """Apply correction rules based on annotation label.
    Returns new list of annotation dicts (with corrected text) + correction log.
    Does NOT modify the original dicts — creates copies."""
```

**`if __name__ == "__main__"` test block:**
- Test each corrector with known errors
- Assert: `correct_case_number("G.R. No, 73155")` → `("G.R. No. 73155", [Correction(...)])`
- Assert: `correct_division("FIRST DIVISLON")` → `("FIRST DIVISION", [...])`
- Assert: `correct_end_decision("SOORDERED.")` → `("SO ORDERED.", [...])`
- Assert: `correct_ponente("TEEWMHANKEE")` → `("TEEHANKEE", [...])`
- Assert: `correct_ponente("GUTIERREZ, JR.")` → `("GUTIERREZ, JR.", [])` (no change needed)

**Constraints:**
- Install `rapidfuzz` — add to requirements.txt: `rapidfuzz>=3.0.0`
- Corrections modify ONLY the `text` field, NOT char offsets. The corrected text represents what SHOULD be there; offsets still point to the original position.
- Do NOT over-correct. Unknown ponente names stay as-is. Only correct when confidence is high (>85% fuzzy match).
- Do NOT correct parties, votes, counsel, or body text — too variable, corrections would introduce errors.
- Log every correction. The audit trail is essential for debugging.

---

### T6: Confidence Scorer

**Status:** TODO
**Depends on:** T5 (imports KNOWN_JUSTICES)
**Files to create:**
- `regex_improve/detection/confidence.py`

**Description:**
Score each extracted case's quality to decide which cases need LLM re-extraction. Cases scoring below 0.7 are flagged for the LLM fallback.

#### `regex_improve/detection/confidence.py`

**Constants:**
```python
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
PARTIES_LEN_RANGE = (50, 2000)
VOTES_LEN_RANGE = (20, 500)
```

**Data class:**
```python
@dataclass
class ConfidenceResult:
    score: float                # 0.0 to 1.0
    checks: dict[str, float]   # individual check name → score
    flags: list[str]           # human-readable issue descriptions
```

**Function `score_case(annotations: list[dict], known_justices: list[str] = None) -> ConfidenceResult`:**

Weighted checks:
1. **required_labels_present** (weight 0.3): count of found required labels / total required labels.
2. **parties_length** (weight 0.1): 1.0 if any parties annotation has length in (50, 2000), else 0.0.
3. **votes_length** (weight 0.1): 1.0 if any votes annotation has length in (20, 500), else 0.0.
4. **ponente_known** (weight 0.1): 1.0 if ponente text fuzzy-matches a known justice (>85%), 0.5 if "PER CURIAM", 0.0 if unknown/missing. Use rapidfuzz if available, else skip check (return 0.5).
5. **ordering_correct** (weight 0.2): 1.0 if all present labels appear in `LABEL_ORDER` by `start_char`. 0.0 if any is out of order. Only checks labels that are present — missing labels are ignored.
6. **no_overlaps** (weight 0.1): 1.0 if no pair of annotations has overlapping char ranges. 0.0 if any do.
7. **date_valid** (weight 0.1): 1.0 if date text matches `Month DD, YYYY` pattern (with lenient parsing). 0.0 otherwise.

Final score = sum(weight × check) for all 7 checks.

**Function `score_all_cases(cases, known_justices, threshold=0.7) -> tuple[list, list]`:**
Split cases into high-confidence and low-confidence lists based on threshold.

**`if __name__ == "__main__"` test block:**
- Load ground truth annotations, score each case. All should score >= 0.8 (they're human-annotated).
- Create a deliberately broken case (missing case_number, out-of-order labels) and verify it scores < 0.5.

**Constraints:**
- Import `KNOWN_JUSTICES` from `detection.ocr_correction`. If import fails, use empty list.
- If rapidfuzz not installed, skip ponente check (use 0.5 fallback). Print warning once.
- The ordering check must handle the ground truth quirk where `date` annotations sometimes appear before `division` (both are on the same/adjacent lines). Allow labels with the same `start_char` to be in any order.

---

### T7: LLM Fallback (DeepSeek V3)

**Status:** TODO
**Depends on:** T6
**Files to create:**
- `regex_improve/detection/llm_fallback.py`

**Description:**
DeepSeek V3 API integration for re-extracting uncertain labels on low-confidence cases. Uses OpenAI-compatible API. Budget-tracked with $5 total limit.

#### `regex_improve/detection/llm_fallback.py`

**Configuration:**
```python
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
```

**`get_client() -> OpenAI`:** Read `DEEPSEEK_API_KEY` from environment. Raise `ValueError` with clear message if not set.

**`BudgetTracker` dataclass:**
- `total_budget: float = 5.00`
- `input_rate: float = 0.27e-6` ($/token)
- `output_rate: float = 1.10e-6` ($/token)
- `total_input_tokens: int = 0`
- `total_output_tokens: int = 0`
- Properties: `total_cost`, `budget_remaining`
- Methods: `can_afford(est_input, est_output) -> bool`, `record_usage(input, output)`

**System prompt:**
```
You are extracting structured fields from Philippine Supreme Court case text.
Given the raw text of a court case, extract the requested fields as JSON.

Output format:
{
  "labels": [
    {
      "label": "<label_name>",
      "text": "<exact text from the input — include OCR errors as-is>",
      "start_offset": <0-based char offset within the provided text>,
      "end_offset": <0-based char offset (exclusive)>
    }
  ]
}

Rules:
- Extract the EXACT text as it appears (preserve OCR errors, original spacing).
- Offsets are character positions within the text you receive (0-based).
- For multi-line fields (parties, votes), include newline characters in the text.
- For ponente, extract ONLY the surname (e.g., "GUTIERREZ, JR." not "GUTIERREZ, JR., J.:").
- If a field is not present in the text, omit it from the output.
```

**`extract_with_llm(case_text, labels_to_extract, existing_labels, budget, client=None) -> list[dict] | None`:**
1. Estimate tokens: `len(case_text) // 4 + 500` (rough estimate for system+user prompt)
2. Check `budget.can_afford()`. If not, log warning, return None.
3. Build user prompt: include `case_text`, list which labels to extract, and provide existing labels as context.
4. Call `_call_with_retry(client, messages)`
5. Parse JSON response. Extract the `labels` array. Convert each to annotation dict format (convert `start_offset`/`end_offset` from case-relative to volume-relative using the case's `start_char`).
6. Record usage from response.
7. Return list of annotation dicts, or None on failure.

**`_call_with_retry(client, messages, max_retries=3)`:**
- Call `client.chat.completions.create(model=DEEPSEEK_MODEL, messages=messages, temperature=0.0, response_format={"type": "json_object"})`
- On rate limit errors, retry with exponential backoff: sleep 1s, 2s, 4s.
- On other errors, raise.

**`if __name__ == "__main__"` test block:**
- Check for DEEPSEEK_API_KEY. If not set, print message and exit.
- Load Volume_226.txt, extract case 0 text (lines 421-703).
- Call `extract_with_llm()` requesting `["parties", "votes"]`.
- Print returned labels and budget usage.

**Constraints:**
- `openai>=1.0.0` is required. Add to requirements.txt.
- `DEEPSEEK_API_KEY` must be set. Pipeline fails with `ValueError` if missing.
- Temperature MUST be 0.0.
- Use `response_format={"type": "json_object"}` for structured output.
- If budget is exhausted: log warning to stderr, return None (do NOT raise). Pipeline continues with regex-only results.
- Do NOT send entire volume text. Only send the specific case's text.
- Log every API call: case_id, input tokens, output tokens, cost, labels requested.

---

### T8: Pipeline Orchestrator + CLI

**Status:** TODO
**Depends on:** T1, T2, T3, T4, T5, T6, T7
**Files to create:**
- `regex_improve/detection/pipeline.py`
- `regex_improve/detection/__main__.py`

**Description:**
Wire all stages together. CLI entry point for single-volume and batch processing.

#### `regex_improve/detection/pipeline.py`

**`process_volume(volume_path, output_path=None, llm_budget=5.0, confidence_threshold=0.7) -> dict`:**

Steps:
1. **Preprocess**: `VolumePreprocessor().load(volume_path)`
2. **Boundaries**: `CaseBoundaryDetector(preprocessor).detect()`
3. **Extract**: `SectionExtractor(preprocessor).extract_all(boundaries)`
4. **OCR correct**: For each case, call `correct_annotations()` on its annotation dicts. Log corrections.
5. **Confidence**: Call `score_all_cases()` to split into high/low confidence.
6. **LLM fallback**: For each low-confidence case:
   - Determine which labels to re-extract (those that triggered low scores).
   - Get case text from `preprocessor.loader.text[start_char:end_char]`.
   - Call `extract_with_llm()`.
   - Merge: LLM results override regex results for re-extracted labels only.
7. **Assemble**: Build format_version=2 JSON. Set `status="auto_extracted"`, `notes="confidence: X.XX"`.
8. **Write**: If output_path provided, write JSON. Return the dict.

Print summary: `"Processed N cases: M high-confidence, K sent to LLM, $X.XX spent"`

**`process_batch(volume_dir, output_dir, volume_range=(226,961), llm_budget=5.0, confidence_threshold=0.7) -> dict`:**
- Find all `Volume_NNN.txt` files where NNN is in range.
- Shared `BudgetTracker` across all volumes.
- Process each volume, write `Volume_NNN_predicted.json` to output_dir.
- Print progress after each volume.
- Return summary dict.

#### `regex_improve/detection/__main__.py`

CLI:
```
python -m detection <input> [-o OUTPUT] [--budget BUDGET] [--threshold THRESHOLD] [--range START-END] [--score GROUND_TRUTH]
```

- `<input>`: volume .txt file (single mode) or directory (batch mode)
- `-o`: output path (single) or directory (batch). Defaults: `<input>.predicted.json` or `<input>/predictions/`.
- `--budget`: LLM budget in USD (default 5.00)
- `--threshold`: confidence threshold (default 0.7)
- `--range`: volume range for batch, e.g., `226-961`
- `--score`: optional ground truth path — run scorer after extraction and print results

Ensure `regex_improve/` is on sys.path for imports to work.

**Constraints:**
- Runnable as: `cd regex_improve && python -m detection ../downloads/Volume_226.txt`
- Output JSON must be loadable by the annotation GUI (format_version=2).
- `status` = "auto_extracted" for all machine-generated cases.
- LLM failure must NOT crash the pipeline. Fall back to regex results with warning.
- Print final summary to stdout.
- If `--score` is provided, import and call `scorer.score_volume()`, print the table.

---

### T9: Integration Tests

**Status:** TODO
**Depends on:** T8
**Files to create:**
- `regex_improve/detection/tests/__init__.py`
- `regex_improve/detection/tests/test_pipeline.py`

**Description:**
End-to-end validation against Volume 226 ground truth.

#### `regex_improve/detection/tests/test_pipeline.py`

Uses `unittest`. `setUpClass` runs the pipeline once on Volume_226.txt (without LLM — mock or skip) and stores results for all test methods.

**Test methods:**

1. `test_case_count` — Detected cases == 72 (matching ground truth annotated cases).
2. `test_first_case_start` — First case `start_of_case` at line 421.
3. `test_all_cases_have_required_labels` — Every case has start_of_case, case_number, doc_type.
4. `test_consolidated_case_detected` — At least one case has case_number with group > 0.
5. `test_overall_f1` — Micro-averaged F1 >= 0.90 (using scorer).
6. `test_per_label_f1_minimums` — Each label meets minimum F1:
   - start_of_case: 0.95, case_number: 0.90, date: 0.90, division: 0.95
   - doc_type: 0.95, start_syllabus: 0.95, ponente: 0.88
   - start_decision: 0.88, end_decision: 0.85, parties: 0.75, votes: 0.70
7. `test_output_format` — Output JSON has correct format_version, volumes key, case structure.
8. `test_ocr_corrections_applied` — At least one `G.R. No,` was corrected to `G.R. No.` in OCR correction log.

**Constraints:**
- Tests must work without DEEPSEEK_API_KEY. Use `unittest.skipUnless(os.environ.get("DEEPSEEK_API_KEY"), "no API key")` for LLM-specific tests.
- Clean up test output files in `tearDownClass`.
- Run with: `cd regex_improve && python -m pytest detection/tests/ -v`
- Tests should complete in < 30 seconds (regex-only).

---

## Dependency Graph

```
T1 (preprocess) ──── T2 (boundary FSM) ──── T3 (section extractor) ──┐
                                                                      │
T4 (scorer) ── standalone, no deps ──────────────────────────────────┐│
                                                                     ││
T5 (OCR correction) ── standalone ──── T6 (confidence) ──── T7 (LLM)││
                                                                     ││
                                              T8 (pipeline) ─────────┘│
                                                                      │
                                              T9 (integration tests) ─┘
```

**Parallelizable:** T4, T5 can be built in parallel with T1→T2→T3 chain.

---

## Python Dependencies to Add

Add to `requirements.txt`:
```
rapidfuzz>=3.0.0
openai>=1.0.0
```

---

## File Tree (Final State)

```
regex_improve/
├── detection/
│   ├── __init__.py              # T1
│   ├── __main__.py              # T8
│   ├── preprocess.py            # T1
│   ├── boundary_fsm.py          # T2
│   ├── section_extractor.py     # T3
│   ├── scorer.py                # T4
│   ├── ocr_correction.py        # T5
│   ├── confidence.py            # T6
│   ├── llm_fallback.py          # T7
│   ├── pipeline.py              # T8
│   └── tests/
│       ├── __init__.py          # T9
│       └── test_pipeline.py     # T9
├── gui/                         # [COMPLETE — do not modify]
│   └── ... (all GUI modules)
├── annotate_gui.py
├── improved_regex.py
└── samples/
    └── Volume_*.txt
```
