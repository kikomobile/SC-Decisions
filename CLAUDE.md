# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow: Architect + Worker

**Claude Code = Architect.** **Cline (DeepSeek-chat API) = Worker.**

### Claude Code's role (this agent)
- **Plan** features, fixes, and refactors — produce clear, scoped instructions
- **Review** code written by Cline — check correctness, style, edge cases
- **Research** the codebase — find patterns, trace data flow, diagnose bugs
- **Never write code directly** unless it's a trivial one-line fix or the user explicitly asks. Default to producing instructions for Cline instead.

### How to produce Cline instructions
When the user asks for a change, output a clear task description the user can paste into Cline's chat. Format:

```
[Task]: <concise title>
[Files]: <exact file paths to create/modify>
[Context]: <why this change is needed>
[Instructions]:
1. <step-by-step instructions referencing specific files and line numbers>
2. ...
[Constraints]: <what NOT to change, edge cases to handle>
```

Guidelines for instructions:
- Reference exact file paths and line numbers/ranges
- Include the "why" so Cline (DeepSeek) has context for trade-off decisions
- Specify expected behavior and edge cases
- Keep each instruction focused on one logical change — split large tasks into sequential steps
- Write all instructions into TASKS.md

### Review workflow
After Cline applies changes:
1. Read the modified files to verify correctness
2. Flag issues or request follow-up changes as new Cline instructions
3. Confirm completion to the user when satisfied
4. In TASKS.md, write a one-line summary of the task under "Completed Tasks" section and delete the full spec text of the task under "Active Tasks"

## Project Overview

Pipeline to scrape, process (OCR), parse, and store Philippine Supreme Court decisions from the judiciary e-library into a structured SQLite database. Processes 860+ PDF volumes containing 24,000+ cases.

## Pipeline Architecture

```
01_scraper.ipynb    → Downloads PDFs from elibrary.judiciary.gov.ph
02_processor.ipynb  → Extracts text (PyMuPDF) or OCR (Tesseract) from PDFs
03_database.ipynb   → DEPRECATED — replaced by 04
04_parse_cases.ipynb → Parses structured case records into SQLite + JSON exports
```

**Data flow:** Website → `downloads/*.pdf` → `downloads/*.txt` + `processing_manifest.json` → `sc_decisions.db` + `exports/json/*.json` + `exports/stats/parse_stats.csv`

## Environment Setup

Requires external binaries installed separately: **Tesseract OCR** and **Poppler** (for pdf2image).

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and configure paths. All notebooks load config via `python-dotenv`.

Key env vars: `DOWNLOAD_PATH`, `DB_PATH`, `PDF_FOLDER`, `MANIFEST_PATH`, `JSON_EXPORT_PATH`, `STATS_EXPORT_PATH`, `FORCE_REFRESH`.

## Key Design Decisions

- **Notebook 02 OCR** uses batched processing (50 pages/batch via `first_page`/`last_page` in `convert_from_path`), parallel Tesseract via `multiprocessing.Pool` with `cpu_count() - 1` workers, and page-level checkpointing in `processing_manifest.json` for resume after interruption.
- **Notebook 04 is the sole database owner.** It creates 3 tables: `cases`, `volume_toc`, `processing_log`. Uses UPSERT logic for incremental parsing. JSON arrays/objects are stored as TEXT columns in SQLite.
- **Notebook 04 parsing** is regex-heavy with named constant patterns (e.g., `PATTERN_DIVISION`, `PATTERN_GR_BRACKET`, `PATTERN_PONENTE`). These are tuned for the specific formatting of Philippine Supreme Court reports, including handling OCR imperfections.
- **TOC validation** in Notebook 04 compares parsed cases against the "Cases Reported" table of contents using fuzzy matching on G.R. numbers and titles, reporting discrepancies.

## Database Schema (Notebook 04)

- `cases` — Structured case records with JSON fields for `gr_numbers`, `parties`, `counsel`, `justices`, `syllabus`, `separate_opinions`, `footnotes`. Tracks `parse_incomplete` flag and `parse_errors`.
- `volume_toc` — TOC entries per volume with `matched_to_case` linking.
- `processing_log` — Per-volume parse stats (counts, matches, errors).

## Logging & Manifests

| File | Source | Purpose |
|------|--------|---------|
| `download.log` | Notebook 01 | Download activity |
| `processing.log` | Notebook 02 | OCR/extraction progress |
| `processing_manifest.json` | Notebook 02 | Per-file status tracking with page-level checkpoints |
| `parse.log` | Notebook 04 | Case parsing and DB operations |

---

## Annotation GUI Tool (`regex_improve/gui/`)

### Purpose

