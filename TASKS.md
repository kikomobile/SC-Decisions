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

## Completed Tasks

### Annotation GUI (GUI-1 thru GUI-6)
- [x] **GUI-1**: Project scaffolding + constants + data model
- [x] **GUI-2**: Volume loader — O(1) line/char/page coordinate conversion
- [x] **GUI-3**: Main app window + text panel + side panel
- [x] **GUI-4**: Highlight manager + dialogs
- [x] **GUI-5**: File I/O + status bar (atomic JSON writes)
- [x] **GUI-6**: Exporters + evaluation framework (JSON/Markdown, P/R/F1)

### Detection Pipeline (T1 thru T9)
- [x] **T1**: Package scaffold + preprocessor (`preprocess.py`) — noise_mask for page markers, volume headers, short titles. 94.5% F1 on Vol 226.
- [x] **T2**: Case boundary FSM (`boundary_fsm.py`) — 72/72 boundaries, OCR bracket variants, consolidated cases. 97.3% case_number exact, 94.4% date exact.
- [x] **T3**: Section extractor (`section_extractor.py`) — 16 label types, 96.7% F1. Known: end_of_case 81.9%, votes includes noise lines.
- [x] **T4**: Standalone scorer (`scorer.py`) — IoU-based span matching, per-label P/R/F1, CLI. Zero external deps.
- [x] **T5**: OCR post-correction (`ocr_correction.py`) — case_number, date, division, ponente (fuzzy via rapidfuzz), end_decision. Audit trail.
- [x] **T6**: Confidence scorer (`confidence.py`) — 7 weighted checks, score_all_cases splits high/low at threshold.
- [x] **T7**: LLM fallback (`llm_fallback.py`) — DeepSeek V3, BudgetTracker ($5 limit), exponential backoff, JSON output.
- [x] **T8**: Pipeline orchestrator + CLI (`pipeline.py`, `__main__.py`) — 8-step pipeline, single + batch mode, format_version=2 output.
- [x] **T9**: Integration tests (`tests/test_pipeline.py`) — 9 tests, 1.59s, F1 >= 0.90, all passing.

### Correction Tracking (CT-1, CT-2)
- [x] **CT-1**: Snapshot baseline on import + diff engine (`correction_tracker.py`) — deep-copy baseline, 4-type diff (removed, added, label_changed, span_adjusted).
- [x] **CT-2**: Export corrections as analysis-ready JSON (`app.py` modified) — "File > Export Corrections..." menu, embedded analysis_prompt for Claude.

### Volume 227 Fixes (FIX-1 thru FIX-7)
- [x] **FIX-1**: Votes overflow past page breaks — strict termination (double blanks, boundary patterns, 15-line cap) in `section_extractor.py`.
- [x] **FIX-2**: Missed boundaries from OCR-corrupted brackets — optional opening bracket + fallback `RE_CASE_BRACKET_NO_CLOSE` in `boundary_fsm.py`.
- [x] **FIX-3**: Quoted "SO ORDERED." triggers false end_decision — switched to last-match instead of first-match in `section_extractor.py`.
- [x] **FIX-4**: Counsel span bleeds past page breaks — smart termination using designation heuristics in `section_extractor.py`.
- [x] **FIX-5**: Parties span absorbs footnotes — `RE_PARTIES_END` + designation tracking stops at footnote lines in `section_extractor.py`.
- [x] **FIX-6**: Page number bug — `get_page()` called with char offset instead of line number fixed at 6 call sites in `section_extractor.py`.
- [x] **FIX-7**: Separate opinion regression after FIX-1 — tracked `separate_opinion_idx` + forward scan in `section_extractor.py`.

### OCR Repair Tools
- [x] **TOOL-1**: Patch blank pages — `patch_blank_pages.py` CLI, multi-strategy re-OCR (raw/preprocessed/400DPI) from original PDFs, batch mode, dry-run, `.bak` backup.

### Dynamic Justice Registry (KJ-1 thru KJ-3)
- [x] **KJ-1**: Justice registry seed file + loader — `justices.json` + `justice_registry.py` with load/save/add functions; `ocr_correction.py` rewired to load from file instead of hardcoded list.
- [x] **KJ-2**: Harvest justices CLI — `harvest_justices.py`, extracts ponente names from high-confidence (>=0.9) predictions and appends to registry.
- [x] **KJ-3**: Instructions.txt updated with harvest workflow documentation (Section 9).

### Self-Diagnostic Failure Reporting (DIAG-1 thru DIAG-3, DIAG-FIX-1, DIAG-FIX-2)
- [x] **DIAG-1**: Diagnostics module — 4 statistical checks (mean confidence, missing labels, span lengths, confidence distribution) in `diagnostics.py`.
- [x] **DIAG-2**: Near-miss pattern detection added to `diagnostics.py` — 4 patterns (division/bracket/SO_ORDERED/doc_type), 30-item cap.
- [x] **DIAG-3**: Diagnostics wired into pipeline — runs on every invocation, full output in `.log`, console output only on warnings/criticals.
- [x] **DIAG-FIX-1**: Calibrate thresholds and tighten near-miss patterns — percentage-based span outlier thresholds, anchored regexes eliminate body-text false positives.
- [x] **DIAG-FIX-2**: Expand `matched_lines` to include section extractor annotation lines in `pipeline.py`, reducing near-miss false positives.

### Detection Manifest and Caching (MANIFEST-1 thru MANIFEST-4)
- [x] **MANIFEST-1**: `detection_method` field added to all annotation dicts (`"regex"` or `"llm"`).
- [x] **MANIFEST-2**: `manifest.py` module — manifest I/O, merge logic (preserves cached LLM annotations), `should_reprocess()`, 12 self-tests.
- [x] **MANIFEST-3**: Manifest integrated into pipeline + `--force` CLI flag — skips up-to-date volumes, preserves cached LLM results on re-runs.
- [x] **MANIFEST-4**: Tests updated (`TestManifest` class, 6 tests) and Instructions.txt Section 12 added.

