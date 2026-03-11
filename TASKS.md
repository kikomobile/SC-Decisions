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

**Status:** DONE
**Review notes:** All 7 weighted checks implemented per spec. Handles ground truth quirks: (a) stacked annotations (identical spans, e.g. start_of_case + division) are exempt from overlap check, (b) annotations at the same start_char are grouped and compared using minimum order index (fixes division->case_number false positive). Ponente check returns 0.5 fallback when rapidfuzz unavailable. Test block: ground truth avg=1.0, broken case=0.333 (<0.5), score_all_cases splits correctly. Also fixed redundant `import re` in ocr_correction.py (T5 nit).
**Depends on:** T5 (imports KNOWN_JUSTICES)
**Files created:**
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

**Status:** DONE
**Review notes:** All spec requirements met. `get_client()` reads `DEEPSEEK_API_KEY` from env with clear `ValueError` if missing. `BudgetTracker` with correct rates (0.27e-6 input, 1.10e-6 output), budget check before API calls, returns `None` on exhaustion (no raise). `_call_with_retry` with exponential backoff (1s, 2s, 4s). Temperature 0.0 and `response_format={"type": "json_object"}` enforced. Logs every API call with case_id, tokens, cost. Extra helpers added: `convert_llm_labels_to_annotations` (case-relative→volume-relative offset conversion), `determine_labels_to_re_extract` (maps failed confidence checks to label list) — both useful for T8. Test block validates BudgetTracker, label determination, annotation conversion, and invalid input handling. Actual API test gated on `DEEPSEEK_API_KEY` presence.
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

**Status:** DONE
**Review notes:** Full pipeline runs end-to-end on Volume 226: 72 cases detected, 12 OCR corrections, all 72 high-confidence at 0.7 threshold. LLM integration verified — single API call to DeepSeek returned correct `parties` and `ponente` for case 0 (3190 input, 145 output tokens, $0.001). CLI supports single + batch modes with all spec flags (--budget, --threshold, --range, --score, --skip-llm, --json). Output JSON is format_version=2 with status="auto_extracted". Known minor issues: (a) `process_batch` budget not truly shared — each `process_volume` creates its own BudgetTracker, (b) annotation type mixes Annotation dataclass and dicts after OCR correction step — works at runtime but type hints are inconsistent. Neither affects single-volume processing.
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

**Status:** DONE
**Review notes:** All 9 tests pass in 1.59s. Covers: case count (72), first case start (line 421, SECOND DIVISION), required labels (start_of_case, case_number, doc_type on all 72), consolidated case detection (group > 0), overall F1 >= 0.90, per-label F1 minimums (11 labels checked), output format (format_version=2, volumes, case structure, annotation fields), OCR corrections (12 applied). LLM integration test properly gated with `@unittest.skipUnless(DEEPSEEK_API_KEY)` — ran and passed since key was set. Cleanup in tearDownClass via shutil.rmtree. Minor nit: test_ocr_corrections_applied doesn't hard-assert the comma-to-period fix (prints note instead) — acceptable since the specific OCR error may not always be present.
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

## Correction Tracking Tasks

These tasks add human-review correction tracking to the GUI. When a user imports pipeline predictions and modifies them (fix labels, adjust spans, add missing annotations, delete false positives), the changes are recorded as structured corrections. The corrections file is designed to be fed into Claude/Claude Code for pipeline improvement analysis.

---

### CT-1: Snapshot Baseline on Import + Diff Engine

**Status:** DONE
**Review notes:** CorrectionTracker with deep-copy baseline, 4-type diff engine (removed, added, label_changed, span_adjusted). Test block: 3 corrections detected correctly from mock data (1 label change, 1 span adjustment, 1 addition). Natural sort for case_id ordering. Context extraction with newline escaping. All pipeline tests still pass.
**Depends on:** GUI Import Predictions feature (already implemented in app.py)
**Files to modify:**
- `regex_improve/gui/app.py`
- `regex_improve/gui/file_io.py`
**Files to create:**
- `regex_improve/gui/correction_tracker.py`

**Description:**
When the user imports a predicted.json via "File > Import Predictions...", snapshot the original predictions as a frozen baseline. On every subsequent annotation change (add, remove), compute the diff between the current state and the baseline, and write it to a corrections file.

#### `regex_improve/gui/correction_tracker.py`

**Imports:**
```python
import json
import copy
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from gui.models import Annotation, Case, VolumeData
```

**Data classes:**
```python
@dataclass
class CorrectionEntry:
    case_id: str
    correction_type: str        # "removed", "added", "label_changed", "span_adjusted"
    label: str                  # the annotation label involved
    original: Optional[dict]    # original annotation dict (None for "added")
    corrected: Optional[dict]   # corrected annotation dict (None for "removed")
    context_text: str           # ~200 chars of surrounding volume text for analysis
    start_line: int             # line number for reference
    notes: str = ""             # optional user note

@dataclass
class CorrectionLog:
    volume_name: str
    source_file: str            # path to the predicted.json that was imported
    total_predicted: int        # how many annotations were in the original predictions
    corrections: List[CorrectionEntry] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
```

**Class `CorrectionTracker`:**

Fields:
- `baseline: Optional[VolumeData]` -- deep copy of imported predictions, frozen
- `volume_name: str`
- `source_file: str` -- path to the imported predicted.json
- `volume_text: str` -- full volume text (for extracting context)

Methods:

1. `set_baseline(self, volume_data: VolumeData, source_file: str, volume_text: str)`:
   - Deep copy `volume_data` using `copy.deepcopy()` and store as `self.baseline`
   - Store `source_file` and `volume_text`
   - Store `volume_name = volume_data.volume`

2. `has_baseline(self) -> bool`:
   - Return whether a baseline has been set

