# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