### Volume 234 Extraction Fixes (FIX-234-1 thru FIX-234-4)
- [x] **FIX-234-1**: WHEREFORE fallback for end_decision — justice-surname confirmation within ~20 lines when "SO ORDERED." absent in `section_extractor.py`.
- [x] **FIX-234-2**: Justice-surname loose matching for votes termination — footnote lines without justice surnames stop votes extraction in `section_extractor.py`.
- [x] **FIX-234-3**: Detect all separate opinions — replaced single-match with loop creating paired start/end_opinion for each opinion in `section_extractor.py`.
- [x] **FIX-234-4**: Parties extraction requires "vs." + second designation before stopping — `RE_VS_LINE` + `seen_first_designation` logic in `section_extractor.py`.

### Era-Tagged Pattern Registry (ERA-1 thru ERA-7)
- [x] **ERA-1**: `pattern_registry.py` — `Era` + `EraConfig` dataclasses, 5 era definitions (vol 121-999), baseline patterns copied from all modules, `get_era_config()` / `get_fallback_order()` API.
- [x] **ERA-2**: Volume number extracted from filename in `process_volume()` and threaded as `vol_num` param to all module constructors.
- [x] **ERA-3**: All modules (`preprocess.py`, `boundary_fsm.py`, `section_extractor.py`) consume patterns from `self.config` via registry — module-level `RE_*` constants removed.
- [x] **ERA-4**: Era-aware confidence scoring — `score_case()` and `score_all_cases()` accept optional `EraConfig` for era-specific required labels, label order, and span length ranges.
- [x] **ERA-5**: Era fallthrough in pipeline — if mean confidence < 0.65, retry with adjacent eras (outward), select best; `--fallthrough-threshold` CLI arg added.
- [x] **ERA-6**: Syllabus skip for era5 — `has_syllabus=False` guard in `section_extractor.py` prevents false syllabus matches in modern volumes.
- [x] **ERA-7**: Validation against both ground truths — era selection tests + fallback order tests + Vol 421 test added to `test_pipeline.py`.

### Scorer Enhancement
- [x] **SCORE-1**: Annotation texts in scorer per-case output — `_truncate()` helper, `match_spans()`/`match_grouped_spans()` return 6-tuple with detail dicts, `per_case` gains `missed_annotations`/`extra_annotations`/`matched_annotations` fields, `format_results_table()` shows MISSED/EXTRA/low-IoU MATCHED sections per case.

### CSV Extract Quality Fixes (CSV-1a, CSV-1b, CSV-2, CSV-3)
- [x] **CSV-1a**: Widen SO ORDERED regex — handles smart quotes, "IT IS" prefix, trailing footnote numbers in `pattern_registry.py`. Recovered 86 missing votes (1314→1228).
- [x] **CSV-1b**: Content-based votes termination — `_is_non_votes_content()` helper + early termination + gap trimming in `section_extractor.py`. Overflow 19→0.
- [x] **CSV-2**: Ghost row filter — skip cases with no `case_number` in `extract_predictions_csv.py`. Blank rows 13→0.
- [x] **CSV-3**: Widen ponente regex — optional trailing punctuation, search window 3→5, inline fallback in `section_extractor.py` + `pattern_registry.py`. +106 ponentes recovered (net +72 regression due to lost LLM-fallback ponentes from --skip-llm reprocess).

### CSV Pipeline Integration (CSV-PIPE-1, CSV-PIPE-2)
- [x] **CSV-PIPE-1**: Moved CSV extraction logic into `regex_improve/detection/csv_extractor.py` (JusticeMatcher, extract_cases, archive_csv, write_predictions_csv). Replaced `extract_predictions_csv.py` with thin wrapper. Auto-archiving via `csv_archive/` with mtime-based timestamps.
- [x] **CSV-PIPE-2**: Wired `--csv` and `--no-archive` flags into `__main__.py`. CSV extraction runs after both single and batch mode. `--csv` uses `nargs="?"` with default `predictions_extract.csv`.

### Pipeline Control Panel — Streamlit UI (UI-1, UI-2, UI-3)
- [x] **UI-1**: Created `ui_helpers.py` — settings persistence (atomic JSON), `PipelineRunner` subprocess class with threaded log queue, command builders for single/batch/CSV modes, validation runners, `scan_volumes()`, `parse_summary_metrics()`.
- [x] **UI-2**: Created `pipeline_ui.py` — Streamlit app with sidebar settings, 3 tabs (Single Volume, Batch Processing, CSV Extraction), live log streaming via `st.status`, summary metrics cards, validation check expanders.
- [x] **UI-3**: Added `streamlit>=1.29.0` to `requirements.txt`, added `.pipeline_ui_settings.json` to `.gitignore`.

### Unhandled Vote Pattern Fix (VOTE-1 thru VOTE-4)
- [x] **VOTE-1**: Extended `_VOTE_VERB_RE` in `csv_extractor.py` with 6 new verb patterns (separate opinion, joins opinion, on official business, inhibit). Expanded classification logic and added after-verb name extraction for "joins...of" pattern.
- [x] **VOTE-2**: Added `other_votes` field to `CaseRecord` in `temporal.py`, wired through `load_cases()` and `TemporalNetwork` with `treat_other_as_dissent=True` reclassification.
- [x] **VOTE-3**: Added `treat_other_as_dissent` to `build_network.py` `build()` and `_process_case()`, reading `other_votes` from CSV and merging into dissenters.
- [x] **VOTE-4**: Wired `treat_other_as_dissent` checkbox into `pipeline_ui.py` (default ON) and passed to all call sites (build_network, load_cases, TemporalNetwork).

### Vote Classification Fix (CSV-4, CSV-4b)
- [x] **CSV-4**: Replaced sentence-based clause splitting with action-verb-based splitting in `csv_extractor.py` `parse_votes()`. Added `_VOTE_VERB_RE` regex + OCR variants (concut/conrur/concui). Fixed 10 misclassified cases.
- [x] **CSV-4b**: Added OCR normalization step in `parse_votes()` — canonicalizes 10 OCR variants of "concur" (coneur/concue/concuf/soncur/concor/coricur/conour/concut/conrur/concui), handles hyphenated `con- cur`/`con cur`, underscore-prefixed `_concur`. Simplified `_VOTE_VERB_RE` and step 3 regex. Fixed 20 additional cases.

### Votes Detection Fixes (VOTE-FIX-1, VOTE-FIX-2)
- [x] **VOTE-FIX-1**: Widened `re_division` in `pattern_registry.py` — `[A-Z]{4,7}` replaces literal `FIRST|SECOND|THIRD` to handle OCR corruptions (e.g., FIPST). FSM bracket gate prevents false positives.
- [x] **VOTE-FIX-2**: Added `_RE_DEFINITE_VOTES` regex in `section_extractor.py` — lines with unambiguous votes keywords (concur/dissent/leave/no part) bypass 50-char limit. Two guard points updated (initial capture + continuation).

