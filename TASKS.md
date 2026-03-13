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

**Status:** DONE
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

**Status:** DONE
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

**Status:** DONE
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

**Status:** DONE
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

**Status:** DONE
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

**Status:** DONE
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

### FIX-7: Separate Opinion Regression — Opinions Lost After FIX-1 Votes Termination

**Status:** DONE
**Estimated impact:** 3 cases in Volume 227 (G.R. 63070, G.R. 70742, G.R. 62887)
**Depends on:** FIX-1
**Files to modify:**
- `regex_improve/detection/section_extractor.py`

**Root cause:** FIX-1 votes extraction loop breaks at `RE_SEPARATE_OPINION`, but `votes_end_idx` points to the line *after* the last votes line, not the opinion line. Blank lines between votes and the opinion header cause the opinion check (which starts scanning at `votes_end_idx`) to miss it.

**Code changes:**
1. Initialize `separate_opinion_idx = None` before the votes loop
2. Save `separate_opinion_idx = i` when breaking at `RE_SEPARATE_OPINION`
3. After votes extraction, use tracked `separate_opinion_idx` directly if available; otherwise scan forward from `votes_end_idx` up to 10 lines looking for `RE_SEPARATE_OPINION`, stopping early at division/case bracket boundaries

**Expected result:** All 3 separate opinions in Volume 227 detected (matching human ground truth).

**Constraints:**
- Do not change the votes extraction loop's termination logic (FIX-1)
- Forward scan must stop at RE_DIVISION / RE_CASE_BRACKET to prevent false matches into the next case

---

### FIX Dependency Graph

```
FIX-1 (votes overflow)     -- independent
FIX-2 (missed boundaries)  -- independent
FIX-3 (quoted SO ORDERED)  -- independent
FIX-4 (counsel overflow)   -- independent
FIX-5 (parties footnotes)  -- independent
FIX-6 (page number bug)    -- independent
FIX-7 (opinion regression) -- depends on FIX-1

All are independent except FIX-7 (which depends on FIX-1).
FIX-1 + FIX-2 together fix ~80% of corrections.
After all fixes, re-run on Volume 226 (regression test) and Volume 227 (improvement test).
```

---

## OCR Repair Tools

### TOOL-1: Patch Blank Pages — Re-OCR Blank Pages from Original PDFs

**Status:** DONE
**Depends on:** None (standalone tool)
**Files created:**
- `regex_improve/detection/patch_blank_pages.py`

**Root cause:** Tesseract occasionally produces no text for pages that have real content in the PDF (3,594 blank content pages across 377 volumes). This causes the detection pipeline to miss cases that start on or span those pages (e.g., People vs. Poyos in Volume 227, page 517).

**Solution:** A general-purpose CLI tool that:
1. Scans `.txt` files for blank pages (consecutive `--- Page N ---` markers with no text between them)
2. Skips front/back matter (pages 1-10 and last 10)
3. Re-OCRs blank pages from the original PDF using a **multi-strategy approach** (raw first, preprocessed second, high-DPI raw third)
4. Patches the text file in-place with the re-OCR'd content
5. Creates `.txt.bak` backup before modification
6. Reports which pages were patched vs. genuinely blank (below `--min-chars` threshold)

**Multi-strategy OCR** (tries in order, stops at first success >= `min_chars`):
1. **Raw OCR** — no preprocessing, just Tesseract on the grayscale image (primary strategy since preprocessing caused the blanks)
2. **Preprocessed OCR** — same pipeline as `02_processor.ipynb` (requires cv2; skipped with warning if unavailable)
3. **Raw OCR @400 DPI** — higher resolution raw image (only if default DPI < 400)

**Features:**
- Single file or batch directory mode
- `--dry-run` scan-only mode (no PDF/OCR dependencies needed)
- Configurable DPI, min-chars threshold, backup toggle
- Processes pages in reverse order to avoid position-shifting bugs
- Graceful cv2 fallback — works without opencv (raw-only strategies)

**Usage:** See `regex_improve/detection/Instructions.txt` section 9.

---

## Dynamic Justice Registry Tasks

