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

---

## Active Tasks

(No active tasks.)

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