### Label Inspector (INSPECT-1, INSPECT-2, INSPECT-FIX-1)
- [x] **INSPECT-1**: Created `label_inspector.py` — `parse_lookup_input()`, `lookup_cases()`, `format_case_text()`, `compile_results()` for spot-checking predicted labels by volume+case_number. Standalone module, stdlib-only, UTF-8 safe.
- [x] **INSPECT-2**: Wired label inspector into `pipeline_ui.py` as 4th tab — text area paste input, per-case expanders with copyable code blocks, metrics row, JSON download button.
- [x] **INSPECT-FIX-1**: Guarded `None` confidence in `format_case_text()` and UI expander label — displays "N/A" instead of crashing on `:.3f`.

---

## Active Tasks

### Processor Text Ordering Fix (PROC-1)

```
[Task]: Fix PyMuPDF text extraction block ordering in 02_processor.ipynb
[Files]: 02_processor.ipynb (cell-12, function extract_text_pymupdf)
[Context]:
PyMuPDF's page.get_text() extracts text blocks in PDF-internal order, NOT
top-to-bottom reading order. On pages where a new case starts on the same page
where the previous case ends, the new case header (DIVISION, G.R. No., parties)
gets extracted BEFORE the old case's ending text (WHEREFORE, SO ORDERED, votes).
This causes ~57% of pages in Volume 668 to have jumbled text, and affects most
volumes from ~550 onward. The fix: extract blocks, sort by y-coordinate, then
concatenate. This produces correct reading order with no formatting side effects.

[Instructions]:
1. In 02_processor.ipynb cell-12, replace the entire extract_text_pymupdf function with:

def extract_text_pymupdf(pdf_path):
    """Extract text from all pages of a searchable PDF using PyMuPDF.

    Extracts text blocks and sorts by vertical position (y0) to fix
    PDF-internal block ordering that can jumble case boundaries on
    shared pages.
    """
    doc = fitz.open(pdf_path)
    all_text = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("blocks")
        # Filter to text blocks only (type 0); skip image blocks (type 1)
        text_blocks = [b for b in blocks if b[6] == 0]
        # Sort by vertical position (y0=b[1]), then horizontal (x0=b[0])
        text_blocks.sort(key=lambda b: (b[1], b[0]))
        # Concatenate block text (b[4]) — preserves original line breaks
        page_text = "".join(b[4] for b in text_blocks)
        if page_text.strip():
            all_text.append(f"--- Page {page_num + 1} ---\n{page_text}")
    doc.close()
    return "\n\n".join(all_text)

2. Do NOT change any other function or cell in the notebook.

[Constraints]:
- Do NOT use page.get_text(sort=True) — it adds x-based indentation that
  breaks ^-anchored regex patterns in the detection pipeline.
- Do NOT change the page marker format "--- Page N ---".
- The function must produce text identical to the original get_text() output
  on pages where blocks are already in correct y-order (most pages).
- Block tuple structure: (x0, y0, x1, y1, text, block_no, block_type).
  block_type 0 = text, 1 = image. Filter for type 0 only.
```

---

### Processor Selective Reprocessing (PROC-2)

```
[Task]: Add volume-range reprocessing config to 02_processor.ipynb
[Files]: 02_processor.ipynb (cell-8, the RESET block)
[Context]:
After PROC-1, we need to reprocess volumes 501–961 to regenerate .txt files
with correct block ordering. Volumes ≤500 are unaffected (0% out-of-order
blocks) and mostly went through OCR (different path). We need a config cell
that selectively clears manifest entries and deletes .txt files for the
specified range only, so the main processing loop re-extracts them.

[Instructions]:
1. In cell-8, AFTER the existing RESET_PROCESSING block, add a new block:

# === SELECTIVE REPROCESS: Clear specific volume range ===
REPROCESS_RANGE = None  # Set to (501, 961) to reprocess volumes 501-961, then set back to None

if REPROCESS_RANGE:
    range_start, range_end = REPROCESS_RANGE
    cleared = 0
    for key in list(manifest.keys()):
        # Extract volume number from manifest key (e.g., "Volume_668.pdf" -> 668)
        m = re.search(r'Volume_(\d+)', key)
        if m:
            vol_num = int(m.group(1))
            if range_start <= vol_num <= range_end:
                # Only clear searchable (non-OCR) volumes — OCR uses different path
                entry = manifest[key]
                if entry.get("status") == "done" and not entry.get("is_ocr", False):
                    # Delete existing .txt so it gets regenerated
                    txt_file = DOWNLOAD_PATH / entry.get("text_file", "")
                    if txt_file.exists():
                        txt_file.unlink()
                        logger.info(f"Deleted {txt_file.name} for reprocessing")
                    del manifest[key]
                    cleared += 1
    save_manifest(manifest)
    logger.info(f"SELECTIVE REPROCESS: Cleared {cleared} volumes in range {range_start}-{range_end}")
    print(f"Selective reprocess: cleared {cleared} volumes ({range_start}-{range_end})")

2. Add `import re` at the top of cell-8 if not already imported (it is imported
   in cell-12 indirectly via other functions, but cell-8 runs before cell-12).
   Actually, check: `re` is not imported at module level in the notebook.
   Add `import re` to cell-1 (the imports cell) if it's not already there.

[Constraints]:
- Do NOT clear OCR volumes (is_ocr=True) — their text comes from Tesseract,
  not PyMuPDF, so they are unaffected by the block ordering bug.
- Do NOT modify the existing RESET_PROCESSING block.
- The REPROCESS_RANGE should default to None (no-op) so the notebook is safe
  to run without accidentally clearing volumes.
- Only delete .txt files, never .pdf files.
```

---

### Displaced Text Guard in Detection Pipeline (GUARD-1)