3. `compute_diff(self, current: VolumeData) -> CorrectionLog`:
   - Compare `self.baseline` against `current` case by case
   - Match cases by `case_id`
   - For each matched case pair, compare annotations:
     - Use `(label, start_char, end_char)` as the annotation key for matching
     - **Exact match**: annotation exists in both baseline and current with same label, start_char, end_char, text -- no correction needed
     - **Removed**: annotation exists in baseline but not in current (any key) -- `correction_type="removed"` (pipeline false positive)
     - **Added**: annotation exists in current but not in baseline -- `correction_type="added"` (pipeline false negative)
     - **Label changed**: same `(start_char, end_char)` exists in both but with different `label` -- `correction_type="label_changed"`
     - **Span adjusted**: same `label` exists in both, `start_char` or `end_char` within 200 chars of each other but not identical -- `correction_type="span_adjusted"`. Match by closest `start_char` for same label.
   - For unmatched baseline cases (case_id not in current): all annotations are "removed"
   - For unmatched current cases (case_id not in baseline): all annotations are "added"
   - For each correction, extract `context_text`: `volume_text[max(0, start_char-100):min(len(volume_text), end_char+100)]`
   - Compute `summary`:
     ```python
     {
         "total_corrections": int,
         "by_type": {"removed": int, "added": int, "label_changed": int, "span_adjusted": int},
         "by_label": {"parties": int, "ponente": int, ...},  # count per label
         "cases_with_corrections": int,
         "cases_perfect": int  # cases with zero corrections
     }
     ```
   - Return `CorrectionLog`

4. `_get_context(self, start_char: int, end_char: int) -> str`:
   - Return `self.volume_text[max(0, start_char-100):min(len(self.volume_text), end_char+100)]`
   - Replace newlines with `\n` literal for single-line display

**`if __name__ == "__main__"` test block:**
- Create two mock VolumeData objects (baseline and modified)
- Baseline has 3 cases with annotations; modified has 1 annotation removed, 1 added, 1 label changed
- Call `compute_diff()`, print the corrections and summary
- Assert correction counts match expected

**Constraints:**
- Deep copy the baseline on `set_baseline` -- do NOT hold a reference to the live VolumeData
- The diff must handle cases where the user adds entirely new cases or deletes entire cases
- `context_text` must be safe for JSON serialization (escape special characters)
- Do NOT import from detection/ modules -- this is a gui/ module
- Do NOT use Unicode characters in print statements

---

### CT-2: Export Corrections as Analysis-Ready JSON

**Status:** DONE
**Review notes:** "File > Export Corrections..." menu item added to GUI. Snapshots baseline on import via set_baseline(). Export writes structured JSON with summary (by_type, by_label, cases_perfect/corrected), corrections list with original/corrected/context, and embedded analysis_prompt for Claude. Saves to regex_improve/corrections/ directory (created on first export). Import verified, all pipeline tests pass.
**Depends on:** CT-1
**Files to modify:**
- `regex_improve/gui/app.py`
**Files to create:**
- `regex_improve/corrections/` (directory, created on first export)

**Description:**
Add a "File > Export Corrections..." menu item to the GUI. When clicked, compute the diff between baseline predictions and current annotations, then write a structured JSON file designed for Claude/Claude Code analysis.

#### Changes to `regex_improve/gui/app.py`:

1. Import `CorrectionTracker` from `gui.correction_tracker`

2. Add `self.correction_tracker = CorrectionTracker()` in `__init__`

3. In `import_predictions()`, after the volume data is replaced (after line 301 `self.volume_data = pred_volume`), add:
   ```python
   self.correction_tracker.set_baseline(pred_volume, file_path, self.loader.text)
   ```

4. Add menu item "Export Corrections..." in the File menu, after "Import Predictions...":
   ```python
   file_menu.add_command(label="Export Corrections...", command=self.export_corrections)
   ```

5. Add `export_corrections` method:
   - Check that `self.correction_tracker.has_baseline()` -- if not, show warning "Import predictions first, then make corrections, then export."
   - Compute diff: `correction_log = self.correction_tracker.compute_diff(self.volume_data)`
   - If no corrections found, show info "No corrections detected. Predictions match current annotations."
   - Show save dialog with default filename: `{volume_name}_corrections.json` in `regex_improve/corrections/` directory
   - Build the export dict (see format below)
   - Write JSON with `indent=2, ensure_ascii=False`
   - Show info with correction count

#### Export JSON Format:

```json
{
    "format": "correction_log",
    "version": 1,
    "volume_name": "Volume_226.txt",
    "source_predictions": "path/to/Volume_226.predicted.json",
    "summary": {
        "total_predicted_annotations": 850,
        "total_corrections": 23,
        "cases_reviewed": 72,
        "cases_with_corrections": 8,
        "cases_perfect": 64,
        "by_type": {
            "removed": 5,
            "added": 10,
            "label_changed": 3,
            "span_adjusted": 5
        },
        "by_label": {
            "parties": 7,
            "end_of_case": 5,
            "votes": 4,
            "ponente": 3,
            "end_decision": 2,
            "counsel": 2
        }
    },
    "corrections": [
        {
            "case_id": "vol226_case_12",
            "type": "removed",
            "label": "parties",
            "original": {
                "label": "parties",
                "text": "WRONG TEXT CAPTURED...",
                "start_char": 15230,
                "end_char": 15890,
                "start_line": 1205,
                "end_line": 1215
            },
            "corrected": null,
            "context": "...100 chars before...WRONG TEXT CAPTURED......100 chars after..."
        },
        {
            "case_id": "vol226_case_12",
            "type": "added",
            "label": "parties",
            "original": null,
            "corrected": {
                "label": "parties",
                "text": "CORRECT TEXT...",
                "start_char": 15230,
                "end_char": 15500,
                "start_line": 1205,
                "end_line": 1210
            },
            "context": "...surrounding text..."
        },
        {
            "case_id": "vol226_case_30",
            "type": "label_changed",
            "label": "counsel",
            "original": {
                "label": "parties",
                "text": "Atty. Juan dela Cruz for petitioner.",
                "start_char": 34000,
                "end_char": 34035,
                "start_line": 3400,
                "end_line": 3400
            },
            "corrected": {
                "label": "counsel",
                "text": "Atty. Juan dela Cruz for petitioner.",
                "start_char": 34000,
                "end_char": 34035,
                "start_line": 3400,
                "end_line": 3400
            },
            "context": "...surrounding text..."
        }
    ],
    "analysis_prompt": "The following is a correction log from human review of automated extraction results for Philippine Supreme Court case Volume_226.txt. The detection pipeline used regex-based extraction with OCR correction. A human reviewer corrected 23 annotations across 8 cases (out of 72 total). Analyze these corrections to identify: (1) systematic patterns in what the pipeline gets wrong, (2) specific regex patterns or FSM transitions that need updating, (3) labels that would benefit most from improved extraction logic. Focus on actionable suggestions referencing the pipeline source files in regex_improve/detection/."
}
```