These tasks replace the hardcoded `KNOWN_JUSTICES` list in `ocr_correction.py` with a dynamically-growing `justices.json` file. A separate CLI command harvests high-confidence ponente names from pipeline output and appends new justices to the registry. After harvesting, already-processed volumes can be re-run to benefit from the expanded list.

---

### KJ-1: Justice Registry — Seed File + Loader + Wiring

**Status:** DONE
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

**Status:** DONE
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
   - The JSON structure is: `data["volumes"][i]["cases"][j]` — iterate over all volumes, then all cases within each volume
   - For each case:
     - Parse the confidence score from `case["notes"]` field (format: `"confidence: 0.950"`)
     - If confidence score < threshold, skip
     - Find the annotation with `label == "ponente"` in `case["annotations"]`
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

**Status:** DONE
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

## Self-Diagnostic Failure Reporting (DIAG-1, DIAG-2, DIAG-3)

Volume-level diagnostics that run automatically on every pipeline invocation. Aggregates failure signals to help identify when the pipeline hits unfamiliar formatting. Output is appended to the existing `.log` file (no changes to `predicted.json`). Report-only — no automatic pipeline behavior changes.

---

### DIAG-1: Diagnostics Module — Statistical Checks

**Status:** DONE
**Depends on:** T8 (pipeline.py)
**Files to create:**
- `regex_improve/detection/diagnostics.py`

**Description:**
Create a diagnostics module that takes a `PipelineResult` and produces a `DiagnosticReport` with 4 statistical checks. Each check produces a severity level (`ok`, `warning`, `critical`) and a human-readable message.

#### `regex_improve/detection/diagnostics.py`

**Imports:**
```python
import statistics
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
```

**Data classes:**

```python
@dataclass
class DiagnosticCheck:
    """Single diagnostic check result."""
    name: str           # e.g., "mean_confidence"
    severity: str       # "ok", "warning", "critical"
    message: str        # human-readable summary
    value: Any          # the measured value (for programmatic use)

@dataclass
class DiagnosticReport:
    """Full diagnostic report for a volume."""
    checks: List[DiagnosticCheck] = field(default_factory=list)
    near_misses: List[Dict[str, Any]] = field(default_factory=list)  # DIAG-2

    @property
    def worst_severity(self) -> str:
        """Return the worst severity across all checks."""
        if any(c.severity == "critical" for c in self.checks):
            return "critical"
        if any(c.severity == "warning" for c in self.checks):
            return "warning"
        return "ok"
```

**Functions:**

1. `check_mean_confidence(cases: List[Dict]) -> DiagnosticCheck`:
   - Compute mean confidence score across all cases (from `case["confidence_score"]`)
   - Thresholds:
     - `>= 0.75` -> `ok`: "Mean confidence {score:.3f} (healthy)"
     - `>= 0.60` -> `warning`: "Mean confidence {score:.3f} -- some cases may have unfamiliar formatting"
     - `< 0.60` -> `critical`: "Mean confidence {score:.3f} -- unfamiliar formatting detected, consider annotating ground truth for this era"
   - If no cases, return `warning` with message "No cases detected"

2. `check_missing_required_labels(cases: List[Dict]) -> DiagnosticCheck`:
   - For each case, check if `case_number`, `date`, and `doc_type` annotations are present
   - Compute the percentage of cases missing ANY of these 3 labels
   - Thresholds:
     - `<= 5%` -> `ok`: "Required labels present in {pct:.0f}% of cases"
     - `<= 15%` -> `warning`: "{count} cases ({pct:.0f}%) missing case_number/date/doc_type -- bracket regex may be failing"
     - `> 15%` -> `critical`: "{count} cases ({pct:.0f}%) missing required labels -- bracket regex likely failing for this era"
   - Also list which specific labels are most commonly missing (top 3)

3. `check_span_lengths(cases: List[Dict]) -> DiagnosticCheck`:
   - Collect text lengths for `parties` and `votes` annotations across all cases
   - Compute mean and standard deviation for each
   - Flag cases where span length is > 3 standard deviations from mean
   - Thresholds:
     - 0 outliers -> `ok`: "Span lengths normal (parties: mean {p_mean:.0f} chars, votes: mean {v_mean:.0f} chars)"
     - 1-3 outliers -> `warning`: "{count} cases with outlier span lengths" + list the case_ids
     - `> 3` outliers -> `critical`: "{count} cases with outlier span lengths -- extraction boundaries may be wrong"
   - If fewer than 5 cases have a given label, skip stddev check for that label (too few samples)