```
[Task]: Add post-boundary pass to detect and fix displaced case endings
[Files]: regex_improve/detection/boundary_fsm.py
[Context]:
Even after PROC-1 fixes text ordering for future runs, a safety net in the
detection pipeline handles any remaining edge cases (or volumes not yet
reprocessed). The problem: when text is jumbled, the end of case N
(WHEREFORE, SO ORDERED, votes, footnotes) appears textually WITHIN case
N+1's boundary — after N+1's DIVISION header but before N+1's SYLLABUS.
Case N's boundary ends too early (before its own SO ORDERED), so section
extraction misses the real end_decision and votes. This guard detects
displaced ending patterns at the start of each case boundary and extends
the previous case's end_line to reclaim them.

[Instructions]:
1. In boundary_fsm.py, add a new method to CaseBoundaryDetector:

    def fix_displaced_endings(self, boundaries: list['CaseBoundary']) -> list['CaseBoundary']:
        """Post-process boundaries to fix displaced case endings.

        When PDF text extraction produces out-of-order blocks, the end of
        case N (SO ORDERED, votes, footnotes) may appear textually after
        the start of case N+1 (DIVISION, G.R. bracket, parties) but before
        N+1's SYLLABUS/counsel/doc_type. This method detects that pattern
        and extends case N's end_line to include the displaced text.

        Args:
            boundaries: list of CaseBoundary from detect(), ordered by start_line.

        Returns:
            The same list, mutated in place, with end_line adjustments.
        """
        if len(boundaries) < 2:
            return boundaries

        from .pattern_registry import get_era_config

        config = self.config

        for i in range(len(boundaries) - 1):
            curr = boundaries[i]
            nxt = boundaries[i + 1]

            # Scan the first ~40 lines of the NEXT case's boundary region.
            # We're looking for displaced content from the CURRENT case:
            # SO ORDERED, WHEREFORE, votes (justice surnames + concur/dissent),
            # that appears BEFORE the next case's substantive content
            # (SYLLABUS, APPEARANCES OF COUNSEL, doc_type like DECISION/RESOLUTION).
            scan_start = nxt.start_line
            scan_end = min(nxt.end_line, scan_start + 40)

            displaced_end_line = None
            found_so_ordered = False
            found_wherefore = False
            hit_new_case_content = False

            for line_num in range(scan_start, scan_end + 1):
                text = self.loader.get_line_text(line_num)
                if not text or not text.strip():
                    continue

                # Skip the new case's own header lines (division, bracket, parties)
                # These are expected at the start. We're looking PAST them.
                if self.preprocessor.is_noise(line_num):
                    continue

                # Stop if we hit the new case's substantive content
                if config.re_syllabus_header.match(text):
                    hit_new_case_content = True
                    break
                if config.re_counsel_header.match(text):
                    hit_new_case_content = True
                    break
                if config.re_doc_type.match(text):
                    hit_new_case_content = True
                    break

                # Detect displaced patterns from the previous case
                if config.re_so_ordered.match(text):
                    found_so_ordered = True
                    displaced_end_line = line_num
                    # Continue scanning for votes after SO ORDERED
                    continue
                if config.re_wherefore.match(text):
                    found_wherefore = True
                    displaced_end_line = line_num
                    continue

                # After SO ORDERED: votes lines (justice surnames + concur/dissent)
                if found_so_ordered:
                    if re.search(
                        r'\b(?:concur|dissent|[Oo]n\s+(?:official\s+)?leave|'
                        r'(?:took|1ook|look)\s+no\s+part)\b',
                        text, re.IGNORECASE
                    ):
                        displaced_end_line = line_num
                        continue
                    # Footnote-like lines after votes (e.g., "* Designated acting member...")
                    if re.match(r'^\s*[\*\d]+\s', text):
                        displaced_end_line = line_num
                        continue

            # If we found displaced SO ORDERED or WHEREFORE before the new
            # case's substantive content, extend the previous case's boundary
            if displaced_end_line and (found_so_ordered or found_wherefore):
                import logging
                logger = logging.getLogger(__name__)
                logger.info(
                    f"GUARD-1: Displaced ending detected — case ending at line "
                    f"{curr.end_line} extended to {displaced_end_line} "
                    f"(SO_ORDERED={found_so_ordered}, WHEREFORE={found_wherefore})"
                )
                curr.end_line = displaced_end_line

        return boundaries

2. In the detect() method of CaseBoundaryDetector, call fix_displaced_endings()
   at the very end, just before the return statement. Find the line that says:

        return boundaries

   And change it to:

        # Post-process: fix displaced case endings from jumbled PDF block ordering
        boundaries = self.fix_displaced_endings(boundaries)
        return boundaries

   (There should be only one `return boundaries` at the end of detect().)

3. Import `re` at the top of boundary_fsm.py if not already imported.
   (It IS already imported — line 1 is `import re`.)

[Constraints]:
- Do NOT modify the detect() method's core FSM logic — only add the call
  at the end before return.
- The guard must be safe on volumes where text is NOT jumbled — if no
  displaced patterns are found, boundaries are returned unchanged.
- Do NOT extend end_line past the next case's SYLLABUS/counsel/doc_type.
  Only reclaim lines that appear BEFORE those markers.
- The method modifies boundaries in place AND returns them (for chaining).
- Use self.config patterns (re_so_ordered, re_syllabus_header, etc.) rather
  than hardcoded regexes, except for the votes keyword check which is a
  local detection heuristic and doesn't need registry patterns.
- re_wherefore is already in pattern_registry EraConfig — use self.config.re_wherefore.
```

---

### Network Graph Readability + Export (NET-1 thru NET-5)

#### NET-1: Labels Inside Nodes + Name Formatting