**Key design decisions:**

- `analysis_prompt` is embedded in the JSON so the user can paste the entire file content to Claude/Claude Code and get analysis without writing a separate prompt
- `context` provides surrounding text so Claude can see what the pipeline was working with
- `by_label` in summary immediately shows which labels are weakest
- `by_type` shows whether the pipeline is producing more false positives (removed) or false negatives (added)
- `original` + `corrected` side by side makes it easy to see exactly what changed

**`if __name__ == "__main__"` test block in app.py:** Not needed -- test via the GUI.

**Constraints:**
- Create `regex_improve/corrections/` directory on first export (use `mkdir(parents=True, exist_ok=True)`)
- The `analysis_prompt` must include the volume name and correction counts so it's self-contained
- Corrections must be grouped by case_id in the output (all corrections for case_12 together, then case_30, etc.)
- Sort cases by case_id naturally (vol226_case_0 before vol226_case_10)
- Do NOT auto-export on every change -- only on explicit "Export Corrections..." click
- Do NOT modify correction_tracker.py (only import from it)
- Do NOT use Unicode characters in any strings
- The exported file must be valid JSON loadable by `json.load()`

---

### Correction Tracking Dependency Graph

```
CT-1 (tracker + diff engine) ---- CT-2 (export + menu item)
```

CT-1 must be completed first. CT-2 depends on CT-1.

---

### Correction Tracking File Tree

```
regex_improve/
├── gui/
│   ├── correction_tracker.py    # CT-1
│   ├── app.py                   # CT-2 (modified)
│   └── ... (existing modules)
├── corrections/                 # CT-2 (created on first export)
│   └── Volume_NNN_corrections.json
```

---

## Pipeline Fix Tasks (from Volume 227 Correction Analysis)

Human review of Volume 227 (74 cases) found 181 corrections across 43 cases. Analysis identified 6 root causes, prioritized by number of corrections they would fix. These fixes should be applied and re-tested against both Volume 226 ground truth (to prevent regression) and Volume 227 (to verify improvement).

**Validation:** After each fix, run:
```
cd regex_improve
python -m detection ../downloads/Volume_226.txt --score annotation_exports/ground_truth_20260309_144413.json --skip-llm
python -m detection ../downloads/Volume_227.txt --skip-llm
```
Then import the Vol 227 predicted.json into the GUI and spot-check the corrected labels.

---

### FIX-1: Votes Overflow Past Page Breaks

**Status:** TODO
**Estimated impact:** ~28 votes + ~25 end_of_case corrections (29% of all corrections)
**Depends on:** None
**Files to modify:**
- `regex_improve/detection/section_extractor.py`