Tkinter-based GUI for manually annotating Philippine Supreme Court cases in OCR-extracted volume text files. Creates method-agnostic ground truth annotations for evaluating any extraction approach (regex, NLP, LLM). Replaces the CLI `annotate_tool.py`.

### File Structure

```
regex_improve/
├── annotate_gui.py              # Entry point: python annotate_gui.py
├── gui/
│   ├── __init__.py
│   ├── constants.py             # Label defs, colors, keyboard shortcuts, config
│   ├── models.py                # Annotation, Case, VolumeData, AnnotationStore
│   ├── volume_loader.py         # Load .txt, build page/line/char index maps
│   ├── app.py                   # Main Tk window, menu bar, panel layout
│   ├── text_panel.py            # Scrollable Text widget + Canvas line number gutter
│   ├── side_panel.py            # Case navigator, annotation list, label buttons
│   ├── highlight_manager.py     # Tag creation/removal, color coding
│   ├── dialogs.py               # Consolidated case prompts, party linking
│   ├── file_io.py               # Load/save annotations.json, auto-save
│   ├── status_bar.py            # Bottom status bar
│   ├── exporters.py             # BaseExporter + JsonExporter + MarkdownExporter
│   └── evaluation.py            # ExtractionMethod protocol + RegexMethod + runner
├── improved_regex.py            # (existing) Pluggable regex patterns
├── annotate_tool.py             # (existing) CLI tool — being replaced
├── annotations.json             # (existing/shared) Annotation data store
└── samples/                     # (existing) Volume_NNN.txt files
```

### Architecture Decisions

1. **70k-line Text performance**: Load full text via single `text.insert('end', content)`. Use a `Canvas` widget for the line number gutter — redraw only the visible viewport on `<Configure>` and scroll events. Never insert all 80k line numbers at once.

2. **Four coordinate systems** — `VolumeLoader` precomputes conversion structures:
   - **Tkinter index**: `"line.column"` (1-based line, 0-based column)
   - **Character offset**: 0-based from file start — stored in annotations
   - **Line number**: 1-based — displayed in gutter and stored in annotations
   - **Page number**: from `--- Page N ---` markers — stored in annotations
   - `line_starts[]` array enables O(1) Tk↔char conversion; `page_breaks[]` sorted list enables O(log n) line→page lookup via bisect.

3. **Case boundaries**: A case is created by marking "Start of Case." Subsequent field annotations auto-associate with the nearest preceding unclosed case. "End of Case" closes it. Annotations outside any case are rejected with a warning.

4. **Consolidated cases**: A second `case_number` within the same case triggers a prompt: "Add as consolidated case number?" Auto-assigns incrementing `group` index (0, 1, 2...). `parties` annotations in consolidated cases prompt for group assignment. All other labels have `group: null`.

5. **Keyboard shortcuts**: Number keys use `Ctrl+N`, letter keys use `Ctrl+Shift+L` to avoid conflicts with Ctrl+V/X/O/P (paste/cut/open/print).

6. **Visual separators**: Start/End of Case lines get full-width gold background tags. No separator widgets inserted (would break char offsets).

7. **Auto-save**: Atomic write (write temp file → `os.replace()` to target) after every annotation change. Prevents corruption on crash.

8. **Pluggable systems**: Exporters inherit `BaseExporter`. Extraction methods implement `ExtractionMethod` protocol. Both support adding new formats/methods without modifying existing code.

### Naming Conventions

- Classes: `PascalCase` — `AnnotationStore`, `TextPanel`, `VolumeLoader`
- Functions/methods: `snake_case` — `load_volume`, `add_annotation`
- Constants: `UPPER_SNAKE_CASE` — `LABEL_CASE_NUMBER`, `COLOR_SKY_BLUE`
- Private methods: `_underscore_prefix` — `_redraw_line_numbers`, `_on_scroll`
- Tkinter tag names: `"highlight_{label}_{index}"` — e.g., `"highlight_case_number_0"`
- Files: `snake_case.py`

### Data Flow

```
Volume_NNN.txt → VolumeLoader → (text, line_starts[], page_breaks[])
                                        ↓
User actions → HighlightManager → AnnotationStore → annotations.json
                    ↓                    ↓
              TextPanel (tags)    SidePanel (list view)
                                        ↓
                              Exporters → JSON / Markdown
                              Evaluation → RegexMethod → results
```

### Import Rules

- `gui/` modules import freely from `constants.py` and `models.py`
- No circular imports — `app.py` is the composition root that wires components
- `evaluation.py` dynamically imports `improved_regex.py` via `importlib` — never a static import
- Zero external dependencies — stdlib + tkinter only
- Entry point `annotate_gui.py` adds its own directory to `sys.path` for clean imports