```
[Task]: Render justice name labels inside circular nodes with smart line-breaking
[Files]: network/visualize.py
[Context]:
Currently nodes use the default PyVis "dot" shape, which renders labels floating
outside the node. With 50-100 nodes this creates unreadable overlapping text.
Switching to shape="circle" in vis.js renders labels INSIDE the node. Larger node
sizes and white text on the community-colored background make names readable.
Names > 14 chars need line breaks at hyphens/spaces to fit inside circles.

[Instructions]:
1. Add two helper functions ABOVE build_pyvis_html (after COMMUNITY_COLORS, ~line 14):

   def _format_label(name: str, max_line_len: int = 14) -> str:
       """Insert a line break for names longer than max_line_len characters.
       Breaks at hyphens first, then spaces, preferring the split closest
       to the middle of the string."""
       if len(name) <= max_line_len:
           return name
       mid = len(name) // 2
       # Try breaking at a hyphen closest to the middle
       hyphen_positions = [i for i, c in enumerate(name) if c == '-']
       if hyphen_positions:
           best = min(hyphen_positions, key=lambda p: abs(p - mid))
           return name[:best + 1] + "\n" + name[best + 1:]
       # Try breaking at a space closest to the middle
       space_positions = [i for i, c in enumerate(name) if c == ' ']
       if space_positions:
           best = min(space_positions, key=lambda p: abs(p - mid))
           return name[:best] + "\n" + name[best + 1:]
       return name

   def _darken_hex(hex_color: str, factor: float = 0.3) -> str:
       """Darken a hex color by the given factor (0-1). Returns hex string."""
       hex_color = hex_color.lstrip('#')
       r = int(int(hex_color[0:2], 16) * (1 - factor))
       g = int(int(hex_color[2:4], 16) * (1 - factor))
       b = int(int(hex_color[4:6], 16) * (1 - factor))
       return f"#{r:02x}{g:02x}{b:02x}"

2. On line 49, change node size range:
   OLD: min_size, max_size = 10, 50
   NEW: min_size, max_size = 30, 70

3. In the node-adding loop (lines 60-67), replace the net.add_node call.
   OLD:
       net.add_node(node, label=node, title=title, color=color, size=size)

   NEW:
       label = _format_label(node)
       font_size = max(8, int(size * 0.28))
       net.add_node(
           node, label=label, title=title, size=size, shape="circle",
           color={"background": color, "border": _darken_hex(color, 0.3)},
           font={"size": font_size, "color": "#ffffff", "face": "arial", "multi": True},
       )

[Constraints]:
- The "title" (hover tooltip) must still show the FULL unabbreviated name + stats.
- Do NOT change the COMMUNITY_COLORS array.
- "multi": True enables vis.js multi-line label rendering (\n in label text).
- Keep the node id as the original full name (first arg to add_node), only change
  the display label.
- Test: "LEONARDO-DE CASTRO" should display as two lines inside a circle,
  "CARPIO" should display as one line.
```

---

#### NET-2: Edge Declutter (Curved Edges + Opacity Scaling + Community Coloring)

```
[Task]: Reduce edge visual clutter with curves, opacity scaling, and community colors
[Files]: network/visualize.py
[Context]:
With 500-2000+ edges, straight opaque lines of uniform color create visual noise.
Three improvements: (a) curved edges prevent overlap on same-path edges, (b) opacity
scales with weight so weak edges fade into background, (c) same-community edges use
a faint community color while cross-community edges use grey.

[Instructions]:
1. Add new parameters to build_pyvis_html signature (line 15-18):

   def build_pyvis_html(
       G: nx.Graph,
       edge_threshold: int = 0,
       node_size_by: str = "weighted_degree",
       curved_edges: bool = True,
       opacity_scaling: bool = True,
   ) -> str:

2. After the Network() constructor (line 57), add curved edge config:

       net = Network(height="700px", width="100%", bgcolor="#ffffff", font_color="black")
       if curved_edges:
           net.set_edge_smooth("curvedCW")

   NOTE: Remove the net.repulsion() line (line 58) entirely — it will be
   replaced in NET-3. For now, just delete it. The graph will still render
   (vis.js defaults to barnesHut physics).

3. Replace the edge-adding loop (lines 69-76) with community-aware coloring
   and opacity. OLD:

       max_weight = max((d["weight"] for _, _, d in G.edges(data=True)), default=1)
       for u, v, d in G.edges(data=True):
           w = d["weight"]
           if w < edge_threshold:
               continue
           width = max(0.5, w / max_weight * 5)
           net.add_edge(u, v, value=w, width=width, title=f"Weight: {w}")

   NEW:

       max_weight = max((d["weight"] for _, _, d in G.edges(data=True)), default=1)
       for u, v, d in G.edges(data=True):
           w = d["weight"]
           if w < edge_threshold:
               continue
           width = max(0.5, w / max_weight * 5)

           # Opacity: strong edges opaque, weak edges transparent
           if opacity_scaling:
               alpha = max(0.08, min(0.85, w / max_weight))
           else:
               alpha = 0.6

           # Color: same-community edges tinted, cross-community edges grey
           comm_u = node_community.get(u, -1)
           comm_v = node_community.get(v, -1)
           if comm_u == comm_v and comm_u >= 0:
               base = COMMUNITY_COLORS[comm_u % len(COMMUNITY_COLORS)]
               r, g, b = int(base[1:3], 16), int(base[3:5], 16), int(base[5:7], 16)
               edge_color = f"rgba({r},{g},{b},{alpha:.2f})"
           else:
               edge_color = f"rgba(150,150,150,{alpha:.2f})"

           net.add_edge(
               u, v, width=width, title=f"Weight: {w}",
               color={"color": edge_color, "highlight": "#333333", "hover": "#555555"},
           )

[Constraints]:
- Do NOT pass value=w to add_edge — it triggers vis.js auto-scaling which
  conflicts with our manual width control.
- Highlight/hover colors are dark so selected edges are always visible.
- Opacity range: 0.08 (nearly invisible) to 0.85 (not fully opaque, allowing
  overlap visibility).
- The node_community dict from the community detection block (lines 35-38) is
  already computed before this code runs.
```

---

#### NET-3: Community-Aware Layout

