# DETECTION_PLAN.md — Automated Case Data Extraction Pipeline

**Target corpus:** Philippine Supreme Court Reports, Volumes 226–961 (~735 volumes, 1986–2024)
**Benchmark:** 72 annotated cases from Volume 226 (`ground_truth_20260309_144413.json`)
**Date:** 2026-03-09

---

## Table of Contents

1. [Difficulty Analysis Per Label](#1-difficulty-analysis-per-label)
2. [Methodology Comparison](#2-methodology-comparison)
3. [Pipeline Architecture](#3-pipeline-architecture)
4. [Evaluation Framework](#4-evaluation-framework)
5. [Cost Model](#5-cost-model)
6. [Task Breakdown](#6-task-breakdown)
7. [Iteration Strategy](#7-iteration-strategy)

---

## 1. Difficulty Analysis Per Label

Assessed against the 72 annotated cases in Volume 226. Each label is rated on a five-tier scale: **Trivial / Easy / Medium / Hard / Very Hard**.

### Tier 1 — Trivial (fixed-keyword anchors, regex-perfect)

| Label | Count | Approach | Justification |
|-------|-------|----------|---------------|
| **start_syllabus** | 72 | Exact match `SYLLABUS` | Always the literal word "SYLLABUS" on its own line. 71 occurrences in Vol 226 text (count includes TOC reference; filter by position after case bracket). **Caveat:** Vanishes entirely in modern volumes (~Vol 900+). |
| **doc_type** | 72 | Regex `^DECISION$\|^RESOLUTION$\|^D\s*E\s*C\s*I\s*S\s*I\s*O\s*N$\|^R\s*E\s*S\s*O\s*L\s*U\s*T\s*I\s*O\s*N$` | Always appears on its own line. Two values: "DECISION" (61) and "RESOLUTION" (11). Post-2011 volumes use spaced variant `D E C I S I O N`. |

### Tier 2 — Easy (structural patterns, high-confidence regex)

| Label | Count | Approach | Justification |
|-------|-------|----------|---------------|
| **start_of_case** | 72 | Regex for division headers | Always one of: `EN BANC` (31), `FIRST DIVISION` (12), `SECOND DIVISION` (28), `THIRD DIVISION` (0 in Vol 226, present in later volumes). One OCR variant: `FIRST DIVISLON`. Appears on own line preceding a case bracket. Vol 226 has exactly 72 occurrences in the text at positions matching the ground truth. |
| **division** | 73 | Co-located with `start_of_case` | Same text as `start_of_case` in almost all cases. Shares character offsets with start_of_case (identical spans). The one discrepancy — "May 27, 1986" coded as division — appears to be a ground-truth annotation oddity. |
| **start_decision** | 72 | First non-blank line after ponente line | After `PONENTE, J.:` line, the next non-blank line is start_decision. Average 58 chars. Always the first sentence of the opinion body. |
| **end_decision** | 72 | Regex for "SO ORDERED" variants | 67 of 72 are exactly `SO ORDERED.`. Variants: `SO ORDERED,` (1), `SOORDERED.` (1), `as to costs. It is so ordered.` (1), `petitioner is ACQUITTED. No costs.` (1), `Cabrera. This decision is immediately executory.` (1). The 5 variants require fuzzy matching or per-case fallback. |
| **case_number** | 74 | Regex for G.R./A.M. bracket patterns | Format: `[G.R. No. NNNNN. Date]` on the line immediately after a division header. OCR variants: `(G.R.` (parenthesis for `[`), `{G.R.` (curly brace for `[`), `G.R. No,` (comma for period, 5 instances). Also `Adm. Matter`, `Adm. Case`, `A.M. No.` patterns. All 74 case numbers are extractable with a tolerant regex. Consolidated cases have a second bracket line 1-2 lines below the first. |
| **date** | 73 | Co-extracted with case_number from bracket | Always inside the same bracket as the case number: `[G.R. No. NNNNN. <date>]`. Format is `Month DD, YYYY` with OCR variants like `May 30. 1986` (period for comma) and `[986` for `1986`. |

### Tier 3 — Medium (pattern-based with boundary ambiguity)

| Label | Count | Approach | Justification |
|-------|-------|----------|---------------|
| **ponente** | 70 | Regex for `SURNAME, J.:` pattern | Appears on its own line as `SURNAME, J.:` or `SURNAME, JR., J.:`. 12 unique ponente names in Vol 226 (GUTIERREZ JR. appears 16 times). 3 cases are `PER CURIAM:` (or `PER CURIAM,;:` with OCR noise). 2 cases have no ponente at all. The ponente line always appears immediately after the `DECISION`/`RESOLUTION` line. **Medium** because: (a) OCR can corrupt the surname, (b) PER CURIAM is a special case, (c) must distinguish from separate opinion author lines (e.g., `TEEHANKEE, C.J., concurring:`). |
| **counsel** | 38 | Regex for `APPEARANCES OF COUNSEL` header | Present in only 53% of annotated cases (38/72), but the header is reliable — 38 exact matches in the volume text. The span includes the header itself plus subsequent lines listing counsel names through to the next section. Boundary detection (where counsel ends) is the hard part: it ends at the blank line before `DECISION`/`RESOLUTION`. In cases without this section, the field is simply absent. |
| **end_syllabus** | 72 | Heuristic: last line before `APPEARANCES OF COUNSEL` or `DECISION`/`RESOLUTION` | This is the last substantive line of the syllabus section. No keyword marker — must be inferred from the boundary between syllabus and the next section (counsel or decision). Content is variable (e.g., "under the old law.", "majority rule.", etc.). Requires state-machine logic: scan forward from `start_syllabus` until hitting the next structural marker, then take the previous non-blank line. |
| **start_opinion** | 6 | Regex for `SURNAME, C.J., concurring/dissenting:` | Only 6 instances, all by Justice Teehankee in Vol 226. OCR variant: `TEEWMHANKEE`. Format: `SURNAME, C.J., (concurring\|dissenting\|separate opinion):`. Must not confuse with ponente line (which has just `J.:` not `concurring:`). |
| **end_opinion** | 6 | Heuristic: last line before next case or end of volume | Similar to `end_of_case` — the last line of the separate opinion body. In case 73, this is the last line on the final page, cut off mid-sentence. Requires knowing the next case boundary or volume end. |

### Tier 4 — Hard (variable structure, multi-line, OCR-sensitive)

| Label | Count | Approach | Justification |
|-------|-------|----------|---------------|
| **parties** | 74 | Regex + heuristic for boundaries | Multi-line span (avg 5 lines, up to 46 lines). Starts on the line after the case bracket, ends at the blank line before `SYLLABUS`. Content: `PARTY_NAME, role, vs. PARTY_NAME, role.` BUT: OCR-corrupted names, line-wrapping mid-word (e.g., `SANDIGAN-\nBAYAN`), consolidated cases with two separate party blocks, and roles can be complex (`plaintiff and appellee-appellant`). The start position is deterministic (after bracket) but the end is ambiguous when party text is long or the `vs.` delimiter is OCR-damaged. |
| **votes** | 72 | Regex + heuristic | Multi-line span (avg 1.5 lines, up to 9 lines). Always immediately follows `SO ORDERED.` but format is highly variable: simple concurrence (`JJ., concur.`), with dissent (`J., dissenting.`), with qualification (`J., in the result.`), with separate opinion note (`files a separate opinion...`). 57 unique vote formulations in 72 cases. The span boundary is particularly tricky: votes may flow into separate opinion announcements, then the actual separate opinion text. Must distinguish between votes-proper and the start of a separate opinion. |
| **end_of_case** | 72 | Derived from other labels | The last line of the entire case entry. Usually equals the last line of `votes` (when no separate opinion) or `end_opinion` (when separate opinion exists). This is a derived/computed label — once votes and optional opinions are located, end_of_case is the max of those endpoints. But it must handle: (a) cases cut off at page boundaries, (b) cases where the last line is mid-sentence (case 73: cut at "does not look with"). |

### Tier 5 — Very Hard (would benefit from LLM or major heuristic engineering)

None of the 16 labels are truly "very hard" in isolation for Volume 226, but the **combination** of parties + votes + end_of_case boundary detection across OCR-damaged text from 4 decades of format evolution makes the overall system very hard. The real difficulty is generalization: patterns that work for 1986 formatting will need substantial adaptation for 2024 formatting where `SYLLABUS` sections don't exist and `DECISION` is spaced as `D E C I S I O N`.

### Recommended Phasing

| Phase | Labels | Rationale |
|-------|--------|-----------|
| **Phase 1** | start_of_case, case_number, date, division, doc_type, start_syllabus | Fixed anchors — establishes case boundaries and metadata. These alone give you a working case-boundary detector. |
| **Phase 2** | ponente, counsel, end_syllabus, start_decision, end_decision | Structural sections between known anchors. Each has a reliable start marker. |
| **Phase 3** | parties, votes, end_of_case | Variable-boundary labels. Require accurate Phase 1+2 anchors to constrain search space. |
| **Phase 4** | start_opinion, end_opinion | Rare labels (6/72 cases). Lower priority, only relevant when separate opinions exist. |

---

## 2. Methodology Comparison

### 2a. Rule-based / Regex

**Strengths:**
- Near-perfect for Tier 1–2 labels (start_of_case, case_number, date, division, doc_type, start_syllabus, start_decision, end_decision)
- Zero cost, instant execution
- Deterministic and debuggable
- Already partially implemented in `improved_regex.py`

**Weaknesses:**
- Brittle against OCR variants (need explicit enumeration of every bracket-swap, comma-for-period, etc.)
- Parties boundary detection requires complex multi-line state tracking
- Votes parsing has 57+ format variations just in one volume
- No graceful degradation — a missed pattern is a miss, not a near-miss
- Must be updated as format evolves across eras

**Accuracy estimate (Vol 226):**

| Label | Expected F1 |
|-------|-------------|
| start_of_case | 0.99 |
| case_number | 0.97 |
| date | 0.97 |
| division | 0.99 |
| doc_type | 0.99 |
| start_syllabus | 0.99 |
| ponente | 0.95 |
| counsel | 0.95 |
| end_syllabus | 0.90 |
| start_decision | 0.95 |
| end_decision | 0.93 |
| parties | 0.85 |
| votes | 0.80 |
| start_opinion | 0.95 |
| end_opinion | 0.85 |
| end_of_case | 0.85 |

**Cost:** $0
**Speed:** ~1 second per volume
**Generalizability:** Moderate — each new era may need new patterns

### 2b. LLM-based (DeepSeek API, full extraction)

**Approach:** Send entire volume text (or chunked) to DeepSeek V3, prompt it to extract all 16 labels per case.

**Chunk strategy:**
- Volume 226 is ~375K tokens — far too large for a single API call (DeepSeek context limit: 64K tokens for V3, 128K for V3-0324)
- Must chunk by case. Average case is ~4,700 tokens. With system prompt (~500 tokens) + output (~500 tokens), each call is ~5,700 tokens.
- BUT: we need case boundaries first to chunk by case — circular dependency. Solution: use regex for case-boundary detection (Phase 1 labels), then LLM for field extraction within each case.

**Prompt design:**
- System prompt: JSON schema of expected output, 2-3 few-shot examples from ground truth
- User prompt: raw text of one case (from start_of_case to estimated end_of_case)
- Output: structured JSON with all labels, offsets, and text

**Accuracy estimate:** 0.90–0.98 across all labels (LLMs excel at boundary detection in natural text), but accuracy degrades with OCR noise.

**Cost projection:** See [Section 5](#5-cost-model). TL;DR: **$74–$105 for full extraction of all 735 volumes** — far exceeds the $5 budget.

**Speed:** ~2–4 minutes per volume (rate-limited by API throughput)

**Generalizability:** High — LLMs handle format evolution naturally.

### 2c. Hybrid (regex for easy labels, LLM for hard labels)

**Recommended approach.** The budget math is decisive: regex costs $0, and the $5 budget allows LLM calls for only ~13M input tokens total. Here's how to allocate them:

**Regex handles (Phases 1–2):**
- start_of_case, case_number, date, division, doc_type, start_syllabus, start_decision, end_decision, ponente, counsel, end_syllabus
- These 11 labels have fixed markers or are derivable from adjacent anchors
- Cost: $0

**LLM handles (Phase 3 hard cases only, triggered by low confidence):**
- parties (when multi-line, consolidated, or OCR-damaged)
- votes (when format is complex)
- end_of_case (when boundary is ambiguous)
- start_opinion / end_opinion (rare — only when detected)

**How the hybrid works:**
1. Regex runs first, extracting all Phase 1–2 labels and attempting Phase 3
2. A confidence scorer flags cases where regex output is uncertain (e.g., parties span seems too short/long, votes doesn't match known patterns, ponente not found)
3. Only flagged cases are sent to DeepSeek — estimated at 15–25% of cases
4. LLM receives: (a) the raw text of the specific case, (b) the already-extracted Phase 1–2 labels as context, (c) a prompt asking only for the uncertain labels

**Cost projection for hybrid:** See [Section 5](#5-cost-model). TL;DR: **$1.50–$4.80 depending on fallback rate** — fits within $5.

**Accuracy estimate:** 0.93–0.98 across all labels (regex accuracy for easy labels + LLM accuracy for hard labels).

### 2d. Other Approaches Considered

**Heuristic state machine (recommended as the regex implementation strategy):**
A finite-state machine that processes each volume line-by-line, transitioning between states: `SEEKING_CASE → IN_HEADER → IN_PARTIES → IN_SYLLABUS → IN_COUNSEL → IN_DECISION_BODY → IN_VOTES → IN_OPINION → SEEKING_CASE`. Each state has entry/exit rules based on line content. This is how the regex approach should be structured internally — not as independent pattern matches, but as a stateful parser.

Advantages over raw regex: naturally handles ordering constraints (e.g., ponente must come after doc_type), prevents false positives from body text matching header patterns, and makes boundary detection sequential.

**NLP/NER (spaCy):**
Not recommended as primary approach. The extraction task is structural (section boundaries in a formatted document), not entity recognition in free text. NER would require training data in a different format than what the annotation GUI produces, and wouldn't help with the core challenge (boundary detection between sections).

However, spaCy's `Matcher` or `PhraseMatcher` could be useful for:
- Normalizing OCR-damaged justice names against a known list
- Extracting party roles (petitioner, respondent, etc.) from party text
- Identifying legal citation patterns within body text

**Template matching:**
Not viable. While cases follow a template, OCR noise and format evolution across 735 volumes make rigid templates too brittle. The state machine approach is a more flexible version of this idea.

### Methodology Decision Matrix

| Criterion | Regex/FSM | Full LLM | Hybrid | NER |
|-----------|-----------|----------|--------|-----|
| Accuracy (Vol 226) | 0.92 | 0.96 | 0.96 | 0.80 |
| Cost (735 vols) | $0 | $105 | $1.50–$4.80 | $0 |
| Speed (per vol) | 1s | 3min | 15s | 5s |
| Generalizability | Medium | High | High | Low |
| Debuggability | High | Low | Medium | Low |
| **Recommendation** | **Primary** | No | **Fallback** | Component |

---

## 3. Pipeline Architecture

### System Diagram

```
                              Volume_NNN.txt
                                    │
                    ┌───────────────┴───────────────┐
                    │       STAGE 1: Preprocess      │
                    │  • Strip page markers           │
                    │  • Strip volume headers          │
                    │  • Strip short-title lines       │
                    │  • Build line→char offset map    │
                    │  • Build page number index       │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │   STAGE 2: Case Boundary FSM   │
                    │  • Detect division headers       │
                    │  • Match case brackets            │
                    │  • Extract case_number + date     │
                    │  • Handle consolidated brackets   │
                    │  • Output: case boundary ranges   │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │  STAGE 3: Section Extraction    │
                    │  Per case (within boundaries):   │
                    │  • Parties (bracket→SYLLABUS)     │
                    │  • SYLLABUS→end_syllabus          │
                    │  • Counsel (if present)           │
                    │  • doc_type + ponente             │
                    │  • Decision body boundaries       │
                    │  • Votes block                    │
                    │  • Separate opinions (if any)     │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │   STAGE 4: Confidence Check    │
                    │  • Score each extraction          │
                    │  • Flag low-confidence cases      │
                    │  • Missing required labels?       │
                    │  • Span length anomalies?         │
                    └──────┬────────────┬───────────┘
                           │            │
                     High conf.    Low conf.
                           │            │
                           │   ┌────────┴────────┐
                           │   │  STAGE 5: LLM   │
                           │   │  Fallback        │
                           │   │  (DeepSeek V3)   │
                           │   │  • Re-extract    │
                           │   │    uncertain     │
                           │   │    labels only   │
                           │   └────────┬────────┘
                           │            │
                    ┌──────┴────────────┴───────────┐
                    │   STAGE 6: OCR Post-Correction │
                    │  • Fix case_number punctuation   │
                    │  • Normalize date formats         │
                    │  • Fix bracket types [](){}       │
                    │  • Normalize justice names         │
                    │  • Flag uncorrectable errors       │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │    STAGE 7: Output Assembly     │
                    │  • Build ground_truth JSON        │
                    │  • Compute char/line/page offsets │
                    │  • Validate schema                │
                    │  • Write per-volume JSON           │
                    └───────────────────────────────┘
```

### Stage Details

**Stage 1 — Preprocessing**

Input: raw `Volume_NNN.txt`
Output: clean text + coordinate maps

The preprocessor must handle:
- **Page markers:** `--- Page NNN ---` (regex: `^--- Page \d+ ---$`). These appear every 40–60 lines. Strip from text but record the line→page mapping.
- **Volume headers:** `VOL. 226, MAY 23, 1986 3` or `VOL, 226, JULY 11, 1986 625` (OCR comma for period). These appear after every page marker as the first line of each new page. Strip but preserve line numbering.
- **Short-title lines:** `Milano vs. Employees' Compensation Commission` — abbreviated case titles that appear as running headers after volume headers. Strip.
- **Coordinate map:** Build `line_starts[]` array (identical to the GUI's `VolumeLoader`) for O(1) conversion between Tkinter line numbers, character offsets, and page numbers. The output JSON must include all three coordinate systems.

The key design question: **strip vs. annotate.** Stripping makes regex simpler but destroys character offsets. The better approach is to **annotate** noise lines (flag them in a parallel boolean array) and have the FSM skip flagged lines, while preserving the original character offsets for JSON output.

**Stage 2 — Case Boundary Detection (FSM)**

The state machine processes lines sequentially:

```
State: BETWEEN_CASES
  On: line matches division header (EN BANC / FIRST|SECOND|THIRD DIVISION)
      → Record start_of_case position
      → Transition to EXPECTING_BRACKET

State: EXPECTING_BRACKET
  On: line matches case bracket pattern [G.R. No. / A.M. No. / Adm. ...]
      → Extract case_number and date from bracket
      → Check next line for second bracket (consolidated case)
      → Transition to IN_PARTIES
  On: 3+ lines without bracket match
      → Likely false positive division header (body text mentioning "EN BANC")
      → Revert to BETWEEN_CASES

State: IN_PARTIES
  On: blank line followed by "SYLLABUS" on next line
      → Record parties span (from bracket end to blank line)
      → Transition to IN_SYLLABUS
  On: blank line followed by DECISION/RESOLUTION (no SYLLABUS — modern volumes)
      → Record parties span
      → Transition to IN_DECISION_HEADER
```

Full state diagram covers all transitions through SYLLABUS → COUNSEL → DECISION_HEADER → DECISION_BODY → VOTES → OPINION → BETWEEN_CASES.

**Case bracket regex** (must handle all observed variants):
```python
BRACKET_PATTERN = re.compile(
    r'[\[\(\{]'                          # Opening bracket: [ or ( or {
    r'\s*'
    r'(?:G\.R\.\s*No[s,.]?\s*'           # G.R. No. / G.R. Nos. / G.R. No,
    r'|A\.M\.\s*No\.\s*'                 # A.M. No.
    r'|Adm\.\s*(?:Matter|Case)\s*No\.\s*' # Adm. Matter No. / Adm. Case No.
    r')'
    r'([\w\-/]+(?:\s*[-&]\s*[\w\-/]+)*)' # Case number(s)
    r'[.,]\s*'
    r'(\w+\s+\d{1,2}[.,]\s*\d{4})'      # Date: Month DD, YYYY
    r'\s*'
    r'[\]\)\}]',                          # Closing bracket: ] or ) or }
    re.IGNORECASE
)
```

**Stage 3 — Section Extraction**

Within each case's boundary (from `start_of_case` to estimated `end_of_case`), extract sections in order:

1. **parties:** Lines from after case bracket(s) to the blank line before SYLLABUS (or before DECISION in modern volumes without SYLLABUS).

2. **start_syllabus / end_syllabus:** SYLLABUS keyword marks start. End is the last non-blank line before APPEARANCES OF COUNSEL or DECISION/RESOLUTION, whichever comes first. Skip interleaved page markers and volume headers when scanning.

3. **counsel:** If APPEARANCES OF COUNSEL exists, span from that header to the blank line before DECISION/RESOLUTION.

4. **doc_type + ponente:** DECISION or RESOLUTION on own line. Next non-blank line should match `SURNAME[, JR.][, J.|, C.J.]:` or `PER CURIAM:`.

5. **start_decision:** First non-blank line after the ponente line.

6. **end_decision:** Scan forward for `SO ORDERED.` (with fuzzy matching for OCR variants). If not found, use the last line before the votes block.

7. **votes:** Lines immediately after end_decision until: (a) a blank line followed by a separate opinion header, (b) the start of the next case's division header, or (c) end of searchable area.

8. **start_opinion / end_opinion:** If a `SURNAME, C.J./J., concurring/dissenting:` line follows votes, mark it as start_opinion. end_opinion is the last line before the next case or volume end.

9. **end_of_case:** The last annotation position in the case — either end of votes (if no opinion) or end of opinion.

**Stage 4 — Confidence Scoring**

Each extracted case gets a confidence score based on:

| Check | Weight | Criteria |
|-------|--------|----------|
| All required labels present | 0.3 | start_of_case, case_number, date, division, doc_type, start_decision, end_decision, votes, end_of_case |
| Parties span reasonable length | 0.1 | 50–2000 chars (ground truth: 50–1508) |
| Votes span reasonable length | 0.1 | 20–500 chars (ground truth: 32–393) |
| Ponente matches known justice name | 0.1 | Lookup against master list |
| Section ordering correct | 0.2 | start_of_case < case_number < parties < syllabus < counsel < doc_type < ponente < start_decision < end_decision < votes |
| No overlapping spans | 0.1 | No label span should overlap another |
| Date parseable | 0.1 | Valid month/day/year |

Cases scoring below 0.7 are flagged for LLM fallback.

**Stage 5 — LLM Fallback (DeepSeek V3)**

Only invoked for low-confidence cases. Sends:
- Raw text of the specific case (bounded by Stage 2)
- Already-extracted high-confidence labels as context
- Prompt requesting only the uncertain labels

See [Section 5](#5-cost-model) for cost analysis.

**Stage 6 — OCR Post-Correction**

A rule-based correction pass applied to extracted text:

| Error Pattern | Correction | Scope |
|---------------|------------|-------|
| `G.R. No,` | `G.R. No.` | case_number |
| `[986` → `1986`, `(986` → `1986` | Digit restoration | date |
| `May 30. 1986` (period-comma) | `May 30, 1986` | date |
| `(G.R.` → `[G.R.` | Bracket normalization | case_number |
| `{G.R.` → `[G.R.` | Bracket normalization | case_number |
| `DIVISLON` → `DIVISION` | Known typo correction | division |
| `SOORDERED.` → `SO ORDERED.` | Space insertion | end_decision |
| `PER CURIAM,;:` → `PER CURIAM:` | Punctuation cleanup | ponente |
| `TEEWMHANKEE` → `TEEHANKEE` | Justice name normalization | ponente, start_opinion |

Justice name normalization uses a master list of all SC justices (1986–2024) and `rapidfuzz` for fuzzy matching (threshold: 85% similarity). This handles OCR damage to surnames while avoiding false corrections.

**Stage 7 — Output Assembly**

Produces one JSON file per volume in the exact `ground_truth` format:
```json
{
  "format_version": 2,
  "volumes": {
    "Volume_226.txt": {
      "volume": "Volume_226.txt",
      "cases": [
        {
          "case_id": "vol226_case_0",
          "annotations": [
            {
              "label": "start_of_case",
              "text": "SECOND DIVISION",
              "group": null,
              "start_char": 13562,
              "end_char": 13577,
              "start_line": 421,
              "end_line": 421,
              "start_page": 18,
              "end_page": 18
            }
          ],
          "status": "auto_extracted",
          "notes": "confidence: 0.95"
        }
      ]
    }
  }
}
```

The `status` field is set to `"auto_extracted"` (not `"in_progress"`) to distinguish machine output from human annotations. The `notes` field carries the confidence score so the GUI can sort/filter by confidence for review.

---

## 4. Evaluation Framework

### Scoring Metrics

For each label, compute **precision**, **recall**, and **F1** using span-overlap matching.

**Span matching strategy:**

Labels fall into two categories based on the ground truth data:

1. **Position labels** (start_of_case, start_syllabus, start_decision, end_decision, start_opinion, end_opinion, end_of_case): Although stored as spans in the JSON, these mark structural positions. Use a **relaxed position match**: predicted span must overlap the ground truth span by at least 1 character.

2. **Content spans** (case_number, date, division, parties, counsel, ponente, doc_type, votes, end_syllabus): Use **IoU (Intersection over Union) threshold of 0.8**. This allows minor boundary differences (e.g., including/excluding trailing punctuation) while requiring substantial overlap.

**Why 0.8 IoU, not exact match:**
- The ground truth shows minor inconsistencies (e.g., end_of_case sometimes includes a trailing period, sometimes doesn't)
- OCR correction may shift boundaries by a few characters
- A threshold below 0.8 would allow partial credit for grossly wrong spans
- A threshold above 0.9 would penalize trivially different boundary choices

**IoU formula:**
```
IoU = len(predicted ∩ ground_truth) / len(predicted ∪ ground_truth)
```
where intersection and union are computed over character offset ranges.

### Special Handling

**Consolidated cases (group matching):**
- Predicted case_number and parties annotations must include a `group` field
- Match predicted groups to ground truth groups by text similarity (fuzzy match on case number text)
- Each group is scored independently — a prediction that finds both consolidated case numbers with correct grouping gets full credit; finding only one gets 50%

**Missing labels:**
- If ground truth has no annotation for a label (e.g., counsel absent in 34 cases), a correct prediction is to NOT produce that label. Producing a false counsel annotation counts as a false positive.
- If ground truth has a label but prediction doesn't, it's a false negative.

**Position-only labels with shared offsets:**
- In the ground truth, `division` and `start_of_case` often share identical character offsets. The scorer must handle this — matching `division` should not double-count as matching `start_of_case`.

### Scoring Script Architecture

```python
# scorer.py — evaluate predictions against ground truth

def score_volume(predicted_json, ground_truth_json, iou_threshold=0.8):
    """Returns per-label precision, recall, F1 and per-case breakdown."""

    results = {}
    for label in ALL_LABELS:
        tp, fp, fn = 0, 0, 0
        for case_id in all_case_ids:
            gt_spans = get_spans(ground_truth, case_id, label)
            pred_spans = get_spans(predicted, case_id, label)
            matched_gt, matched_pred = match_spans(gt_spans, pred_spans, iou_threshold)
            tp += len(matched_gt)
            fp += len(pred_spans) - len(matched_pred)
            fn += len(gt_spans) - len(matched_gt)
        results[label] = compute_f1(tp, fp, fn)

    return results
```

The scorer also outputs:
- **Per-case breakdown:** which cases failed which labels (for debugging)
- **Confusion analysis:** what the prediction said vs. what ground truth says (for error categorization)
- **Aggregate F1:** micro-averaged across all labels (weighted by label frequency)

### Integration with Annotation GUI

The scorer output feeds back into the annotation GUI workflow:

1. Load predicted JSON into the GUI alongside ground truth
2. GUI highlights discrepancies: green = correct match, red = mismatch, yellow = partial overlap
3. Human reviewer can accept predictions (converting `auto_extracted` to `verified`) or correct them
4. Corrected predictions become new ground truth, expanding the training set

The GUI's `file_io.py` already handles the JSON format — no schema changes needed. The `status` field distinguishes human-annotated (`in_progress`) from machine-predicted (`auto_extracted`) from human-verified (`verified`).

---

## 5. Cost Model

### Token Estimation

**Volume 226 measurements:**
- File size: ~1.4 MB
- Character count: ~1,360,000
- Estimated tokens: ~360,000 (at ~3.8 chars/token for OCR English text)
- Cases: 72 annotated
- Average chars per case: 18,644
- Average tokens per case: ~4,900

**Corpus-wide estimates (Volumes 226–961):**

| Metric | Per Volume (avg) | Corpus Total (735 vols) |
|--------|-----------------|------------------------|
| File size | ~1.4 MB | ~1.0 GB |
| Tokens | ~360K | ~265M |
| Cases | ~48 (estimated avg) | ~35,000 |

Note: Vol 226 has 72 cases, but later volumes may have fewer (shorter cases but longer body text). 48 cases/volume is a conservative estimate.

### Approach A: Full LLM Extraction (not viable)

Send every case to DeepSeek V3 for extraction.

| Component | Tokens | Rate | Cost |
|-----------|--------|------|------|
| Input (case text) | 265M | $0.27/M | $71.55 |
| Input (system prompt, ~500 tok × 35K calls) | 17.5M | $0.27/M | $4.73 |
| Output (~500 tok × 35K calls) | 17.5M | $1.10/M | $19.25 |
| **Total** | | | **$95.53** |

**Verdict: 19× over budget.** Not viable as primary approach.

### Approach B: LLM for All Hard Labels (not viable)

Send parties + votes + end_of_case sections for every case.

Estimated tokens per case for hard-label sections:
- Parties context window: ~800 tokens (parties text + surrounding 500 chars)
- Votes context window: ~600 tokens
- System prompt: ~300 tokens
- Output: ~200 tokens
- Total per case: ~1,900 tokens

| Component | Tokens | Rate | Cost |
|-----------|--------|------|------|
| Input (35K cases × 1,700 tok) | 59.5M | $0.27/M | $16.07 |
| Output (35K × 200 tok) | 7.0M | $1.10/M | $7.70 |
| **Total** | | | **$23.77** |

**Verdict: 4.8× over budget.** Still not viable for all cases.

### Approach C: LLM Fallback Only (viable)

Regex handles all labels. LLM is invoked only for cases where the confidence scorer flags uncertainty. Based on Vol 226 analysis:

**Expected fallback rates:**
- Tier 1–2 labels: <2% of cases need LLM help (~1 case per volume)
- parties: ~15% of cases (consolidated cases, OCR-damaged party blocks, very long party lists)
- votes: ~10% of cases (complex multi-line votes with dissent/concurrence notes)
- Overall: ~20% of cases across the corpus

| Scenario | Fallback Rate | LLM Calls | Input Tokens | Output Tokens | Cost |
|----------|--------------|-----------|--------------|---------------|------|
| Optimistic | 10% | 3,500 | 5.95M | 0.7M | **$2.38** |
| Expected | 20% | 7,000 | 11.9M | 1.4M | **$4.75** |
| Pessimistic | 30% | 10,500 | 17.85M | 2.1M | **$7.13** |

**Verdict: Expected case fits within $5.** The pessimistic case slightly exceeds it.

### Budget Optimization Strategies

If the 20% fallback rate pushes costs above $5:

1. **Tighten confidence thresholds:** Reduce LLM calls by accepting slightly lower accuracy on borderline cases. The human review step in the GUI catches remaining errors.

2. **Batch multiple cases per API call:** Send 3–5 short cases in a single prompt to amortize the system prompt cost. DeepSeek V3's 64K context allows ~10 cases per call.

3. **Cache common patterns:** If the same justice name list or party format appears repeatedly, skip LLM for subsequent occurrences that match an already-verified pattern.

4. **Prioritize later volumes:** Modern volumes (post-2010) have cleaner formatting and may need fewer LLM fallbacks. Process them with regex-only first, using LLM budget for the noisier early volumes.

### DeepSeek Pricing Verification

The cost model uses DeepSeek V3 (deepseek-chat) pricing as of early 2026:
- Input: $0.27 per 1M tokens (cache miss) / $0.07 per 1M (cache hit)
- Output: $1.10 per 1M tokens

If using DeepSeek's **prompt caching** (available for repeated system prompts), the input cost drops significantly for repeated calls with the same system prompt:
- Cached system prompt: $0.07/M instead of $0.27/M
- With caching, the "Expected" scenario drops from $4.75 to ~$3.60

---

## 6. Task Breakdown

### T1: Preprocessing Module

**Implements:** Stage 1 (Preprocessing)
**Dependencies:** None
**Estimated effort:** Small

**Deliverables:**
- `detection/preprocess.py` — functions: `load_volume()`, `build_coordinate_maps()`, `classify_noise_lines()`
- Reuse coordinate math from `gui/volume_loader.py` (VolumeLoader already computes `line_starts[]` and `page_breaks[]`)
- Unit tests against Volume 226: verify line count, page count, char offsets match ground truth values

**Acceptance criteria:**
- `line_starts[421]` maps to `start_char=13562` (first case in ground truth)
- `page_breaks` correctly maps line 421 → page 18
- Noise line classifier correctly identifies all `--- Page NNN ---` lines, all `VOL. 226, ...` headers, and all short-title lines

### T2: Case Boundary Detector (FSM)

**Implements:** Stage 2 (Case Boundary FSM)
**Dependencies:** T1
**Estimated effort:** Medium

**Deliverables:**
- `detection/boundary_fsm.py` — class `CaseBoundaryDetector` with states, transitions, bracket regex
- Handles all bracket variants: `[`, `(`, `{` openers; `G.R. No.`, `G.R. No,`, `A.M. No.`, `Adm. Matter No.`, `Adm. Case No.`
- Consolidated case detection (second bracket within 3 lines of first)
- Outputs list of `CaseBoundary(start_line, end_line_estimate, case_numbers, date, division)`

**Acceptance criteria against Vol 226 ground truth:**
- Detects all 72 case start positions (100% recall for start_of_case)
- Correctly identifies both consolidated cases (vol226_case_45 and vol226_case_47)
- Extracts all 74 case numbers with correct text (allowing OCR as-is)
- Extracts all 73 dates

### T3: Section Extractor

**Implements:** Stage 3 (Section Extraction)
**Dependencies:** T2
**Estimated effort:** Medium-Large

**Deliverables:**
- `detection/section_extractor.py` — class `SectionExtractor` that processes each case boundary
- Extracts all 16 labels using the FSM approach within each case
- Special handling for: missing SYLLABUS (modern volumes), missing counsel, PER CURIAM cases, separate opinions

**Acceptance criteria against Vol 226 ground truth (per-label F1 at IoU ≥ 0.8):**
- start_of_case: ≥ 0.98
- case_number: ≥ 0.95
- date: ≥ 0.95
- division: ≥ 0.97
- doc_type: ≥ 0.97
- start_syllabus: ≥ 0.98
- end_syllabus: ≥ 0.88
- counsel: ≥ 0.90
- ponente: ≥ 0.93
- start_decision: ≥ 0.93
- end_decision: ≥ 0.90
- parties: ≥ 0.82
- votes: ≥ 0.78
- start_opinion: ≥ 0.90
- end_opinion: ≥ 0.82
- end_of_case: ≥ 0.82

### T4: Scoring Script

**Implements:** Evaluation Framework (Section 4)
**Dependencies:** T1 (for coordinate maps)
**Estimated effort:** Small-Medium

**Deliverables:**
- `detection/scorer.py` — functions: `score_volume()`, `score_label()`, `match_spans()`
- IoU-based span matching with configurable threshold (default 0.8)
- Group-aware matching for consolidated cases
- Output: per-label P/R/F1, per-case breakdown, aggregate micro-F1
- CLI: `python -m detection.scorer --predicted pred.json --ground-truth gt.json`
- Optional: output diff report loadable in annotation GUI

**Acceptance criteria:**
- Correctly scores a perfect prediction (all F1 = 1.0)
- Correctly handles missing labels (absent counsel → true negative, not false negative)
- Correctly handles consolidated cases (group matching)
- Produces valid JSON report

### T5: Confidence Scorer + LLM Fallback

**Implements:** Stages 4–5 (Confidence Check + LLM Fallback)
**Dependencies:** T3, T4
**Estimated effort:** Medium

**Deliverables:**
- `detection/confidence.py` — class `ConfidenceScorer` with weighted rule checks
- `detection/llm_fallback.py` — DeepSeek V3 integration with:
  - Prompt templates for parties, votes, and boundary re-extraction
  - Token counting for budget tracking
  - Retry logic with exponential backoff
  - Response parsing into ground_truth JSON format
- Budget tracker that halts LLM calls when approaching $5 limit

**Acceptance criteria:**
- On Vol 226: confidence scorer correctly flags ≥ 80% of cases that the regex extractor got wrong (i.e., cases where regex F1 < 0.8 for any label)
- LLM fallback improves F1 by ≥ 0.05 on flagged cases
- Total cost for Vol 226 LLM calls < $0.01 (only a few cases should trigger)

### T6: OCR Post-Correction

**Implements:** Stage 6 (OCR Post-Correction)
**Dependencies:** T3
**Estimated effort:** Small-Medium

**Deliverables:**
- `detection/ocr_correction.py` — functions for each correction type
- Justice name normalizer using `rapidfuzz` against a master justice list
- Date normalizer (parse into standard format, fix OCR digit errors)
- Case number normalizer (fix punctuation, bracket types)
- All corrections are logged (original → corrected) for audit

**Dependencies (Python packages):**
- `rapidfuzz` — fuzzy string matching for justice name normalization (MIT license, no heavy deps)
- `python-dateutil` — robust date parsing for OCR-damaged dates (already widely used)

**Acceptance criteria:**
- Corrects all 5 `G.R. No,` → `G.R. No.` instances in Vol 226
- Corrects `DIVISLON` → `DIVISION`
- Corrects `SOORDERED.` → `SO ORDERED.`
- Normalizes `TEEWMHANKEE` → `TEEHANKEE`
- Does NOT over-correct: leaves legitimate variations intact (e.g., `GUTIERREZ, JR.` vs `GUTIERREZ, JR` — both are correct, don't "fix" the missing period)

### T7: Output Assembly + End-to-End Pipeline

**Implements:** Stage 7 + pipeline orchestration
**Dependencies:** T1–T6
**Estimated effort:** Small-Medium

**Deliverables:**
- `detection/pipeline.py` — orchestrates all stages, processes one or many volumes
- `detection/__main__.py` — CLI entry point: `python -m detection Volume_226.txt`
- Output JSON in ground_truth format, one file per volume
- Summary statistics per volume (cases found, confidence distribution, LLM calls made, cost)
- Batch mode: `python -m detection --batch downloads/` processes all volumes

**Acceptance criteria:**
- End-to-end on Vol 226 produces valid JSON loadable in annotation GUI
- Aggregate micro-F1 ≥ 0.92 against the 72-case ground truth
- Processing time < 10 seconds per volume (regex-only)
- LLM-fallback volumes complete in < 60 seconds each

### T8: Cross-Era Validation

**Implements:** Iteration strategy for Volumes 251–960
**Dependencies:** T7
**Estimated effort:** Medium (annotation effort, not code)

**Deliverables:**
- Run pipeline on all 6 sample volumes (251, 421, 676, 813, 960) plus Vol 226
- Manual review of predictions in annotation GUI for each volume
- Document format differences and pipeline failures per era
- Update regex patterns and FSM transitions as needed
- Create ground truth annotations for at least 10 cases per sample volume

**Acceptance criteria:**
- Pipeline produces parseable output for all 6 sample volumes (no crashes)
- Aggregate F1 ≥ 0.85 on newly annotated ground truth across all eras
- Known format differences (spaced DECISION, missing SYLLABUS, Unicode issues) are handled

### Task Dependency Graph

```
T1 ─────┬──── T2 ──── T3 ──── T5 ──── T7 ──── T8
        │                │              │
        └──── T4 ────────┘     T6 ──────┘
```

T1 and T4 can be developed in parallel (T4 only needs the JSON schema, not the coordinate maps). T6 is independent of T5 and can be developed in parallel. T7 integrates all prior work. T8 is the validation/iteration phase.

### Estimated Total Effort

| Task | Effort |
|------|--------|
| T1: Preprocessing | 2–3 hours |
| T2: Boundary FSM | 4–6 hours |
| T3: Section Extractor | 6–10 hours |
| T4: Scoring Script | 3–4 hours |
| T5: Confidence + LLM | 4–6 hours |
| T6: OCR Correction | 3–4 hours |
| T7: Pipeline Assembly | 2–3 hours |
| T8: Cross-Era Validation | 8–12 hours (mostly annotation) |

---

## 7. Iteration Strategy

### Volume Selection for Annotation

The corpus spans Volumes 226–961 (1986–2024). Format evolution is not gradual — it happens in discrete transitions. The goal is to annotate volumes at each transition point.

**Recommended annotation sequence:**

| Priority | Volume | Era | Why |
|----------|--------|-----|-----|
| 1 (done) | **226** | 1986 | Baseline. 72 cases annotated. |
| 2 | **251** | 1989 | Already available as sample. Tests early-era stability. Volume 226 patterns should hold. If they don't, the very first era expansion is broken. |
| 3 | **421** | 2001 | Already available. Introduces A.M. case numbers, possible "SYNOPSIS" transition, moderate OCR quality improvement. Tests mid-era format. |
| 4 | **500** | ~2005 | Approximate transition point where formatting may shift. Needs exploratory read to confirm. |
| 5 | **676** | 2011 | Already available. Introduces spaced `D E C I S I O N` header. Tests the single biggest formatting change. |
| 6 | **813** | 2016 | Already available. High OCR quality era. Tests near-modern formatting. |
| 7 | **900** | ~2022 | Near the SYLLABUS→no-SYLLABUS transition. Needs exploratory read. |
| 8 | **960** | 2024 | Already available. Tests native digital format with Unicode issues and completely different structure (no SYLLABUS, no APPEARANCES OF COUNSEL, inline footnotes). |

For each volume, annotate 10–15 cases (covering: simple cases, consolidated cases, cases with separate opinions, cases without counsel, PER CURIAM cases if present). Total annotation effort: ~80–120 cases across 7 additional volumes.

### Detecting Pipeline Failure on New Eras

The pipeline must self-report when it's struggling. Signals:

1. **Low average confidence:** If a volume's mean confidence drops below 0.75, the era likely has unfamiliar formatting. Alert the user.

2. **Missing required labels:** If >10% of cases in a volume are missing `case_number`, `date`, or `doc_type`, the bracket regex is failing. Log which bracket patterns were attempted.

3. **Abnormal case count:** If the detected case count differs from the TOC count by >10%, the case boundary detector is miscounting. (The TOC is available in each volume's first pages.)

4. **Span length outliers:** If parties or votes spans are >3σ from the known mean, something is likely wrong with boundary detection.

5. **Novel patterns:** Log any lines that partially match structural patterns but don't fully match (e.g., a line containing "G.R." but not matching the bracket regex). These are candidate patterns for the next regex update.

### Updating the Pipeline Without Breaking Coverage

**Strategy: era-tagged pattern sets.**

Rather than one monolithic regex per label, maintain a versioned pattern registry:

```python
BRACKET_PATTERNS = {
    'v226_v500': re.compile(r'...'),  # 1986–2005 era
    'v500_v700': re.compile(r'...'),  # 2005–2012 era
    'v700_v900': re.compile(r'...'),  # 2012–2022 era
    'v900_v961': re.compile(r'...'),  # 2022–2024 era
}

DOC_TYPE_PATTERNS = {
    'v226_v650': re.compile(r'^(DECISION|RESOLUTION)$'),
    'v650_v961': re.compile(r'^(D\s*E\s*C\s*I\s*S\s*I\s*O\s*N|R\s*E\s*S\s*O\s*L\s*U\s*T\s*I\s*O\s*N|DECISION|RESOLUTION)$'),
}
```

Each volume is assigned an era based on its volume number. The pipeline selects the appropriate pattern set. If a pattern fails, it falls through to the next era's patterns before flagging for LLM fallback.

**Regression testing:** After every pattern update, re-run the scorer against ALL annotated volumes (226, 251, 421, etc.). The acceptance criterion is: F1 must not decrease on any previously-passing volume. This is a simple CI check:

```bash
python -m detection.scorer --batch annotated_volumes/ --min-f1 0.90
```

### Scaling to Full Corpus

**Phase 1 (Volumes 226–260):** Process the earliest 35 volumes. These are all 1986–1989 era and should use the same patterns as Vol 226. Spot-check 5 volumes manually in the GUI.

**Phase 2 (Volumes 261–500):** Process the next ~240 volumes. Annotate Vol 421 ground truth first. Spot-check 10 volumes.

**Phase 3 (Volumes 501–700):** Process ~200 volumes. Annotate Vol 676 ground truth. Expect the `D E C I S I O N` transition to trigger LLM fallbacks until patterns are updated.

**Phase 4 (Volumes 701–900):** Process ~200 volumes. Annotate Vol 813 ground truth.

**Phase 5 (Volumes 901–961):** Process the final ~61 volumes. Annotate Vol 960 ground truth. This era requires the most adaptation (no SYLLABUS, no APPEARANCES, Unicode issues).

**LLM budget allocation per phase:**

| Phase | Volumes | Expected Fallback Rate | Estimated Cost |
|-------|---------|----------------------|----------------|
| 1 | 226–260 | 10% (familiar era) | $0.15 |
| 2 | 261–500 | 15% | $1.05 |
| 3 | 501–700 | 25% (format transition) | $1.45 |
| 4 | 701–900 | 15% | $0.90 |
| 5 | 901–961 | 30% (new format) | $0.55 |
| **Total** | | | **$4.10** |

This leaves ~$0.90 buffer for retries and unexpected fallbacks.

---

## Appendix A: Dependencies

| Package | Purpose | License |
|---------|---------|---------|
| `rapidfuzz` | Fuzzy string matching for justice name normalization, party matching | MIT |
| `python-dateutil` | Robust date parsing for OCR-damaged dates | Apache 2.0 |
| `openai` (or `httpx`) | DeepSeek API client (OpenAI-compatible API) | MIT |
| `tiktoken` | Token counting for budget tracking | MIT |

No heavy ML dependencies (no spaCy, no torch). The pipeline is deliberately lightweight.

## Appendix B: Key Observations from Volume 226 Data

### Case bracket format variants observed

```
[G.R. No. 50545. May 23, 1986]     — standard
[G.R. No, 56191. May 27, 1986]     — comma for period (5×)
(G.R. No. 64548. July 7, 1986]     — parenthesis opener
{G.R. No. 69208. May 28, 1986]     — curly brace opener
[G.R. No. 63409. May 30, [986]     — [986 for 1986
[Adm. Case No. 2756. June 5, 1986] — Adm. Case
{Adm. Matter Nos. R-278-RTJ & R-309-RTJ]. May 30, 1986] — complex
[Adm. Matter No. 84-3-886-0. July 7, 1986] — Adm. Matter
[G.R. No. 63559, May 30, 1986]     — comma before date (not period)
(G.R. No. 64559, July 7, 1986)     — parentheses both sides
```

### Division header counts in Volume 226

```
EN BANC          — 31 cases
SECOND DIVISION  — 28 cases
FIRST DIVISION   — 12 cases
FIRST DIVISLON   — 1 case (OCR error)
```

### Cases without APPEARANCES OF COUNSEL: 34 out of 72

In these cases, the transition is directly: end_syllabus → DECISION/RESOLUTION → ponente.

### SO ORDERED variants

```
SO ORDERED.           — 67 cases (93%)
SO ORDERED,           — 1 (comma for period)
SOORDERED.            — 1 (missing space)
"It is so ordered."   — 1 (lowercase, embedded in sentence)
Other closing phrases — 2 (no "SO ORDERED" at all)
```

### Vote block structure patterns

```
Simple:     "Feria (Chairman), Fernan, Alampay, and Paras, JJ., concur."
With note:  "Teehankee, C.J., and Cruz, J., in the result."
Multi-line: "Abad Santos, Feria, Yap, Fernan, Narvasa, Gutierrez, Jr.,\nCruz, and Paras, JJ., concur."
With sep.:  "Teehankee, C.J., files a separate opinion..."
Complex:    Multiple lines with dissent, concurrence, and qualification
```