**Description:**
The votes extraction loop (`section_extractor.py:461-500`) captures all lines from `end_decision_line + 1` up to `boundary.end_line` (the next case's start minus 1), stopping only at `RE_SEPARATE_OPINION`. This means votes absorb `--- Page N ---` markers, `PHILIPPINE REPORTS` headers, volume short titles, footnotes, and even entire subsequent cases when boundaries are missed.

**Root cause in code:**
```python
# section_extractor.py:464-466 — votes includes ALL lines up to boundary.end_line
for line_num, text in lines:
    if line_num >= votes_start_line and line_num <= boundary.end_line:
        votes_lines.append((line_num, text))
```

The `lines` list (from `get_content_lines`) already filters noise, but `--- Page N ---` markers are noise-masked, so they don't appear in `lines`. The real problem is that footnotes, SCRA citations, and next-case headers that survive the noise filter are NOT excluded.

**Fix:**

1. In `_extract_case` (around line 461-500), replace the votes extraction logic. After finding `end_decision_line`, collect votes lines with a **strict termination** strategy:

   ```python
   # Collect votes: lines after end_decision, terminated by:
   # (a) A blank line followed by another blank line (double blank = section break)
   # (b) Any line matching RE_DIVISION or RE_CASE_BRACKET (next case start)
   # (c) Any line matching RE_SEPARATE_OPINION (existing check)
   # (d) Maximum 15 non-blank lines (votes are never longer than ~10 lines)
   ```

2. Implement the termination logic:
   - Start from `end_decision_line + 1`
   - Skip leading blank lines (there's usually 1 blank line between "SO ORDERED." and the concurrence)
   - Collect non-blank lines that look like votes (contain "concur", "dissent", justice names, "JJ.", "J.,", "Chairman", etc.)
   - Stop at the first line that does NOT look like a votes line after the concurrence has started
   - Also stop at any line matching `RE_DIVISION` or `RE_CASE_BRACKET` (imported from `boundary_fsm.py`)
   - Cap at 15 non-blank lines maximum

3. Add a simple votes-content heuristic. A valid votes line typically contains one or more of:
   - Justice surname patterns (all-caps words)
   - "concur" / "dissent" / "dissenting" / "separate opinion"
   - "JJ." / "J.," / "J.:" / "C.J."
   - "Chairman" / "Presiding"
   - "(on leave)" / "(on official leave)" / "(no part)"
   - Footnote markers should NOT be included (lines starting with digits followed by a space, or lines starting with `*` or `"`)

4. After votes extraction, set `end_of_case` to the last line of votes (or `end_decision_line` if no votes found), NOT to `boundary.end_line`.

**Example of the bug:**
```
Original votes (vol227_case_6):
  "Feria (Chairman), Fernan, Alampay, and Gutierrez, Jr, JJ,\nconcur,\n\n--- Page 89 ---\n72\nPHILIPPINE REPORTS\nVda. de Roxas vs. CA"

Corrected votes:
  "Feria (Chairman), Fernan, Alampay, and Gutierrez, Jr, JJ,\nconcur,"
```

**Constraints:**
- Import `RE_DIVISION` and `RE_CASE_BRACKET` from `boundary_fsm` at the top of `section_extractor.py`
- Do NOT change how `boundary.end_line` is set in `boundary_fsm.py` — the fix is entirely in section_extractor
- The `end_of_case` annotation must land on the last line of the current case's content (votes or end_decision), never on the next case's header
- Do NOT use Unicode characters in print statements
- Preserve existing `RE_SEPARATE_OPINION` handling for cases with separate opinions

---

### FIX-2: Missed Case Boundaries from OCR-Corrupted Brackets

**Status:** TODO
**Estimated impact:** ~90 cascading corrections across all label types (50% of all corrections)
**Depends on:** None (can be done in parallel with FIX-1)
**Files to modify:**
- `regex_improve/detection/boundary_fsm.py`

**Description:**
5 cases in Volume 227 were completely missed because `RE_CASE_BRACKET` (`boundary_fsm.py:31-40`) failed to match their opening bracket line. OCR commonly corrupts `[` into `1`, `(`, `{`, or drops it. Lines like `1G.R. No. 12345. July 1, 1986]` or `G.R. No. 12345. July 1, 1986]` (no opening bracket) fail the regex.

**Root cause in code:**
```python
# boundary_fsm.py:31-32 — requires literal opening bracket
RE_CASE_BRACKET = re.compile(
    r'^[\[\(\{]'   # <-- This REQUIRES [, (, or { as first character
    ...
)
```

**Fix:**

1. Make the opening bracket optional in `RE_CASE_BRACKET`. Replace:
   ```python
   r'^[\[\(\{]'
   ```
   with:
   ```python
   r'^[\[\(\{1]?'   # Opening bracket: [, (, {, or OCR-corrupted 1, or missing entirely
   ```

   The `1` covers the common OCR error where `[` is read as `1`. The `?` makes the entire bracket optional, covering the case where OCR drops it.

2. However, making the opening bracket fully optional risks false positives (matching regular text lines that happen to start with "G.R. No."). To prevent this, add a constraint: when the opening bracket is absent, require a closing bracket `]`, `)`, or `}` at the end of the line. Modify the regex:

   ```python
   RE_CASE_BRACKET = re.compile(
       r'^[\[\(\{1]?'                # Opening bracket (optional, tolerates OCR errors)
       r'(?:G\.\s*R\.\s*No[\.\s,]*s?[\.\s,]*|'
       r'A\.\s*M\.\s*No[\.\s,]*s?[\.\s,]*|'
       r'Adm\.\s*(?:Matter|Case)\s*No[\.\s,]*s?[\.\s,]*)'
       r'\s*([\w\-/&\s\.]+?)'        # case number (non-greedy)
       r'[\.\s,]+'                    # separator
       r'(.+)'                        # date text (greedy)
       r'[\]\)\}]'                    # Closing bracket (still required)
       r'.*$',
       re.IGNORECASE
   )
   ```

3. Also add `RE_CASE_BRACKET_NO_CLOSE` as a fallback pattern for lines where BOTH brackets are corrupted/missing but the line clearly contains a G.R. number and date:
   ```python
   RE_CASE_BRACKET_NO_CLOSE = re.compile(
       r'^[\[\(\{1]?'
       r'(?:G\.\s*R\.\s*No[\.\s,]*s?[\.\s,]*|'
       r'A\.\s*M\.\s*No[\.\s,]*s?[\.\s,]*|'
       r'Adm\.\s*(?:Matter|Case)\s*No[\.\s,]*s?[\.\s,]*)'
       r'\s*([\w\-/&\s\.]+?)'
       r'[\.\s,]+'
       r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})',
       re.IGNORECASE
   )
   ```
   Use this as a second attempt in the `EXPECTING_BRACKET` state (line 111) only if the primary `RE_CASE_BRACKET` fails.

4. In the FSM's `EXPECTING_BRACKET` state (`boundary_fsm.py:107-161`), after the primary regex fails, try the fallback:
   ```python
   bracket_match = RE_CASE_BRACKET.match(line_text)
   if not bracket_match:
       bracket_match = RE_CASE_BRACKET_NO_CLOSE.match(line_text)
   if bracket_match:
       # ... existing processing
   ```

**Testing:** After the fix, run the pipeline on Volume 227 and verify that 74 cases are detected (currently 69). The 5 new cases should be: Benguet Consolidated (~p.439), Ibasco (~p.513), People vs. Poyos (~p.518), Royal Lines (~p.587), Cuevas (~p.652).

**Constraints:**
- The primary `RE_CASE_BRACKET` (with closing bracket required) should be tried FIRST to avoid false positives
- The fallback `RE_CASE_BRACKET_NO_CLOSE` requires an explicit month-name date pattern to reduce false matches
- Do NOT change the FSM state transitions — only change what regex is matched
- Run the Volume 226 test after the fix to ensure no regression (should still detect 72 cases)
- Do NOT use Unicode characters in print statements
- Update `_extract_case_number_from_bracket` if needed to handle missing closing brackets

---

### FIX-3: Quoted "SO ORDERED." Triggers False end_decision

**Status:** TODO
**Estimated impact:** ~15 end_decision corrections + cascading votes/end_of_case errors
**Depends on:** None (can be done in parallel with FIX-1 and FIX-2)
**Files to modify:**
- `regex_improve/detection/section_extractor.py`

**Description:**
The end_decision scanner (`section_extractor.py:417-421`) takes the **first** `RE_SO_ORDERED` match in the decision body. Philippine Supreme Court decisions frequently quote lower court orders verbatim, which contain their own "SO ORDERED." or "IT IS SO ORDERED." lines. The pipeline matches the quoted one instead of the actual dispositive ending.

**Root cause in code:**
```python
# section_extractor.py:417-421 — takes FIRST match, breaks immediately
for i, (line_num, text) in enumerate(decision_lines):
    if RE_SO_ORDERED.match(text):
        end_decision_line = line_num
        end_decision_text = text
        break   # <-- This is the bug: should continue to find the LAST match
```

**Fix:**

1. Change the `break` on first `RE_SO_ORDERED` match to continue scanning, keeping track of the **last** match:

   ```python
   # Scan ALL decision lines, keep the LAST "SO ORDERED." match
   for i, (line_num, text) in enumerate(decision_lines):
       if RE_SO_ORDERED.match(text):
           end_decision_line = line_num
           end_decision_text = text
           # Do NOT break — continue to find the last occurrence
       # Also check other ending patterns (keep existing logic for
       # ACQUITTED/DISMISSED/AFFIRMED, "immediately executory", etc.)
       # but these should ALSO use last-match, not first-match
   ```

2. However, the other ending patterns (`is ACQUITTED/DISMISSED`, `immediately executory`, `It is so ordered.`) at lines 423-434 should also be changed to last-match. Simplify: collect all candidate end_decision lines, then pick the **last** one by line number.

3. As an additional safeguard, if both "SO ORDERED." and "It is so ordered." (case-sensitive — the quoted one often has lowercase "is") appear, prefer the one that appears later. The actual dispositive "SO ORDERED." is always the last such marker in the decision.

**Example of the bug:**
```
vol227_case_34:
  FALSE match at line ~16066: "It is SO ORDERED." (inside quoted lower court order)
  REAL match at line 16105:   "SO ORDERED." (actual end of decision)
```

**Constraints:**
- The fix must handle cases with only ONE "SO ORDERED." (common case — no regression)
- The fix must handle cases with ZERO "SO ORDERED." (existing fallback logic at lines 436-449 is unchanged)
- Do NOT use Unicode characters in print statements
- Do NOT modify `RE_SO_ORDERED` regex itself — the matching pattern is correct, only the selection strategy (first vs last) needs to change

---

### FIX-4: Counsel Span Bleeds Past Page Breaks

**Status:** TODO
**Estimated impact:** ~22 counsel corrections
**Depends on:** None
**Files to modify:**
- `regex_improve/detection/section_extractor.py`

**Description:**
The counsel extraction (`section_extractor.py:276-305`) finds "APPEARANCES OF COUNSEL" and extends the span until `RE_DOC_TYPE` is matched. But the counsel block often spans a page break, and the lines between the last attorney line and the doc_type header (page markers, volume headers, short titles) are included in the counsel text because `get_content_lines` already filtered noise — but lines like the next case's short title (`"Marcopper Mining Corp. vs. Garcia"`) survive the noise filter.

**Root cause in code:**
```python
# section_extractor.py:279-283 — scans until RE_DOC_TYPE, nothing else stops it
while counsel_end_idx < len(lines):
    end_line_num, end_text = lines[counsel_end_idx]
    if RE_DOC_TYPE.match(end_text):
        break
    counsel_end_idx += 1
```

**Fix:**

1. Add an early termination heuristic after the counsel header. The counsel block has a predictable structure:
   - Line 1: "APPEARANCES OF COUNSEL" (or "APPEARANCE OF COUNSEL")
   - Lines 2+: Attorney names with "for petitioner/respondent/plaintiff/defendant/appellant/appellee" designations
   - The block ends after the last attorney designation line

2. Replace the simple `while` loop with a smarter scan:

   ```python
   # After finding "APPEARANCES OF COUNSEL", scan for attorney lines.
   # An attorney line typically ends with a legal designation:
   #   "for petitioner.", "for respondents.", "for plaintiff-appellant.", etc.
   # Stop counsel when we hit:
   # (a) RE_DOC_TYPE
   # (b) Two consecutive blank lines
   # (c) A line that matches RE_DIVISION or RE_CASE_BRACKET (next case boundary)
   # (d) 30 lines scanned without finding any "for" designation (safety limit)
   ```

3. Define a regex for attorney designation lines:
   ```python
   RE_COUNSEL_DESIGNATION = re.compile(
       r'for\s+(?:the\s+)?(?:petitioner|respondent|plaintiff|defendant|appellant|appellee|'
       r'accused|complainant|private|intervenor|oppositor)',
       re.IGNORECASE
   )
   ```

4. Track whether we've seen at least one designation line. After seeing one, stop at the first blank line (the designation block is complete). If we never see one (unusual formatting), fall back to the existing `RE_DOC_TYPE` termination but cap at 30 lines.

5. Import `RE_DIVISION` and `RE_CASE_BRACKET` from `boundary_fsm` (may already be imported from FIX-1) and add them as stop conditions.

**Example of the bug:**
```
vol227_case_19 original counsel:
  "APPEARANCES OF COUNSEL\n\nGozon Puno...\nManuel S. Laurel...\n\n--- Page 187 ---\n170 PHILIPPINE REPORTS\nMarcopper Mining Corp. vs. Garcia\n"

Corrected:
  "APPEARANCES OF COUNSEL\n\nGozon Puno...\nManuel S. Laurel for private respondent."
```

**Constraints:**
- Do NOT change the counsel `start_line` — it correctly starts at "APPEARANCES OF COUNSEL"
- Only change the end boundary logic
- The fix must handle counsel blocks with multiple attorneys (2-6 lines is typical)
- The fix must handle counsel blocks with no "for" designations (rare, but possible — fall back to existing behavior with line cap)
- Do NOT use Unicode characters in print statements

---

### FIX-5: Parties Span Absorbs Footnotes from Previous Case

**Status:** TODO
**Estimated impact:** ~14 parties corrections
**Depends on:** None
**Files to modify:**
- `regex_improve/detection/section_extractor.py`

**Description:**
The parties extraction (`section_extractor.py:192-198`) collects all lines between the last case bracket and the first `RE_SYLLABUS` or `RE_DOC_TYPE` match. When footnotes from the previous case appear on the same page (between the previous case's body and the current case's header area), they get absorbed into the parties span.

**Root cause in code:**
```python
# section_extractor.py:193-198 — only stops at SYLLABUS or DOC_TYPE
parties_end_idx = parties_start_idx
while parties_end_idx < len(lines):
    line_num, text = lines[parties_end_idx]
    if RE_SYLLABUS.match(text) or RE_DOC_TYPE.match(text):
        break
    parties_end_idx += 1
```

**Fix:**

1. Add stop conditions for footnote content. Parties blocks end with a legal designation like "respondents.", "respondent.", "petitioners.", "petitioner.", "plaintiff-appellant.", "defendant-appellee.", etc. After seeing such a line, the next blank line should terminate the parties block.

2. Define a parties termination regex:
   ```python
   RE_PARTIES_END = re.compile(
       r'(?:respondents?|petitioners?|plaintiffs?|defendants?|appellants?|appellees?|'
       r'accused-appellants?|intervenors?|oppositors?)\s*[.,;]*\s*$',
       re.IGNORECASE
   )
   ```

3. Update the parties scanning loop:
   ```python
   seen_designation = False
   while parties_end_idx < len(lines):
       line_num, text = lines[parties_end_idx]
       if RE_SYLLABUS.match(text) or RE_DOC_TYPE.match(text):
           break
       if RE_PARTIES_END.search(text):
           seen_designation = True
           parties_end_idx += 1
           # After the designation line, skip trailing blank lines and stop
           while parties_end_idx < len(lines) and not lines[parties_end_idx][1].strip():
               parties_end_idx += 1
           break
       # Also stop at footnote-like lines (start with digit+space or quotation mark)
       if seen_designation and not text.strip():
           break
       parties_end_idx += 1
   ```

4. Additionally, stop if a line starts with a footnote indicator:
   - Line starts with `"` (opening quote — footnote citation)
   - Line starts with a digit followed by a space and then text (footnote number)
   - Line starts with `*` (asterisk footnote)

**Example of the bug:**
```
vol227_case_27 original parties:
  "FELISA RIVERA...respondents.\n\n\" Bernas, Constitutional Rights and Duties, Vol. I, 1974 Edition, p. 100."

Corrected:
  "FELISA RIVERA...respondents."
```

**Constraints:**
- The fix must handle parties blocks that span multiple lines (typical: 3-15 lines)
- The fix must handle consolidated cases with multiple party groups
- Do NOT stop at every period — only at lines ending with a legal designation
- If no designation is found (unusual formatting), fall back to existing `RE_SYLLABUS`/`RE_DOC_TYPE` stop
- Do NOT use Unicode characters in print statements

---

### FIX-6: Page Number Bug — get_page() Called with Char Offset Instead of Line Number

**Status:** TODO
**Estimated impact:** All annotations (cosmetic — wrong page numbers in every annotation)
**Depends on:** None
**Files to modify:**
- `regex_improve/detection/section_extractor.py`

**Description:**
`VolumeLoader.get_page()` expects a **1-based line number**, but `section_extractor.py` passes **character offsets** at 6 call sites (lines 119, 120, 141, 142, 611, 612). Since char offsets are large numbers (e.g., 158930), `get_page()` treats them as line numbers, and bisect returns the last page break, giving page 730 (the volume index page) for nearly every annotation.

**Root cause in code:**
```python
# section_extractor.py:119-120 — passes start_char (a char offset) to get_page (expects line number)
start_page = self.loader.get_page(cn.start_char)    # BUG: cn.start_char is a char offset
end_page = self.loader.get_page(cn.end_char - 1)    # BUG: cn.end_char is a char offset

# volume_loader.py:148 — get_page expects a 1-based line number
def get_page(self, line: int) -> int:
    """Get the page number for a 1-based line number."""
```

**Fix:**

1. At all 6 call sites in `section_extractor.py`, convert the char offset to a line number first, then call `get_page`:

   Replace (lines 119-120):
   ```python
   start_page = self.loader.get_page(cn.start_char)
   end_page = self.loader.get_page(cn.end_char - 1)
   ```
   With:
   ```python
   start_page = self.loader.get_page(self.loader.char_to_line(cn.start_char))
   end_page = self.loader.get_page(self.loader.char_to_line(cn.end_char - 1))
   ```

2. Apply the same fix at lines 141-142 (date page numbers):
   ```python
   start_page = self.loader.get_page(self.loader.char_to_line(boundary.date_start_char))
   end_page = self.loader.get_page(self.loader.char_to_line(boundary.date_end_char - 1))
   ```

3. Apply the same fix at lines 611-612 (inside `_make_annotation`):
   ```python
   start_page = self.loader.get_page(self.loader.char_to_line(start_char))
   end_page = self.loader.get_page(self.loader.char_to_line(end_char - 1))
   ```

**Testing:** After the fix, run on Volume 226 and check that case 0's start_of_case annotation has a page number matching the actual `--- Page N ---` marker near that line (should be a small number like 1-5, not 730).

**Constraints:**
- Do NOT modify `volume_loader.py` — the `get_page()` method is correct for its contract (takes line number)
- Only fix the call sites in `section_extractor.py` that pass the wrong argument type
- All 6 call sites must be fixed (lines 119, 120, 141, 142, 611, 612)
- Do NOT use Unicode characters in print statements

---

### FIX Dependency Graph

```
FIX-1 (votes overflow)     -- independent
FIX-2 (missed boundaries)  -- independent
FIX-3 (quoted SO ORDERED)  -- independent
FIX-4 (counsel overflow)   -- independent
FIX-5 (parties footnotes)  -- independent
FIX-6 (page number bug)    -- independent

All are independent — can be done in any order or in parallel.
FIX-1 + FIX-2 together fix ~80% of corrections.
After all fixes, re-run on Volume 226 (regression test) and Volume 227 (improvement test).
```

---

## Dynamic Justice Registry Tasks

These tasks replace the hardcoded `KNOWN_JUSTICES` list in `ocr_correction.py` with a dynamically-growing `justices.json` file. A separate CLI command harvests high-confidence ponente names from pipeline output and appends new justices to the registry. After harvesting, already-processed volumes can be re-run to benefit from the expanded list.

---

### KJ-1: Justice Registry — Seed File + Loader + Wiring

**Status:** TODO
**Depends on:** T5 (ocr_correction.py), T6 (confidence.py)
**Files to create:**
- `regex_improve/detection/justices.json`
- `regex_improve/detection/justice_registry.py`
**Files to modify:**
- `regex_improve/detection/ocr_correction.py`
- `regex_improve/detection/confidence.py`
- `regex_improve/detection/pipeline.py`

**Description:**
Create a JSON seed file with the 11 known Vol 226 justices, a small registry module with load/save functions, and rewire `ocr_correction.py` and `confidence.py` to use the registry instead of a hardcoded list.

#### `regex_improve/detection/justices.json`

Pre-seeded with the current 11 names from `ocr_correction.py:20-25`:

```json
{
    "description": "Known Philippine Supreme Court justice surnames for ponente fuzzy matching. Grows dynamically via harvest_justices.py.",
    "justices": [
        "ABAD SANTOS",
        "ALAMPAY",
        "CRUZ",
        "FERIA",
        "FERNAN",
        "GUTIERREZ, JR.",
        "MELENCIO-HERRERA",
        "NARVASA",
        "PARAS",
        "TEEHANKEE",
        "YAP"
    ]
}
```

#### `regex_improve/detection/justice_registry.py`

**Imports:**
```python
import json
from pathlib import Path
from typing import List
```

**Module-level constant:**
```python
_REGISTRY_PATH = Path(__file__).resolve().parent / "justices.json"
```

**Functions:**

1. `load_justices(path: Path = None) -> List[str]`:
   - If `path` is None, use `_REGISTRY_PATH`
   - Read the JSON file, return the `"justices"` list
   - If file does not exist or is malformed, print a warning and return an empty list (do NOT crash)
   - Return a copy of the list (not a reference to the internal data)

2. `save_justices(justices: List[str], path: Path = None) -> None`:
   - If `path` is None, use `_REGISTRY_PATH`
   - Sort the list alphabetically (case-insensitive: `key=str.upper`)
   - Deduplicate (case-insensitive comparison, keep the first occurrence's casing)
   - Write JSON with `indent=4, ensure_ascii=False`
   - Preserve the `"description"` field from the existing file if it exists

3. `add_justices(new_names: List[str], path: Path = None) -> List[str]`:
   - Load existing justices from file
   - Compare new names against existing (case-insensitive)
   - Append only genuinely new names
   - Save the combined list
   - Return list of names that were actually added (for reporting)

**`if __name__ == "__main__"` test block:**
- Load from seed file, assert 11 justices loaded
- Add 2 new names (e.g., "DAVIDE, JR.", "ROMERO"), assert they appear in the file
- Try adding a duplicate (e.g., "davide, jr." lowercase), assert it is NOT added again
- Print results

#### Changes to `regex_improve/detection/ocr_correction.py`

1. Replace the hardcoded `KNOWN_JUSTICES` list (lines 19-25) with:
   ```python
   from .justice_registry import load_justices

   # Loaded from justices.json (grows dynamically via harvest_justices.py)
   KNOWN_JUSTICES = load_justices()
   ```

2. Remove the `# Extend as more volumes are processed` comment — it's now handled automatically.

3. Everything else in `ocr_correction.py` stays the same — `correct_ponente()` still references the module-level `KNOWN_JUSTICES` variable. The fuzzy matching logic (`process.extractOne`) is unchanged.

#### Changes to `regex_improve/detection/confidence.py`

1. The existing import (line 19) already imports `KNOWN_JUSTICES` from `ocr_correction`:
   ```python
   from .ocr_correction import KNOWN_JUSTICES
   ```
   This still works because `ocr_correction.py` still exports `KNOWN_JUSTICES` — it's just loaded from file now instead of hardcoded. **No changes needed to confidence.py.**

#### Changes to `regex_improve/detection/pipeline.py`

No changes needed. `pipeline.py` imports `KNOWN_JUSTICES` from `confidence.py` (line 23), which re-exports from `ocr_correction.py`. The chain is preserved.

**Constraints:**
- The hardcoded list in `ocr_correction.py` must be completely removed — replaced by the file load
- `load_justices()` must never crash the pipeline. If `justices.json` is missing or corrupt, return `[]` with a warning
- `save_justices()` must sort alphabetically and deduplicate
- Do NOT use Unicode characters in print statements
- `justices.json` should be committed to git (it is NOT in `.gitignore`)
- Do NOT modify `correct_ponente()` logic — only change how `KNOWN_JUSTICES` is populated

---

### KJ-2: Harvest Justices CLI Command

**Status:** TODO
**Depends on:** KJ-1
**Files to create:**
- `regex_improve/detection/harvest_justices.py`

**Description:**
Create a standalone CLI command that scans predicted.json output files, extracts ponente names from high-confidence cases (case-level confidence >= 0.9), and appends new unique names to `justices.json`. This enables a self-improving feedback loop: each batch of processed volumes improves ponente matching for subsequent runs.

#### `regex_improve/detection/harvest_justices.py`

**Imports:**
```python
import json
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any, Set
```

**CLI interface:**
```
python -m detection.harvest_justices <input> [--dry-run] [--threshold 0.9]

positional arguments:
  input                 Path to a single predicted.json OR a directory containing *_predicted.json files

optional arguments:
  --dry-run             Show what would be added without writing to justices.json
  --threshold FLOAT     Minimum case confidence score to harvest ponente from (default: 0.9)
```

**Functions:**

1. `extract_ponente_names(predicted_path: Path, threshold: float = 0.9) -> List[str]`:
   - Load the predicted.json file
   - Iterate over all cases in all volumes
   - For each case:
     - Parse the confidence score from `case["notes"]` field (format: `"confidence: 0.950"`)
     - If confidence score < threshold, skip
     - Find the annotation with `label == "ponente"`
     - If no ponente annotation, skip
     - Get the ponente `text` value
     - Skip if text is empty, or contains "PER CURIAM" (case-insensitive)
     - Skip if text length < 3 (too short to be a real name)
     - Add to results
   - Return list of ponente names found

2. `harvest(input_path: Path, threshold: float = 0.9, dry_run: bool = False) -> Dict[str, Any]`:
   - If `input_path` is a file, scan just that file
   - If `input_path` is a directory, find all `*_predicted.json` and `*.predicted.json` files
   - Call `extract_ponente_names()` for each file
   - Collect all unique names (case-insensitive dedup)
   - If not `dry_run`, call `add_justices()` from `justice_registry.py`
   - Return summary dict:
     ```python
     {
         "files_scanned": int,
         "cases_above_threshold": int,
         "ponente_names_found": int,
         "new_names_added": ["DAVIDE, JR.", "ROMERO", ...],  # only genuinely new ones
         "already_known": ["CRUZ", "NARVASA", ...],           # names that were already in registry
         "skipped_per_curiam": int,
         "dry_run": bool
     }
     ```

3. `main()`:
   - Parse CLI args
   - Call `harvest()`
   - Print human-readable summary report
   - If new names were added (and not dry-run), print suggestion:
     ```
     N new justice(s) added to justices.json.
     Consider re-running the pipeline on previously processed volumes to benefit
     from improved ponente matching:
         python -m detection <volume_dir> --range <range> --skip-llm
     ```

**`if __name__ == "__main__"` block:**
- Call `main()`

**Constraints:**
- Must handle both single-file and directory input
- Must handle malformed JSON files gracefully (skip with warning, do not crash)
- Confidence score is parsed from the `notes` field string, NOT from a dedicated field (the pipeline writes `"confidence: 0.950"` into notes)
- "PER CURIAM" is not a justice name — always skip it
- Case-insensitive deduplication: "CRUZ" and "Cruz" should not both be added
- The `--dry-run` flag must NOT modify `justices.json`
- Do NOT use Unicode characters in print statements
- Print a count of files scanned, names found, and names added

---

### KJ-3: Update Instructions.txt with Harvest Workflow

**Status:** TODO
**Depends on:** KJ-2
**Files to modify:**
- `regex_improve/detection/Instructions.txt`

**Description:**
Add documentation for the harvest workflow to the existing Instructions.txt. Replace the existing suggestion 8.C with concrete usage instructions now that it is implemented.

#### Changes to `regex_improve/detection/Instructions.txt`

1. Add a new section **9. HARVESTING JUSTICE NAMES** after section 8 (or between sections 7 and 8). Content:

   ```
   9. HARVESTING JUSTICE NAMES
   --------------------------

   The pipeline uses a list of known justice surnames (justices.json) for
   fuzzy ponente matching and confidence scoring. This list grows dynamically
   as you process more volumes.

   After processing a batch of volumes:

       cd regex_improve
       python -m detection.harvest_justices ../downloads/predictions/

       Dry run (see what would be added without modifying justices.json):
           python -m detection.harvest_justices ../downloads/predictions/ --dry-run

       Custom confidence threshold (default 0.9):
           python -m detection.harvest_justices ../downloads/predictions/ --threshold 0.85

       Single file:
           python -m detection.harvest_justices ../downloads/Volume_226.predicted.json

   The harvester only collects ponente names from cases with confidence
   scores >= 0.9 (by default). This ensures only reliably-extracted names
   are added to the registry. "PER CURIAM" entries are always skipped.

   Recommended workflow after each phase:

       1. Run the pipeline:
           python -m detection ../downloads --range 226-260 --skip-llm

       2. Harvest new justice names:
           python -m detection.harvest_justices ../downloads/predictions/

       3. Re-run the pipeline to benefit from improved ponente matching:
           python -m detection ../downloads --range 226-260 --skip-llm

       Step 3 is optional but recommended. The expanded justice list improves
       both fuzzy ponente correction (ocr_correction.py) and the ponente_known
       confidence check (confidence.py), which can shift borderline cases from
       low to high confidence.
   ```

2. Update section 8.C to mark it as **implemented** — replace the suggestion text with a reference to section 9:

   ```
   C. Expand KNOWN_JUSTICES dynamically from processed volumes

       IMPLEMENTED — see Section 9. The pipeline now loads justice names from
       justices.json (pre-seeded with 11 Vol 226 justices). After each batch
       run, use `python -m detection.harvest_justices` to extract new names
       from high-confidence cases and add them to the registry.
   ```

3. Add `justices.json` to the "Internal constants" list in section 5:

   ```
   KNOWN_JUSTICES (justices.json, loaded by justice_registry.py)
       List of known justice surnames for fuzzy ponente matching.
       Pre-seeded with Vol 226 justices (1986 court). Grows dynamically
       via harvest_justices.py after each batch run.
   ```
   Remove the old entry that references `ocr_correction.py`.

**Constraints:**
- Keep the existing section numbering consistent (renumber if needed)
- The harvest workflow must mention the re-run step for already-processed volumes
- Do NOT use Unicode characters
- Keep the same formatting style as the rest of Instructions.txt (indented code blocks, dashed section headers)

---

### KJ Dependency Graph

```
KJ-1 (seed + loader + wiring) ---- KJ-2 (harvest CLI) ---- KJ-3 (docs)
```

KJ-1 must be completed first. KJ-2 depends on KJ-1. KJ-3 depends on KJ-2.

---

### KJ File Tree

```
regex_improve/
├── detection/
│   ├── justices.json              # KJ-1 (new, committed to git)
│   ├── justice_registry.py        # KJ-1 (new)
│   ├── harvest_justices.py        # KJ-2 (new)
│   ├── ocr_correction.py          # KJ-1 (modified: load from registry)
│   ├── confidence.py              # KJ-1 (no changes needed)
│   ├── pipeline.py                # KJ-1 (no changes needed)
│   ├── Instructions.txt           # KJ-3 (modified)
│   └── ... (other existing files)
```

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
│   ├── ocr_correction.py        # T5 (KJ-1: loads from registry)
│   ├── confidence.py            # T6
│   ├── llm_fallback.py          # T7
│   ├── pipeline.py              # T8
│   │   # FIX-1 thru FIX-6 modify: section_extractor.py, boundary_fsm.py
│   ├── justices.json            # KJ-1 (committed, grows via harvest)
│   ├── justice_registry.py      # KJ-1
│   ├── harvest_justices.py      # KJ-2
│   ├── Instructions.txt         # KJ-3 (updated)
│   └── tests/
│       ├── __init__.py          # T9
│       └── test_pipeline.py     # T9
├── gui/
│   ├── correction_tracker.py   # CT-1
│   └── ... (other GUI modules)
├── corrections/                 # CT-2 (created on first export)
│   └── Volume_NNN_corrections.json
├── annotate_gui.py
├── improved_regex.py
└── samples/
    └── Volume_*.txt
```