```
[Task]: Add community-clustered layout using NetworkX positions or forceAtlas2Based
[Files]: network/visualize.py
[Context]:
The basic repulsion layout scatters nodes randomly. A community-aware layout places
Louvain clusters as distinct visual groups. Two modes: (1) Pre-computed positions
via NetworkX spring_layout with community-clustered starting points (deterministic,
clean), or (2) vis.js forceAtlas2Based physics (interactive, draggable).

[Instructions]:
1. Add imports at the top of visualize.py (after line 3):

   import math
   import json

2. Add layout_mode parameter to build_pyvis_html:

   def build_pyvis_html(
       G: nx.Graph,
       edge_threshold: int = 0,
       node_size_by: str = "weighted_degree",
       curved_edges: bool = True,
       opacity_scaling: bool = True,
       layout_mode: str = "community",
   ) -> str:

   Update the docstring to document all 3 new params.

3. Add a helper function above build_pyvis_html:

   def _compute_community_positions(
       G: nx.Graph, communities: list, width: float = 1000, height: float = 700,
   ) -> dict:
       """Compute node positions with community-clustered starting points.
       Places community centroids on a circle, jitters members around each,
       then refines with spring_layout. Returns {node: (x, y)} in pixel coords."""
       n_comm = len(communities)
       initial_pos = {}
       radius = 3.0
       for i, comm in enumerate(communities):
           angle = 2 * math.pi * i / max(n_comm, 1)
           cx = math.cos(angle) * radius
           cy = math.sin(angle) * radius
           for j, node in enumerate(sorted(comm)):
               jitter_angle = 2 * math.pi * j / max(len(comm), 1)
               initial_pos[node] = (
                   cx + math.cos(jitter_angle) * 0.5,
                   cy + math.sin(jitter_angle) * 0.5,
               )

       pos = nx.spring_layout(
           G, pos=initial_pos,
           k=2.0 / math.sqrt(max(G.number_of_nodes(), 1)),
           iterations=150, seed=42, weight="weight",
       )

       # Scale to pixel coordinates with padding
       pad = 80
       xs = [p[0] for p in pos.values()]
       ys = [p[1] for p in pos.values()]
       x_min, x_max = min(xs), max(xs)
       y_min, y_max = min(ys), max(ys)
       x_range = x_max - x_min or 1
       y_range = y_max - y_min or 1
       return {
           node: (
               int(pad + (x - x_min) / x_range * (width - 2 * pad)),
               int(pad + (y - y_min) / y_range * (height - 2 * pad)),
           )
           for node, (x, y) in pos.items()
       }

4. In build_pyvis_html, AFTER the community detection block (line 38) and
   BEFORE the node size computation (line 41), add:

       # --- Layout ---
       if layout_mode == "community":
           positions = _compute_community_positions(G, communities)
       else:
           positions = None

5. Replace the Network constructor + edge smooth section (from NET-2) with
   layout-mode-specific configuration. AFTER creating the Network object:

       net = Network(height="700px", width="100%", bgcolor="#ffffff", font_color="black")

       if layout_mode == "community":
           # Pre-computed positions: disable physics
           opts = {"physics": {"enabled": False}}
           if curved_edges:
               opts["edges"] = {"smooth": {"enabled": True, "type": "curvedCW"}}
           net.set_options(json.dumps(opts))
       else:
           # Interactive physics with forceAtlas2Based
           net.force_atlas_2based(
               gravity=-80, central_gravity=0.005, spring_length=200,
               spring_strength=0.02, damping=0.4, overlap=1,
           )
           if curved_edges:
               net.set_edge_smooth("curvedCW")

   IMPORTANT: set_options() replaces ALL options. So for "community" mode,
   embed the edge smooth config INSIDE the options JSON. For "physics" mode,
   use the separate calls (force_atlas_2based + set_edge_smooth) since
   force_atlas_2based sets physics options internally.

6. In the node-adding loop, pass fixed positions when layout_mode="community".
   Replace the net.add_node call (from NET-1) with:

       node_kwargs = dict(
           label=label, title=title, size=size, shape="circle",
           color={"background": color, "border": _darken_hex(color, 0.3)},
           font={"size": font_size, "color": "#ffffff", "face": "arial", "multi": True},
       )
       if positions and node in positions:
           node_kwargs["x"] = positions[node][0]
           node_kwargs["y"] = positions[node][1]
           node_kwargs["physics"] = False
       net.add_node(node, **node_kwargs)

[Constraints]:
- spring_layout seed=42 for reproducibility.
- k=2.0/sqrt(N) provides good separation for 50-100 nodes. Do NOT hardcode k.
- When layout_mode="physics", do NOT pass x/y/physics kwargs to nodes.
- Pixel coordinate range ~0-1000 x, ~0-700 y (matching vis.js canvas viewport).
- Do NOT use net.toggle_physics() — it's unreliable. Use set_options instead.
```

---

#### NET-4: Streamlit UI Controls + HTML Export

```
[Task]: Add display toggles and HTML export button to the Network Analysis tab
[Files]: pipeline_ui.py (lines 389-394, 438, 457-502)
[Context]:
NET-1 through NET-3 added parameters to build_pyvis_html: curved_edges,
opacity_scaling, layout_mode. The Streamlit UI needs controls for these.
The HTML export is simply the already-generated PyVis HTML string as a download.

[Instructions]:
1. In pipeline_ui.py, find the session state initialization block (~lines 33-50).
   Add after the existing session state inits:

       if "network_html" not in st.session_state:
           st.session_state.network_html = None

2. Replace the display controls section (lines 389-394). OLD:

       dc1, dc2 = st.columns(2)
       edge_thresh = dc1.slider("Edge Weight Threshold", 0, 500, 0, 10, key="net_edge_thresh")
       size_options = {"Weighted Degree": "weighted_degree", "Case Count": "case_count", "Uniform": "uniform"}
       size_label = dc2.selectbox("Node Size By", list(size_options.keys()), key="net_size_by")
       size_by = size_options[size_label]

   NEW:

       dc1, dc2, dc3 = st.columns(3)
       edge_thresh = dc1.slider("Edge Weight Threshold", 0, 500, 0, 10, key="net_edge_thresh")
       size_options = {"Weighted Degree": "weighted_degree", "Case Count": "case_count", "Uniform": "uniform"}
       size_label = dc2.selectbox("Node Size By", list(size_options.keys()), key="net_size_by")
       size_by = size_options[size_label]
       layout_options = {"Community Clusters": "community", "Interactive Physics": "physics"}
       layout_label = dc3.selectbox("Layout", list(layout_options.keys()), key="net_layout")
       layout_mode = layout_options[layout_label]

       dc4, dc5 = st.columns(2)
       curved_edges = dc4.checkbox("Curved edges", value=True, key="net_curved")
       opacity_scaling = dc5.checkbox("Opacity scaling", value=True, key="net_opacity")

3. Update the build_pyvis_html call (line 438). OLD:

       html = build_pyvis_html(G, edge_threshold=edge_thresh, node_size_by=size_by)

   NEW:

       html = build_pyvis_html(
           G, edge_threshold=edge_thresh, node_size_by=size_by,
           curved_edges=curved_edges, opacity_scaling=opacity_scaling,
           layout_mode=layout_mode,
       )
       st.session_state.network_html = html

4. In the Downloads section (line 459), change from 3 columns to include HTML.
   After the existing dl3 download button (Stats JSON, ~line 502), add:

       # --- Graph export row ---
       dl4, dl5, dl6 = st.columns(3)
       if st.session_state.network_html:
           dl4.download_button(
               "Interactive Graph (HTML)",
               data=st.session_state.network_html,
               file_name="justice_network.html",
               mime="text/html",
               key="dl_html",
           )

   (dl5 and dl6 will be used by NET-5 for PNG/SVG.)

[Constraints]:
- All new widget keys must be unique (prefixed "net_" or "dl_").
- The HTML download is the FULL PyVis-generated HTML including vis.js CDN links,
  so it works standalone in any browser.
- Keep existing controls (edge_thresh, size_by) working exactly as before.
- The dl4/dl5/dl6 columns go BELOW the existing dl1/dl2/dl3 row (a second row
  of download buttons).
```