4. `check_confidence_distribution(cases: List[Dict]) -> DiagnosticCheck`:
   - Count cases in confidence buckets: `[0.0-0.5)`, `[0.5-0.7)`, `[0.7-0.9)`, `[0.9-1.0]`
   - Report distribution as a histogram line: e.g., `"[0-0.5): 2 | [0.5-0.7): 5 | [0.7-0.9): 40 | [0.9-1.0]: 25"`
   - Thresholds:
     - `>= 70%` in top two buckets -> `ok`
     - `>= 50%` in top two buckets -> `warning`: "Only {pct:.0f}% of cases above 0.7 confidence"
     - `< 50%` in top two buckets -> `critical`: "Majority of cases below 0.7 confidence"

5. `run_diagnostics(cases: List[Dict]) -> DiagnosticReport`:
   - Call all 4 check functions
   - Return `DiagnosticReport` with the results
   - `near_misses` field is left empty (populated by DIAG-2)

**`if __name__ == "__main__"` test block:**
- Create mock cases with known scores and annotations
- Run `run_diagnostics()` and print results
- Test edge cases: empty case list, all-perfect scores, all-terrible scores

**Constraints:**
- Zero external dependencies (stdlib only)
- Do NOT import from `pipeline.py` (avoid circular import) — the function takes `List[Dict]` not `PipelineResult`
- Do NOT use Unicode characters in print statements
- Each check function is independent and testable in isolation
- Severity strings must be exactly `"ok"`, `"warning"`, or `"critical"` (lowercase)

---

### DIAG-2: Near-Miss Pattern Detection

**Status:** DONE
**Depends on:** DIAG-1
**Files to modify:**
- `regex_improve/detection/diagnostics.py`

**Description:**
Add a function that scans the raw volume text for lines that *almost* match structural patterns but don't fully match. These near-misses are candidates for regex updates when expanding to new eras.

**Function to add:**

`find_near_misses(volume_text: str, matched_lines: set) -> List[Dict[str, Any]]`:

- `volume_text`: the full volume text
- `matched_lines`: set of 1-based line numbers that were already matched by the pipeline (division headers, case brackets, etc.) — passed in from the pipeline so we don't re-report things that already matched

**Near-miss patterns to scan for** (define as module-level compiled regexes with prefix `RE_NEAR_`):

1. **Near-miss division headers** (`RE_NEAR_DIVISION`):
   - Lines that contain "DIVISION" or "EN BANC" but didn't match `RE_DIVISION`
   - Pattern: `r'(?:DIVISION|EN\s*BANC)'` (case-insensitive)
   - Filter out: lines already in `matched_lines`, lines inside the body of a case (heuristic: ignore lines > 200 chars), lines that are part of "PHILIPPINE REPORTS" headers

2. **Near-miss case brackets** (`RE_NEAR_BRACKET`):
   - Lines containing "G.R." or "A.M." followed by "No" but not matched by `RE_CASE_BRACKET` or `RE_CASE_BRACKET_NO_CLOSE`
   - Pattern: `r'(?:G\.?\s*R\.?\s*No|A\.?\s*M\.?\s*No)'` (case-insensitive)
   - Filter out: lines already in `matched_lines`, lines inside syllabus/opinion text (heuristic: ignore if the line is > 150 chars, as bracket lines are short)

3. **Near-miss SO ORDERED** (`RE_NEAR_SO_ORDERED`):
   - Lines containing "SO ORDERED" that didn't match `RE_SO_ORDERED`
   - Pattern: `r'SO\s*ORDERED'` (case-insensitive)
   - Filter out: lines already in `matched_lines`

4. **Near-miss doc type** (`RE_NEAR_DOC_TYPE`):
   - Lines containing "DECISION" or "RESOLUTION" as a standalone word but not matched by `RE_DOC_TYPE`
   - Pattern: `r'\b(?:D\s*E\s*C\s*I\s*S\s*I\s*O\s*N|R\s*E\s*S\s*O\s*L\s*U\s*T\s*I\s*O\s*N)\b'`
   - Filter out: lines already in `matched_lines`, lines > 100 chars

