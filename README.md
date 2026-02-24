# SC-Decisions

A Python pipeline to scrape, OCR-process, parse, and store Philippine Supreme Court reports from the judiciary e-library.

## Prerequisites

- Python 3.8+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
- [Poppler](https://poppler.freedesktop.org/) (required by pdf2image)

### Installing Tesseract

**Windows:**
1. Download the installer from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)
2. Run the installer (default path: `C:\Program Files\Tesseract-OCR`)
3. Add Tesseract to your system PATH, or set it in your script:
   ```python
   pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
   ```

**macOS:**
```bash
brew install tesseract
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install tesseract-ocr
```

### Installing Poppler

**Windows:**
1. Download from [poppler-windows releases](https://github.com/oschwartz10612/poppler-windows/releases/)
2. Extract and add the `bin/` folder to your system PATH

**macOS:**
```bash
brew install poppler
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install poppler-utils
```

## Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/SC-Decisions.git
   cd SC-Decisions
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create your environment file:
   ```bash
   cp .env.example .env
   ```

4. Edit `.env` with your preferred paths:
   ```
   DOWNLOAD_PATH=./downloads
   DB_PATH=./sc_decisions.db
   REQUEST_DELAY=2
   ```

## Usage

Run the notebooks in order:

1. **`01_scraper.ipynb`** — Scrapes the e-library and downloads all PDF volumes
2. **`02_processor.ipynb`** — Detects scanned PDFs, extracts text or runs OCR, produces searchable PDFs
3. **`04_parse_cases.ipynb`** — Parses PDFs into structured case records and loads into SQLite

> **Note:** `03_database.ipynb` is deprecated and replaced by `04_parse_cases.ipynb`. The old notebook loaded raw text into a flat `decisions` table. Notebook 04 re-extracts text directly from PDFs, parses each volume into individual structured case records, validates against the volume's TOC, and writes to a new schema.

## Pipeline Overview

```
e-library website
       │
       ▼
┌──────────────────┐
│ 01_scraper       │  → downloads/*.pdf
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ 02_processor     │  → downloads/*_searchable.pdf + processing_manifest.json
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ 04_parse_cases   │  → sc_decisions.db + exports/json/*.json + exports/stats/parse_stats.csv
└──────────────────┘
```

## Database Schema

Notebook 04 creates three tables:

```sql
CREATE TABLE cases (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_filename    TEXT,
    gr_numbers         TEXT,     -- JSON array
    date_of_decision   TEXT,
    division           TEXT,
    ponente_name       TEXT,
    ponente_title      TEXT,
    ponente_role       TEXT,
    parties            TEXT,     -- JSON
    counsel            TEXT,     -- JSON
    justices           TEXT,     -- JSON
    syllabus           TEXT,     -- JSON
    main_decision_text TEXT,
    separate_opinions  TEXT,     -- JSON
    footnotes          TEXT,     -- JSON
    pages              TEXT,     -- JSON array
    parse_incomplete   INTEGER,
    parse_errors       TEXT,     -- JSON array
    date_processed     TEXT
);

CREATE TABLE volume_toc (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_filename    TEXT,
    raw_entry          TEXT,
    case_title         TEXT,
    gr_number          TEXT,
    page_number        TEXT,
    date               TEXT,
    matched_to_case    INTEGER,
    matched_gr_number  TEXT
);

CREATE TABLE processing_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_filename    TEXT,
    toc_found          INTEGER,
    toc_count          INTEGER,
    parsed_count       INTEGER,
    matched_count      INTEGER,
    toc_only           TEXT,     -- JSON array
    parsed_only        TEXT,     -- JSON array
    cases_inserted     INTEGER,
    cases_updated      INTEGER,
    cases_skipped      INTEGER,
    parse_errors       TEXT,     -- JSON array
    processed_at       TEXT,
    force_refresh      INTEGER
);
```