---

#### NET-5: PNG + SVG Export via Matplotlib Static Render

```
[Task]: Add PNG and SVG export of the network graph using matplotlib
[Files]: network/visualize.py, pipeline_ui.py
[Context]:
vis.js renders to an HTML5 canvas inside an iframe — no clean way to export
PNG/SVG from the browser in Streamlit. Instead, generate a parallel static
render using matplotlib + NetworkX drawing. Uses the same positions, colors,
and edge styling as the PyVis version. Matplotlib natively exports PNG and SVG.

[Instructions]:

--- PART A: network/visualize.py ---

1. Add `import io` at the top (after the existing imports).

2. Add two new functions at the bottom of the file (after get_community_summary):

   def build_matplotlib_figure(
       G: nx.Graph,
       edge_threshold: int = 0,
       node_size_by: str = "weighted_degree",
       opacity_scaling: bool = True,
       figsize: tuple = (14, 10),
       dpi: int = 150,
   ):
       """Build a static matplotlib figure of the justice network.
       Uses same community detection, coloring, and layout as the PyVis version."""
       import matplotlib
       matplotlib.use("Agg")
       import matplotlib.pyplot as plt
       import matplotlib.patches as mpatches

       if G.number_of_nodes() == 0:
           fig, ax = plt.subplots(1, 1, figsize=figsize)
           ax.text(0.5, 0.5, "No nodes in graph", ha="center", va="center", fontsize=16)
           ax.axis("off")
           return fig

       # Community detection (same seed as PyVis version)
       communities = nx.community.louvain_communities(G, weight="weight", seed=42)
       node_community = {}
       for idx, comm in enumerate(communities):
           for node in comm:
               node_community[node] = idx

       # Node sizes (matplotlib uses area units, scale differently)
       if node_size_by == "weighted_degree":
           raw = dict(G.degree(weight="weight"))
       elif node_size_by == "case_count":
           raw = {n: G.nodes[n].get("case_count", 1) for n in G.nodes}
       else:
           raw = {n: 1 for n in G.nodes}
       max_val = max(raw.values()) if raw else 1
       min_s, max_s = 300, 2000

       def scale(v):
           if max_val <= 1:
               return (min_s + max_s) / 2
           return min_s + (v / max_val) * (max_s - min_s)

       node_list = list(G.nodes)
       node_sizes = [scale(raw[n]) for n in node_list]
       node_colors = [COMMUNITY_COLORS[node_community.get(n, 0) % len(COMMUNITY_COLORS)] for n in node_list]

       # Layout: community-aware spring layout (same algorithm as PyVis)
       n_comm = len(communities)
       initial_pos = {}
       radius = 3.0
       for i, comm in enumerate(communities):
           angle = 2 * math.pi * i / max(n_comm, 1)
           cx = math.cos(angle) * radius
           cy = math.sin(angle) * radius
           for j, node in enumerate(sorted(comm)):
               jitter_angle = 2 * math.pi * j / max(len(comm), 1)
               initial_pos[node] = (
                   cx + math.cos(jitter_angle) * 0.5,
                   cy + math.sin(jitter_angle) * 0.5,
               )
       pos = nx.spring_layout(
           G, pos=initial_pos,
           k=2.0 / math.sqrt(max(G.number_of_nodes(), 1)),
           iterations=150, seed=42, weight="weight",
       )

       # Filter edges
       max_weight = max((d["weight"] for _, _, d in G.edges(data=True)), default=1)
       filtered_edges = [(u, v, d) for u, v, d in G.edges(data=True) if d["weight"] >= edge_threshold]

       # Draw
       fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)
       fig.set_facecolor("#ffffff")
       ax.set_facecolor("#ffffff")

       # Edges with per-edge alpha and community coloring
       for u, v, d in filtered_edges:
           w = d["weight"]
           width = max(0.3, w / max_weight * 3)
           if opacity_scaling:
               alpha = max(0.05, min(0.7, w / max_weight))
           else:
               alpha = 0.4
           comm_u = node_community.get(u, -1)
           comm_v = node_community.get(v, -1)
           if comm_u == comm_v and comm_u >= 0:
               color = COMMUNITY_COLORS[comm_u % len(COMMUNITY_COLORS)]
           else:
               color = "#999999"
           ax.plot(
               [pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]],
               color=color, alpha=alpha, linewidth=width, zorder=1,
           )

       # Nodes
       nx.draw_networkx_nodes(
           G, pos, ax=ax, nodelist=node_list,
           node_size=node_sizes, node_color=node_colors,
           edgecolors=[_darken_hex(COMMUNITY_COLORS[node_community.get(n, 0) % len(COMMUNITY_COLORS)], 0.3) for n in node_list],
           linewidths=1.5, zorder=2,
       )

       # Labels inside nodes (white text)
       for node in node_list:
           x, y = pos[node]
           label = _format_label(node, max_line_len=14)
           area = scale(raw[node])
           font_size = max(5, min(9, area / 200))
           ax.text(
               x, y, label, ha="center", va="center",
               fontsize=font_size, color="white", fontweight="bold", zorder=3,
           )

       # Community legend
       legend_handles = []
       for i, comm in enumerate(sorted(communities, key=len, reverse=True)):
           if i >= 8:
               break
           color = COMMUNITY_COLORS[i % len(COMMUNITY_COLORS)]
           patch = mpatches.Patch(color=color, label=f"Community {i} ({len(comm)})")
           legend_handles.append(patch)
       ax.legend(handles=legend_handles, loc="upper left", fontsize=8, framealpha=0.8)

       ax.axis("off")
       fig.tight_layout(pad=0.5)
       return fig


   def export_figure_bytes(fig, fmt: str = "png", dpi: int = 150) -> bytes:
       """Export a matplotlib figure to bytes (PNG or SVG)."""
       buf = io.BytesIO()
       fig.savefig(buf, format=fmt, dpi=dpi, bbox_inches="tight",
                   facecolor=fig.get_facecolor())
       buf.seek(0)
       return buf.getvalue()


--- PART B: pipeline_ui.py ---

3. Update the import line (line 27). OLD:

       from network.visualize import build_pyvis_html, get_community_summary

   NEW:

       from network.visualize import build_pyvis_html, get_community_summary, build_matplotlib_figure, export_figure_bytes

4. Add session state inits (near the network_html init from NET-4):

       if "network_png" not in st.session_state:
           st.session_state.network_png = None
       if "network_svg" not in st.session_state:
           st.session_state.network_svg = None

5. In the graph export row added by NET-4 (dl4, dl5, dl6 columns), fill in
   dl5 and dl6 with PNG/SVG generation. After the dl4 HTML button:

       # PNG export
       if dl5.button("Generate PNG", key="gen_png"):
           with st.spinner("Rendering PNG..."):
               fig = build_matplotlib_figure(
                   G, edge_threshold=edge_thresh, node_size_by=size_by,
                   opacity_scaling=opacity_scaling,
               )
               st.session_state.network_png = export_figure_bytes(fig, fmt="png", dpi=150)
               import matplotlib.pyplot as plt
               plt.close(fig)
       if st.session_state.network_png:
           dl5.download_button(
               "Download PNG",
               data=st.session_state.network_png,
               file_name="justice_network.png",
               mime="image/png",
               key="dl_png",
           )

       # SVG export
       if dl6.button("Generate SVG", key="gen_svg"):
           with st.spinner("Rendering SVG..."):
               fig = build_matplotlib_figure(
                   G, edge_threshold=edge_thresh, node_size_by=size_by,
                   opacity_scaling=opacity_scaling,
               )
               st.session_state.network_svg = export_figure_bytes(fig, fmt="svg")
               import matplotlib.pyplot as plt
               plt.close(fig)
       if st.session_state.network_svg:
           dl6.download_button(
               "Download SVG",
               data=st.session_state.network_svg,
               file_name="justice_network.svg",
               mime="image/svg+xml",
               key="dl_svg",
           )

[Constraints]:
- matplotlib.use("Agg") MUST be called before any plt import to prevent Tkinter
  backend crash in Streamlit's headless environment.
- plt.close(fig) after export_figure_bytes() — prevents memory leaks.
- The matplotlib render must use the SAME seed (42), same community detection,
  same colors as the PyVis version so exports match the interactive view.
- SVG: do NOT pass dpi (no effect on vector). export_figure_bytes handles this.
- "Generate PNG"/"Generate SVG" buttons render on demand to avoid expensive
  computation on every Streamlit rerun. Download buttons appear after generation.
- Do NOT add matplotlib to requirements.txt — it's already installed (3.10.6).
```