**Output format** for each near-miss:
```python
{
    "line_num": int,       # 1-based line number
    "pattern": str,        # which near-miss pattern matched (e.g., "division", "bracket", "so_ordered", "doc_type")
    "text": str,           # the line text (truncated to 120 chars)
}
```

**Cap:** Return at most 30 near-misses total (sorted by line number). If more than 30, keep the first 30 and add a summary entry: `{"line_num": 0, "pattern": "overflow", "text": "... and N more near-misses truncated"}`.

**Update `run_diagnostics`:**
- Add optional parameters: `volume_text: Optional[str] = None` and `matched_lines: Optional[set] = None`
- If both are provided, call `find_near_misses()` and populate `report.near_misses`
- If not provided, skip near-miss detection (backwards compatible)

**Constraints:**
- Do NOT import `RE_DIVISION`, `RE_CASE_BRACKET`, etc. — define independent near-miss patterns in this module to avoid coupling
- The near-miss regexes should be MORE lenient than the real patterns (that's the point — they catch what the real patterns miss)
- Line length filters are important to avoid flooding output with body text that happens to contain "DECISION"
- Do NOT use Unicode characters in print statements
- Must handle empty `volume_text` gracefully (return empty list)

---

### DIAG-3: Wire Diagnostics into Pipeline and Log Output

**Status:** DONE
**Depends on:** DIAG-1, DIAG-2
**Files to modify:**
- `regex_improve/detection/pipeline.py`

**Description:**
Wire the diagnostics module into the pipeline so it runs on every invocation. Collect the set of matched lines during boundary detection/section extraction, pass them to diagnostics, and append results to the `.log` file.

#### Changes to `regex_improve/detection/pipeline.py`

**1. Add import (at top, with other detection imports):**
```python
from .diagnostics import run_diagnostics, DiagnosticReport
```

**2. Collect matched lines in `process_volume()` (after Step 3, around line 109):**

After `extractor.extract_all(boundaries)` returns, build the set of matched line numbers. These are lines that the pipeline already matched as structural elements:

```python
# Collect matched line numbers for near-miss detection
matched_lines = set()
for boundary in boundaries:
    matched_lines.add(boundary.division_line)
    matched_lines.add(boundary.start_line)
    # Add bracket lines
    for cn in boundary.case_numbers:
        start_line = preprocessor.loader.char_to_line(cn.start_char)
        end_line = preprocessor.loader.char_to_line(cn.end_char - 1)
        for ln in range(start_line, end_line + 1):
            matched_lines.add(ln)
```

Note: check that `boundary` objects actually have `division_line` and `start_line` attributes. If not, use whatever attributes store the line numbers of matched structural elements. Read the `CaseBoundary` dataclass in `boundary_fsm.py` to confirm the correct attribute names.

**3. Run diagnostics (after Step 7, before writing the log, around line 330):**

```python
# Step 8: Run diagnostics
logger.info("Step 8: Running diagnostics...")
diagnostic_report = run_diagnostics(
    all_cases,
    volume_text=volume_text,
    matched_lines=matched_lines
)
```

**4. Add `diagnostic_report` to `PipelineResult`:**

Add a new field to `PipelineResult`:
```python
diagnostics: Optional[Dict[str, Any]] = None
```

Set it after running diagnostics:
```python
result.diagnostics = {
    "worst_severity": diagnostic_report.worst_severity,
    "checks": [
        {"name": c.name, "severity": c.severity, "message": c.message}
        for c in diagnostic_report.checks
    ],
    "near_miss_count": len(diagnostic_report.near_misses)
}
```

**5. Update `write_summary_log()` to include diagnostics:**

After the "PER-CASE DETAILS" section and before "END OF LOG", add a new section:

```python
# Diagnostics section
if result.diagnostics:
    lines.append("DIAGNOSTICS")
    lines.append("-" * 40)
    lines.append(f"  Overall: {result.diagnostics['worst_severity'].upper()}")
    lines.append("")
    for check in result.diagnostics["checks"]:
        severity_marker = {"ok": "  ", "warning": "! ", "critical": "!!"}
        marker = severity_marker.get(check["severity"], "  ")
        lines.append(f"  {marker}{check['name']}")
        lines.append(f"      {check['message']}")
    lines.append("")

    if result.diagnostics.get("near_misses"):
        lines.append("  NEAR-MISS PATTERN MATCHES")
        lines.append("  " + "-" * 36)
        for nm in result.diagnostics["near_misses"]:
            lines.append(f"    Line {nm['line_num']:>6d}  [{nm['pattern']:<12s}]  {nm['text']}")
        lines.append("")
```

Wait — `result.diagnostics` as defined in step 4 doesn't include `near_misses` list (only `near_miss_count`). To include the actual near-miss lines in the log, either:
- (a) Store the full `near_misses` list in `result.diagnostics`, or
- (b) Pass the `DiagnosticReport` object directly to `write_summary_log`

Option (b) is cleaner. Change `write_summary_log` signature to accept an optional `DiagnosticReport`:

```python
def write_summary_log(result: PipelineResult, budget: BudgetTracker,
                      log_path: Path, diagnostic_report: DiagnosticReport = None) -> None:
```

Then use `diagnostic_report` directly in the log writer instead of going through `result.diagnostics`. Still store the summary dict in `result.diagnostics` for programmatic access.

Update the call site:
```python
write_summary_log(result, budget, log_path, diagnostic_report=diagnostic_report)
```

**6. Print diagnostics to console in `print_summary()`:**

After existing print statements, add:
```python
if result.diagnostics:
    worst = result.diagnostics["worst_severity"]
    if worst != "ok":
        print(f"\n  DIAGNOSTICS: {worst.upper()}")
        for check in result.diagnostics["checks"]:
            if check["severity"] != "ok":
                marker = "!" if check["severity"] == "warning" else "!!"
                print(f"    {marker} {check['message']}")
        nm_count = result.diagnostics.get("near_miss_count", 0)
        if nm_count > 0:
            print(f"    {nm_count} near-miss pattern matches (see .log for details)")
```

Only print diagnostics to console if there are warnings/criticals. If everything is `ok`, stay quiet on console (details are always in the `.log`).

**7. Update batch summary:**

In `write_batch_summary_log()`, after per-volume results, add a line showing the worst diagnostic severity per volume:

```python
for vol in summary['volume_results']:
    diag_status = vol.get('diagnostics_severity', 'N/A')
    lines.append(f"  {vol['volume']:<30s} {vol['cases']:>3d} cases, "
                 f"{vol['llm_calls']:>2d} LLM calls, ${vol['llm_cost']:.4f}, "
                 f"diag: {diag_status}")
```

This requires storing `diagnostics_severity` in the per-volume result dict during `process_batch`. Add it where volume results are appended (around line 420):

```python
volume_result = {
    "volume": vol_path.name,
    "cases": len(result.cases),
    "llm_calls": result.llm_calls,
    "llm_cost": result.llm_cost,
    "diagnostics_severity": result.diagnostics.get("worst_severity", "N/A") if result.diagnostics else "N/A"
}
```

**Constraints:**
- Do NOT change the `predicted.json` output format — diagnostics go in `.log` only
- Diagnostics must not crash the pipeline — wrap in try/except, log errors, continue
- Console output for diagnostics only appears when there are warnings/criticals
- The `.log` file always includes the full diagnostics section (even when all `ok`)
- Do NOT use Unicode characters in print statements
- Step numbers in log messages should update (current "Step 7: Assembling final JSON" stays, diagnostics becomes "Step 8")
- The `volume_text` variable is already available in `process_volume` scope (loaded in Step 1)

---

### DIAG Dependency Graph

```
DIAG-1 (statistical checks)  ---- DIAG-2 (near-miss patterns) ---- DIAG-3 (pipeline wiring)
                                                                          |
                                                              DIAG-FIX-1 (calibration)
                                                              DIAG-FIX-2 (matched_lines)
```

DIAG-1 must be completed first. DIAG-2 adds to DIAG-1's module. DIAG-3 wires both into pipeline.
DIAG-FIX-1 and DIAG-FIX-2 are independent of each other but both depend on DIAG-3.

---

### DIAG File Tree

```
regex_improve/
├── detection/
│   ├── diagnostics.py          # DIAG-1 + DIAG-2 (new), DIAG-FIX-1 (modified)
│   ├── pipeline.py             # DIAG-3 (modified), DIAG-FIX-2 (modified)
│   └── ... (other existing files)
```

---

## Diagnostics Calibration Fixes (from Phase 1 Batch Run)

Phase 1 batch run (735 volumes, 226-960) revealed severely miscalibrated diagnostics: 149 critical, 570 warning, only 16 ok. Volume 226 (the ground truth basis volume, 0.926 mean confidence, 100% required labels) was rated **critical**. The diagnostics are producing false alarms, making them useless for identifying genuinely problematic volumes.

**Root causes:**
1. `span_lengths` check uses fixed count thresholds (>3 = critical) that don't scale with volume size
2. Near-miss patterns match body text far too aggressively (834 false positives on Vol 226 alone)
3. `matched_lines` set is incomplete — only boundary FSM lines are excluded, not section extractor matches

**Validation:** After fixes, re-run on Volume 226 and verify it gets `ok`. Check batch_summary.log: critical count should drop significantly, ok count should rise to be the majority for well-performing volumes.

---

### DIAG-FIX-1: Calibrate Thresholds and Tighten Near-Miss Patterns

**Status:** DONE
**Depends on:** DIAG-3
**Files to modify:**
- `regex_improve/detection/diagnostics.py`

**Description:**
Fix the span_lengths severity thresholds and tighten all 4 near-miss regex patterns to eliminate body text false positives.

#### Part A: Fix `check_span_lengths` thresholds

**Current bug (line 252-267):** Fixed count thresholds:
```python
elif len(outliers) <= 3:    # warning
else:                       # critical (>3 outliers)
```
A 72-case volume with 5 natural outliers (7%) hits `critical`. A 15-case volume with 4 outliers (27%) also hits `critical` — even though the second case is genuinely worse.

**Fix:** Replace fixed count thresholds with percentage-based:

```python
# Calculate outlier percentage
total_cases = len(cases)
outlier_pct = (len(outliers) / total_cases * 100) if total_cases > 0 else 0

if not outliers:
    severity = "ok"
    message = f"Span lengths normal (parties: mean {parties_mean_val:.0f} chars, votes: mean {votes_mean_val:.0f} chars)"
elif outlier_pct <= 10.0:
    severity = "warning"
    outlier_cases = sorted(set(o["case_id"] for o in outliers))
    message = f"{len(outliers)} cases ({outlier_pct:.0f}%) with outlier span lengths: {', '.join(outlier_cases[:5])}"
else:
    severity = "critical"
    outlier_cases = sorted(set(o["case_id"] for o in outliers))
    shown = outlier_cases[:5]
    message = f"{len(outliers)} cases ({outlier_pct:.0f}%) with outlier span lengths -- extraction boundaries may be wrong"
    if len(outlier_cases) > 5:
        message += f": {', '.join(shown)} and {len(outlier_cases) - 5} more"
    else:
        message += f": {', '.join(shown)}"
```

This means Vol 226's 5/72 (7%) → `warning` instead of `critical`.

#### Part B: Tighten `RE_NEAR_DOC_TYPE`

**Current bug:** Matches "DECISION" or "RESOLUTION" as a word anywhere in lines ≤ 100 chars. Body text like `"This is a petition to review the decision of the Employees'"` (84 chars) matches.

**Fix:** Replace the pattern and filter. A real doc_type header line is SHORT and contains ONLY the keyword (possibly with spacing/punctuation):

1. Replace `RE_NEAR_DOC_TYPE`:
   ```python
   RE_NEAR_DOC_TYPE = re.compile(
       r'^\s*(?:D\s*E\s*C\s*I\s*S\s*I\s*O\s*N|R\s*E\s*S\s*O\s*L\s*U\s*T\s*I\s*O\s*N)\s*$',
       re.IGNORECASE
   )
   ```
   Key changes: `^` anchor and `$` anchor — line must be ONLY the keyword (with optional whitespace). This eliminates all body text matches.

2. Update the filter in `find_near_misses` for doc_type: remove the `len(line) <= 100` check (the regex itself is now strict enough).

#### Part C: Tighten `RE_NEAR_BRACKET`

**Current bug:** Matches "G.R. No." or "A.M. No." anywhere in lines ≤ 150 chars. Case citations in body text like `"Employees' Compensation Commission (G.R. No. L-45662,"` match.

**Fix:** Require the G.R./A.M. pattern near the START of the line (within first 15 chars), since case bracket lines always start with `[G.R. No.` or similar:

1. Replace `RE_NEAR_BRACKET`:
   ```python
   RE_NEAR_BRACKET = re.compile(
       r'^[\[\(\{1I\s]{0,5}(?:G\.?\s*R\.?\s*No|A\.?\s*M\.?\s*No)',
       re.IGNORECASE
   )
   ```
   This allows 0-5 leading chars (bracket, OCR noise, whitespace) before the case number prefix. Body text citations mid-sentence will NOT match.

2. Remove the `len(line) <= 150` filter for bracket (the anchored regex is now sufficient).

#### Part D: Tighten `RE_NEAR_DIVISION`

**Current bug:** Matches "DIVISION" anywhere in the line. Court names like `"APPELLATE COURT (Third Civil Cases Division),"` match.

**Fix:** Only match lines where the division text is the dominant content:

1. Replace `RE_NEAR_DIVISION`:
   ```python
   RE_NEAR_DIVISION = re.compile(
       r'^\s*(?:(?:FIRST|SECOND|THIRD)\s+DIVISION|EN\s*BANC)\s*$',
       re.IGNORECASE
   )
   ```
   Anchored to start/end, requires a specific division name. This eliminates court name matches.

2. Remove the `"PHILIPPINE REPORTS" not in line.upper()` filter (no longer needed with the strict regex).

#### Part E: Tighten `RE_NEAR_SO_ORDERED`

**Current behavior:** Matches "SO ORDERED" anywhere. This is actually reasonable, but many matches are legitimate SO ORDERED lines that the pipeline DID match — they're just not in `matched_lines` (fixed by DIAG-FIX-2). For now, add a line-anchored version:

1. Replace `RE_NEAR_SO_ORDERED`:
   ```python
   RE_NEAR_SO_ORDERED = re.compile(
       r'^\s*SO\s*ORDERED\s*[.,;]?\s*$',
       re.IGNORECASE
   )
   ```
   Anchored — only matches standalone SO ORDERED lines. Body text containing "so ordered" mid-sentence is excluded.

#### Part F: Update `find_near_misses` filter logic

After tightening all regexes, simplify the filter logic in `find_near_misses`. The anchored regexes now handle most filtering, so remove the per-pattern length checks:

```python
for line_num, line in enumerate(lines, start=1):
    if line_num in matched_lines:
        continue

    # Skip very long lines (body text, not structural)
    if len(line) > 200:
        continue

    # Check each near-miss pattern (order: most specific first)
    pattern_matched = None

    if RE_NEAR_BRACKET.match(line):
        pattern_matched = "bracket"
    elif RE_NEAR_DIVISION.match(line):
        pattern_matched = "division"
    elif RE_NEAR_SO_ORDERED.match(line):
        pattern_matched = "so_ordered"
    elif RE_NEAR_DOC_TYPE.match(line):
        pattern_matched = "doc_type"

    if pattern_matched:
        near_misses.append({
            "line_num": line_num,
            "pattern": pattern_matched,
            "text": line[:120]
        })
```

Note: all near-miss regexes now use `.match()` (anchored) instead of `.search()`.

**Constraints:**
- Do NOT change `check_mean_confidence`, `check_missing_required_labels`, or `check_confidence_distribution` — those are already well-calibrated
- Do NOT change the near-miss output format (line_num, pattern, text)
- Do NOT change the 30-item cap logic
- Do NOT use Unicode characters in print statements
- Update the `__main__` test block to reflect the tightened patterns (the existing test for near-misses will need adjusted line content)

---

### DIAG-FIX-2: Expand matched_lines to Include Section Extractor Matches

**Status:** DONE
**Depends on:** DIAG-3
**Files to modify:**
- `regex_improve/detection/pipeline.py`

**Description:**
The `matched_lines` set in `process_volume()` currently only includes boundary FSM lines (division headers and bracket lines). Section extractor structural matches (SO ORDERED, DECISION/RESOLUTION, SYLLABUS, COUNSEL HEADER, etc.) are not excluded, causing them to appear as false near-misses.

**Current code (pipeline.py, after Step 3):**
```python
matched_lines = set()
for boundary in boundaries:
    matched_lines.add(boundary.start_line)
    for cn in boundary.case_numbers:
        start_line = preprocessor.loader.char_to_line(cn.start_char)
        end_line = preprocessor.loader.char_to_line(cn.end_char - 1)
        for line_num in range(start_line, end_line + 1):
            matched_lines.add(line_num)
```

**Fix:** After Step 3 (`extractor.extract_all(boundaries)`), iterate over extracted cases and add all annotation start/end lines to `matched_lines`. Every annotation represents a line (or range of lines) that the section extractor successfully matched:

```python
# Collect matched line numbers for near-miss detection
matched_lines = set()

# From boundary FSM: division headers and bracket lines
for boundary in boundaries:
    matched_lines.add(boundary.start_line)
    for cn in boundary.case_numbers:
        start_line = preprocessor.loader.char_to_line(cn.start_char)
        end_line = preprocessor.loader.char_to_line(cn.end_char - 1)
        for line_num in range(start_line, end_line + 1):
            matched_lines.add(line_num)

# From section extractor: all annotation lines
for case in extracted_cases:
    for ann in case.annotations:
        ann_start_line = preprocessor.loader.char_to_line(ann.start_char)
        ann_end_line = preprocessor.loader.char_to_line(ann.end_char - 1)
        # For position labels (start_of_case, end_decision, etc.), add exact line
        # For span labels (parties, counsel, votes), add the start line only
        # to avoid over-excluding body text within the span
        if ann.label in ("start_of_case", "end_of_case", "start_decision",
                         "end_decision", "start_syllabus", "end_syllabus",
                         "start_opinion", "end_opinion", "division",
                         "doc_type", "ponente"):
            # Position/header labels: add all lines in the span
            for line_num in range(ann_start_line, ann_end_line + 1):
                matched_lines.add(line_num)
        elif ann.label in ("case_number", "date"):
            # Short labels: add all lines
            for line_num in range(ann_start_line, ann_end_line + 1):
                matched_lines.add(line_num)
        else:
            # Long span labels (parties, counsel, votes, syllabus content):
            # Only add the first and last line to avoid masking body text issues
            matched_lines.add(ann_start_line)
            matched_lines.add(ann_end_line)
```

**Why split by label type:**
- Position/header labels (`doc_type`, `division`, `ponente`, `start_decision`, etc.) are exactly the lines that near-miss detection would otherwise flag. All their lines must be excluded.
- Long span labels (`parties`, `counsel`, `votes`) cover many body text lines. Excluding ALL of them would hide genuinely unmatched structural lines within those spans. Only exclude the first/last lines.

**Note:** Access `ann.start_char` and `ann.end_char` directly — the `case.annotations` list at this point contains `Annotation` dataclass objects (not dicts yet, that conversion happens in Step 4).

**Constraints:**
- Do NOT change how `matched_lines` is passed to `run_diagnostics` — only change how it's populated
- Do NOT modify the section extractor — only read its output
- The annotation objects at this stage are `Annotation` dataclasses with `.label`, `.start_char`, `.end_char` attributes
- Do NOT use Unicode characters in print statements

---

### DIAG-FIX Dependency Graph

```
DIAG-FIX-1 (calibrate thresholds + tighten patterns)  -- independent
DIAG-FIX-2 (expand matched_lines)                     -- independent

Both depend on DIAG-3 (already done).
Can be done in parallel. Both should be applied before re-running batch.
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
│   ├── pipeline.py              # T8 (DIAG-3: wires diagnostics)
│   ├── diagnostics.py           # DIAG-1 + DIAG-2
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
