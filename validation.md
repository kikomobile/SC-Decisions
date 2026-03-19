# Validation Playbook

How to validate the CSV extraction pipeline after code changes to the detection pipeline or CSV extractor.

---

## Part 1: CSV Extraction Validation

### Overview

After changing any detection code (`regex_improve/detection/`) or the CSV extractor (`extract_predictions_csv.py`), re-extract the CSV and compare against a baseline to measure improvement/regression.

### Prerequisites

- A **baseline CSV** (e.g., `predictions_extract.csv`) generated before the code change
- Reprocessed prediction JSONs in `downloads/predictions/` for affected volumes

### Step-by-step Process

#### 1. Reprocess affected volumes

```bash
cd regex_improve
# Single volume
python -B -m detection ../downloads/Volume_266.txt --skip-llm --force

# Batch (e.g., ERA-2 range)
python -B -m detection ../downloads --range 261-500 --skip-llm --force

# Full reprocess
python -B -m detection ../downloads --range 226-500 --skip-llm --force
```

`--force` overwrites cached results. `--skip-llm` uses regex-only extraction (faster, deterministic). Batch mode outputs to `downloads/predictions/`. Single-volume mode outputs to `downloads/Volume_NNN.predicted.json` — use `-o downloads/predictions/Volume_NNN_predicted.json` to write to the correct directory for the CSV extractor.

#### 2. Re-extract the CSV

```bash
cd /path/to/SC-Decisions
python -B extract_predictions_csv.py --output predictions_extract_fixed.csv
```

This reads all `*_predicted.json` files from `downloads/predictions/` and flattens them into one row per case. The `--output` flag lets you write to a separate file so you can compare side-by-side without overwriting the baseline.

#### 3. Run headline comparison

```bash
python -B validation/check_headlines.py predictions_extract.csv predictions_extract_fixed.csv
```

**What it computes:** For each CSV, counts:
- `no_case_number`: rows where `case_number` column is empty
- `no_ponente`: rows where `ponente` column is empty
- `no_votes`: rows where `votes_raw` column is empty
- `overflow_1k` / `overflow_5k`: rows where `len(votes_raw) > threshold`

Then shows before/after/delta for each metric plus defect rates as % of total.

**How to interpret:** Delta should be negative (fewer defects) for the metrics your fix targets. Watch for unexpected regressions in other metrics.

#### 4. Check overflow cases

```bash
python -B validation/check_overflow.py predictions_extract_fixed.csv
```

Lists every case with `votes_raw > 1000` chars, sorted by length. Shows per-volume counts. Target: zero overflow cases.

#### 5. Ponente breakdown (if ponente changed)

```bash
python -B validation/check_ponente_breakdown.py predictions_extract.csv predictions_extract_fixed.csv
```

**What it computes:**
1. **Per-case matching**: Builds `{(volume, case_number): ponente}` dicts for both CSVs. Finds cases that *lost* ponente (had it before, missing now) vs *gained* (missing before, have it now).
2. **Per-volume drill-down**: Groups by volume, counts no-ponente per volume in both files, diffs to find which volumes got worse/better.
3. **Root cause via JSON inspection**: For lost cases, loads the `.predicted.json` and checks if the `doc_type` annotation exists. If most lost cases lack `doc_type`, the ponente loss is because ponente extraction is anchored to `doc_type` — no `doc_type` = no ponente search.

**How to interpret:** If lost cases overwhelmingly lack `doc_type`, the regression is from losing LLM-detected ponentes (when reprocessing with `--skip-llm`), not from the regex change itself.

#### 6. Votes by era (if votes changed)

```bash
python -B validation/check_votes_by_era.py predictions_extract.csv predictions_extract_fixed.csv
```

**What it computes:**
1. **Per-case flow**: Cases that gained/lost votes between CSVs.
2. **Per-era breakdown**: Groups cases by volume range (ERA-1=121-260, ERA-2=261-500, etc.), counts missing votes per era in both files.
3. **Lost-votes classification**: Groups lost-votes cases by their old text length:
   - `< 25 chars`: Likely ponente lines misclassified as votes (losing them is correct)
   - `25-99 chars`: Borderline cases
   - `>= 100 chars`: Real votes that were lost (true regressions)

**How to interpret:** Your target era should improve (fewer missing). Other eras should stay flat or improve. Short-text losses (<25 chars) are likely the old extraction being wrong, not a regression.

---

## Part 2: Ground Truth Regression Testing

### Overview

The scorer compares detection pipeline output against hand-annotated ground truth to produce per-label Precision/Recall/F1. Run this after ANY change to the detection pipeline to catch regressions.

### Available ground truth

| Volume | Path | Cases |
|--------|------|-------|
| 226 | `regex_improve/annotation_exports/ground_truth_20260318_150802.json` | 72 |

### Step-by-step Process

#### 1. Run the scorer

```bash
cd regex_improve
python -B -m detection ../downloads/Volume_226.txt \
    --score annotation_exports/ground_truth_20260318_150802.json \
    --skip-llm --force
```

`--force` ensures the pipeline re-extracts (doesn't use cached results). Output includes the full scoring table.

Or use the wrapper script:
```bash
python -B validation/check_ground_truth.py --force
```

#### 2. Read the score table

The output shows:
- **Micro-averaged F1**: Single number summarizing all labels. Baseline: **0.9665**
- **Per-label P/R/F1**: Each of the 16 label types scored individually
- **TP/FP/FN**: True positives, false positives, false negatives per label
- **Problematic cases**: Details on MISSED/EXTRA/low-IoU matches

#### 3. Key labels to watch

| Label | Baseline F1 | What changes affect it |
|-------|------------|----------------------|
| `votes` | 0.8889 | Votes extraction logic, `_is_non_votes_content`, gap trimming |
| `ponente` | 0.9928 | `re_ponente` regex, search window, inline fallback |
| `end_decision` | 0.9931 | `re_so_ordered` regex, WHEREFORE fallback |
| `end_of_case` | 0.8750 | Votes termination, boundary detection |

#### 4. Acceptable vs concerning changes

- **F1 stays same or improves**: Change is safe
- **F1 drops by < 0.01**: Minor, check if the specific cases that regressed are edge cases
- **F1 drops by > 0.02**: Investigate — look at the problematic cases section for MISSED/EXTRA annotations
- **TP count drops**: The pipeline is missing annotations it used to find
- **FP count rises**: The pipeline is generating false annotations

---

## Validation Scripts Reference

All scripts are in `validation/` and accept `--help`. Default CSV paths are `predictions_extract.csv` (baseline) and `predictions_extract_fixed.csv` (latest).

| Script | Purpose | Accepts |
|--------|---------|---------|
| `check_headlines.py` | Before/after headline metrics | Two CSVs |
| `check_overflow.py` | List overflow cases | One CSV |
| `check_ponente_breakdown.py` | Ponente lost/gained analysis | Two CSVs + JSON dir |
| `check_votes_by_era.py` | Votes changes by era | Two CSVs |
| `check_ground_truth.py` | Run scorer against ground truth | Volume + GT file |

---

## Automated Hooks

Two PostToolUse hooks in `.claude/settings.local.json` auto-run after relevant commands:

1. **After CSV extraction** (`extract_predictions_csv.py` in the bash command): Runs `check_headlines.py` + `check_overflow.py` automatically.
2. **After scorer** (`--score` + `detection` in the bash command): Injects a context reminder with baseline scores so Claude can compare.

These hooks fire in Claude Code sessions only. To run checks manually outside Claude Code, use the scripts directly.