---

### Date Correction (DATE-1, DATE-2, DATE-3)
- [x] **DATE-1**: Date prefix stripping — `_strip_date_prefix()` in `csv_extractor.py` strips G.R. number fragments from date text (e.g., "73978-80. April 26, 1939" → "April 26, 1939"). JSON predictions untouched.
- [x] **DATE-2**: Volume-contextual OCR date correction — `_sanitize_dates()` computes per-volume median date, detects outliers >730 days from median, applies single-digit `_OCR_DIGIT_SWAPS` to auto-correct. Adds `date_original` + `date_warning` CSV columns. 12 corrections, 2 unfixed outliers, 0 false positives across 36,993 cases.
- [x] **DATE-3**: Verified all 5 original targets corrected + 7 bonus OCR catches (4987→1987, March 36→30, 1994→1991, 1993→1995 x3, 2063→2003). 2 unfixed outliers flagged (Vol 833 genuine mismatch, Vol 898 unparseable).

### Volume 515 Missed Cases (V515-1 thru V515-5)
- [x] **V515-1**: `normalize_division_line()` helper in `pattern_registry.py` strips OCR garbage (smart quotes, `_`, `-`, `"`, `'`) at leading/trailing edges. Wired into `boundary_fsm._match_division_with_fallthrough`, `preprocess._classify_noise`, and 4 `section_extractor.py` call sites.
- [x] **V515-2**: `re_division` widened to allow optional leading uppercase word (e.g., `SPECIAL THIRD DIVISION`).
- [x] **V515-3**: `re_case_bracket` + `re_case_bracket_no_close` extended to match `A.C. No.`, `B.M. No.`, `OCA IPI No.` prefixes. Volume_226 regression check still finds 72 boundaries.
- [x] **V515-4**: `recover_stranded_brackets()` post-pass in `boundary_fsm.py` recovers case brackets unclaimed by any boundary using loose "DIVIS"/"BANC" substring match within 8 non-noise lines backward. Volume_515 detection: 47 → 54 cases (7 of 8 target cases recovered).
- [x] **V515-5**: `re_case_bracket` + `re_case_bracket_no_close` widened with leading-garbage class `[\s\*\u2022\u00b7]*` and separator `:` (handles `::` OCR for `.`). Recovers case_49 at Volume_515 page 325 (`* [A.M. No. 01-34-CA-J::January 23, 2006}`). Volume_515 detection: 54 → 55 cases; Volume_226 regression still at 72 boundaries.

---

## NOTE: Future — Batch scoring support

> **Do not implement yet.** Placeholder for the iteration loop.

The current `--score` flag works single-volume only (disabled in batch mode, `__main__.py` line 171). For the iterative pattern-tuning loop (run detection across 5 ground-truth volumes, score each, compare across eras), batch scoring would eliminate repetitive manual commands.

**Desired behavior:**
```bash
python -m detection ../downloads --range 226-960 --score ground_truth.json
# → runs all 5 GT volumes, scores each, produces per-era summary table
```

**Would need:**
- `scorer.py`: new `score_batch()` that iterates volumes in the GT file, matches each to its prediction, returns per-volume + per-era aggregated results.
- `__main__.py`: remove batch-mode scoring warning (line 171), wire up batch scoring.
- `format_results_table()`: add era-grouped summary view (per-era F1, per-label × per-era breakdown).
- Compare regex-only vs regex+LLM side by side in the same report.

---

