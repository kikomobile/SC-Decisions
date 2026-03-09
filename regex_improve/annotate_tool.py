#!/usr/bin/env python3
"""
SC Reports — Case Annotation & Regex Testing Tool
===================================================

Three-phase workflow:
  Phase 1: ANNOTATE  — Pre-populate + manually review ~10 representative cases per volume
  Phase 2: IMPROVE   — Export ground truth for Claude to generate improved regex
  Phase 3: TEST      — Run improved regex on remaining (unannotated) cases and score

Usage:
  python annotate_tool.py annotate          # Phase 1 — interactive annotation
  python annotate_tool.py export            # Phase 2 — export ground truth
  python annotate_tool.py test              # Phase 3 — test improved regex
  python annotate_tool.py status            # Show progress dashboard
"""

import os
import re
import sys
import json
import csv
import random
import textwrap
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SAMPLES_DIR     = Path(os.getenv("SAMPLES_DIR", "./samples"))
ANNOTATION_FILE = Path("./annotations.json")
EXPORT_DIR      = Path("./annotation_exports")
IMPROVED_REGEX  = Path("./improved_regex.py")   # user drops improved patterns here
CASES_PER_VOL   = 10  # representative subset size

EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# REGEX PATTERNS (expanded from 04_parse_cases.ipynb)
# ============================================================================

# Running headers (to strip)
RE_HEADER_MODERN = re.compile(
    r'^\s*V[O0]L[.,]?\s*\d+\s*,.*\d{4}\s+\d+\s*$', re.MULTILINE
)
RE_HEADER_OLD = re.compile(
    r'^\s*\d{1,4}\s+PHILIPPINE REPORTS\s*$', re.MULTILINE
)

# Division labels (expanded for SPECIAL divisions)
RE_DIVISION = re.compile(
    r'^\s*((?:SPECIAL\s+)?(?:FIRST|SECOND|THIRD)\s+DIVISION|EN\s+BANC)\s*$',
    re.MULTILINE | re.IGNORECASE
)

# All case-number prefixes
CASE_NUM_PREFIX = (
    r'(?:'
    r'G[.\s]*R[.\s]*\s*(?:Nos?\.?|No\.?)'
    r'|A[.\s]*C[.\s]*\s*(?:Nos?\.?|No\.?)'
    r'|A[.\s]*M[.\s]*\s*(?:Nos?\.?|No\.?)'
    r'|B[.\s]*M[.\s]*\s*(?:Nos?\.?|No\.?)'
    r'|UDK[\s\-]*(?:Nos?\.?|No\.?)'
    r'|OCA[\s\-]*(?:IPI[\s\-]*)?(?:Nos?\.?|No\.?)'
    r'|(?:Nos?\.?|No\.?)'
    r')'
)

# Bracket pattern: [G.R. No. 123456. January 1, 2008]
RE_CASE_BRACKET = re.compile(
    r'[\[\(\{]\s*'
    + CASE_NUM_PREFIX +
    r'\s*(?:[L1Il][\-~])?\s*[\d\-~]+(?:\s*-\s*\d+)?'
    r'(?:\s*(?:,|and|&)\s*' + CASE_NUM_PREFIX + r'?\s*(?:[L1Il][\-~])?\s*[\d\-~]+)*'
    r'\s*[.,;\s]\s*'
    r'[A-Z][a-z]+\s+\d{1,2}\s*,?\s*\d{4}'
    r'\s*\.?\s*[\]\)\}]',
    re.IGNORECASE
)

# Standalone case number
RE_CASE_NUM = re.compile(
    CASE_NUM_PREFIX + r'\s*(?:[L1Il][\-~])?\s*[\d\-~]+(?:\s*-\s*\d+)?',
    re.IGNORECASE
)

# Date
RE_DATE = re.compile(
    r'((?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December)\s+\d{1,2}\s*,?\s*\d{4})',
    re.IGNORECASE
)

# Case start: Division + bracket, OR standalone bracket at line start
RE_CASE_START = re.compile(
    r'((?:SPECIAL\s+)?(?:FIRST|SECOND|THIRD)\s+DIVISION|EN\s+BANC)'
    r'\s*\n(?:.*\n){0,5}?'
    r'\s*[\[\(\{]\s*(?:G[.\s]*R[.\s]*|A[.\s]*C[.\s]*|A[.\s]*M[.\s]*|B[.\s]*M[.\s]*|UDK|OCA)?\s*'
    r'(?:Nos?\.?|No\.?)'
    r'|'
    r'^\s*[\[\(\{]\s*(?:G[.\s]*R[.\s]*|A[.\s]*C[.\s]*|A[.\s]*M[.\s]*|B[.\s]*M[.\s]*|UDK|OCA)?\s*'
    r'(?:Nos?\.?|No\.?)\s*(?:[L1Il][\-~])?\s*[\d]',
    re.IGNORECASE | re.MULTILINE
)

# Sub-field patterns
RE_PONENTE = re.compile(
    r'^\s*([A-Z][A-Z\-\s\']+?)\s*[,\.;]\s*(?:[A-Z.]+\s*,\s*)?(C\.?\s*J\.?|JJ?\.?)\s*[:\.\?]',
    re.MULTILINE
)
RE_DECISION = re.compile(
    r'^\s*D\s*E\s*C\s*I\s*S\s*I\s*O\s*N\s*$|^\s*DECISION\s*$',
    re.MULTILINE | re.IGNORECASE
)
RE_RESOLUTION = re.compile(
    r'^\s*R\s*E\s*S\s*O\s*L\s*U\s*T\s*I\s*O\s*N\s*$|^\s*RESOLUTION(?!.*NO\.)\s*$',
    re.MULTILINE | re.IGNORECASE
)
RE_SO_ORDERED = re.compile(r'SO\s+ORDERED\s*\.', re.IGNORECASE)
RE_SYLLABUS = re.compile(
    r'^\s*S\s*Y\s*L\s*L\s*A\s*B\s*U\s*S\s*$|^\s*SYLLABUS\s*$',
    re.MULTILINE | re.IGNORECASE
)
RE_COUNSEL = re.compile(
    r'^\s*(?:APPEARANCES?\s+OF\s+COUNSEL|COUNSEL)\s*$',
    re.MULTILINE | re.IGNORECASE
)
RE_SEPARATE_OPINION = re.compile(
    r'^\s*(CONCURRING(?:\s+AND\s+DISSENTING)?\s+OPINION|'
    r'DISSENTING\s+OPINION|SEPARATE\s+OPINION|CONCURRING\s+OPINION)\s*$',
    re.MULTILINE | re.IGNORECASE
)


# ============================================================================
# VOLUME LOADING
# ============================================================================

def load_volume(txt_path):
    """Load a volume .txt and return (lines, page_index).
    page_index maps line_number -> page_number.
    """
    raw = Path(txt_path).read_text(encoding="utf-8")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    page_index = {}
    current_page = 0
    page_marker = re.compile(r"^--- Page (\d+) ---$")
    for i, line in enumerate(lines):
        m = page_marker.match(line)
        if m:
            current_page = int(m.group(1))
        page_index[i] = current_page
    return lines, page_index


# ============================================================================
# PRE-POPULATION ENGINE
# ============================================================================

def find_all_boundaries(lines, page_index):
    """Find every case boundary in a volume. Returns list of boundary dicts."""
    combined = "\n".join(lines)
    # char-offset → line-number map
    off2line = {}
    offset = 0
    for i, line in enumerate(lines):
        off2line[offset] = i
        offset += len(line) + 1
    sorted_offsets = sorted(off2line.keys())

    def offset_to_lineno(pos):
        ln = 0
        for off in sorted_offsets:
            if off > pos:
                break
            ln = off2line[off]
        return ln

    boundaries = []
    for m in RE_CASE_START.finditer(combined):
        start_line = offset_to_lineno(m.start())
        div_group = m.group(1) if m.lastindex and m.group(1) else None
        division = re.sub(r"\s+", " ", div_group.strip().upper()) if div_group else None

        lookahead = combined[m.start():m.start() + 4000]
        brackets = list(RE_CASE_BRACKET.finditer(lookahead))
        case_numbers = []
        date_of_decision = None
        bracket_text = ""

        for bm in brackets:
            bt = bm.group(0)
            bracket_text += bt + " "
            for cn in RE_CASE_NUM.finditer(bt):
                normalized = re.sub(r"\s+", " ", cn.group()).strip()
                if normalized not in case_numbers:
                    case_numbers.append(normalized)
            if not date_of_decision:
                dm = RE_DATE.search(bt)
                if dm:
                    date_of_decision = dm.group(1).strip()

        if not case_numbers:
            for cn in RE_CASE_NUM.finditer(lookahead[:500]):
                normalized = re.sub(r"\s+", " ", cn.group()).strip()
                case_numbers.append(normalized)
                break

        boundaries.append({
            "start_line": start_line,
            "start_offset": m.start(),
            "division": division,
            "case_numbers": case_numbers,
            "date_of_decision": date_of_decision,
            "bracket_text": bracket_text.strip(),
        })

    for i, b in enumerate(boundaries):
        b["end_line"] = boundaries[i + 1]["start_line"] - 1 if i + 1 < len(boundaries) else len(lines) - 1

    return boundaries


def extract_subfields(lines, boundary):
    """Extract sub-field data from a case text slice."""
    sl, el = boundary["start_line"], boundary["end_line"]
    case_text = "\n".join(lines[sl:el + 1])
    f = {}

    # Parties: between last bracket close and first section header
    bracket_end = None
    for bm in RE_CASE_BRACKET.finditer(case_text):
        bracket_end = bm.end()
    parties_end = (RE_SYLLABUS.search(case_text) or RE_COUNSEL.search(case_text)
                   or RE_DECISION.search(case_text) or RE_RESOLUTION.search(case_text))
    if bracket_end and parties_end:
        f["parties_raw"] = case_text[bracket_end:parties_end.start()].strip()[:2000]
    elif bracket_end:
        f["parties_raw"] = case_text[bracket_end:bracket_end + 1500].strip()[:2000]
    else:
        f["parties_raw"] = ""

    # Syllabus
    syl_match = RE_SYLLABUS.search(case_text)
    f["has_syllabus"] = bool(syl_match)
    if syl_match:
        syl_end = (RE_COUNSEL.search(case_text[syl_match.end():]) or
                   RE_DECISION.search(case_text[syl_match.end():]) or
                   RE_RESOLUTION.search(case_text[syl_match.end():]))
        chunk = case_text[syl_match.end():syl_match.end() + (syl_end.start() if syl_end else 5000)]
        f["syllabus_raw"] = chunk.strip()[:3000]
    else:
        f["syllabus_raw"] = ""

    # Counsel
    cm = RE_COUNSEL.search(case_text)
    f["has_counsel"] = bool(cm)
    if cm:
        c_end = RE_DECISION.search(case_text[cm.end():]) or RE_RESOLUTION.search(case_text[cm.end():])
        chunk = case_text[cm.end():cm.end() + (c_end.start() if c_end else 2000)]
        f["counsel_raw"] = chunk.strip()[:2000]
    else:
        f["counsel_raw"] = ""

    # Ponente
    dec = RE_DECISION.search(case_text) or RE_RESOLUTION.search(case_text)
    f["ponente_name"] = ""
    f["ponente_title"] = ""
    f["doc_type"] = ""
    if dec:
        f["doc_type"] = "DECISION" if RE_DECISION.search(case_text) else "RESOLUTION"
        after = case_text[dec.end():dec.end() + 500]
        pm = RE_PONENTE.search(after)
        if pm:
            f["ponente_name"] = pm.group(1).strip()
            raw_t = re.sub(r"\s+", "", pm.group(2)).upper()
            f["ponente_title"] = "C.J." if "C" in raw_t else "J."

    f["has_decision"] = bool(RE_DECISION.search(case_text))
    f["has_resolution"] = bool(RE_RESOLUTION.search(case_text))
    f["has_so_ordered"] = bool(RE_SO_ORDERED.search(case_text))

    sep_ops = []
    for sm in RE_SEPARATE_OPINION.finditer(case_text):
        op_type = sm.group(1).strip().upper()
        after_op = case_text[sm.end():sm.end() + 500]
        am = RE_PONENTE.search(after_op)
        sep_ops.append({"type": op_type, "author": am.group(1).strip() if am else ""})
    f["separate_opinions"] = sep_ops

    return f


# ============================================================================
# REPRESENTATIVE SAMPLING
# ============================================================================

def select_representative(boundaries, lines, page_index, n=CASES_PER_VOL):
    """Pick ~n cases covering the variety of types, divisions, and eras.
    Strategy: categorize every case, then sample from each bucket.
    """
    if len(boundaries) <= n:
        return list(range(len(boundaries)))

    buckets = defaultdict(list)  # category -> [index, ...]
    for i, b in enumerate(boundaries):
        # Categorize by case type prefix
        nums_str = " ".join(b.get("case_numbers", []))
        if "A.C." in nums_str or "A. C." in nums_str:
            ctype = "AC"
        elif "A.M." in nums_str or "A. M." in nums_str:
            ctype = "AM"
        elif "B.M." in nums_str or "B. M." in nums_str:
            ctype = "BM"
        elif re.search(r"No\.?\s*L", nums_str, re.IGNORECASE):
            ctype = "NoL"
        else:
            ctype = "GR"

        # Categorize by division
        div = b.get("division") or "NONE"
        if "SPECIAL" in div:
            div = "SPECIAL"
        elif "EN BANC" in div:
            div = "EN_BANC"

        buckets[f"{ctype}_{div}"].append(i)

    # Also check for resolution vs decision and consolidated
    for i, b in enumerate(boundaries):
        case_text = "\n".join(lines[b["start_line"]:min(b["end_line"] + 1, b["start_line"] + 50)])
        if len(b.get("case_numbers", [])) > 1:
            buckets["CONSOLIDATED"].append(i)
        if RE_RESOLUTION.search(case_text) and not RE_DECISION.search(case_text):
            buckets["RESOLUTION_ONLY"].append(i)

    selected = set()

    # Take at least 1 from every bucket
    for cat, indices in buckets.items():
        if indices:
            selected.add(random.choice(indices))

    # Fill remaining slots evenly
    remaining = n - len(selected)
    if remaining > 0:
        all_indices = list(range(len(boundaries)))
        unselected = [i for i in all_indices if i not in selected]
        # Spread evenly across the volume (first, middle, last)
        step = max(1, len(unselected) // remaining)
        for j in range(0, len(unselected), step):
            if len(selected) >= n:
                break
            selected.add(unselected[j])

    return sorted(selected)


# ============================================================================
# INTERACTIVE ANNOTATION (Phase 1)
# ============================================================================

def build_case_annotation(boundary, lines, page_index, case_idx):
    """Build one annotation dict from a boundary + subfield extraction."""
    fields = extract_subfields(lines, boundary)
    return {
        "case_index": case_idx,
        "status": "unreviewed",
        "start_line": boundary["start_line"],
        "end_line": boundary["end_line"],
        "start_page": page_index.get(boundary["start_line"], 0),
        "end_page": page_index.get(boundary["end_line"], 0),
        "case_numbers": boundary["case_numbers"],
        "case_numbers_corrected": None,
        "bracket_text": boundary["bracket_text"],
        "date_of_decision": boundary["date_of_decision"],
        "date_corrected": None,
        "division": boundary["division"],
        "division_corrected": None,
        "parties_raw": fields["parties_raw"],
        "parties_corrected": None,
        "has_syllabus": fields["has_syllabus"],
        "syllabus_raw": fields["syllabus_raw"],
        "syllabus_corrected": None,
        "has_counsel": fields["has_counsel"],
        "counsel_raw": fields["counsel_raw"],
        "counsel_corrected": None,
        "ponente_name": fields["ponente_name"],
        "ponente_name_corrected": None,
        "ponente_title": fields["ponente_title"],
        "doc_type": fields["doc_type"],
        "has_decision": fields["has_decision"],
        "has_resolution": fields["has_resolution"],
        "has_so_ordered": fields["has_so_ordered"],
        "separate_opinions": fields["separate_opinions"],
        "ocr_errors": [],
        "notes": "",
    }


def init_annotations():
    """Load existing or build new annotations for all sample volumes."""
    if ANNOTATION_FILE.exists():
        with open(ANNOTATION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"Loaded existing annotations from {ANNOTATION_FILE}")
        return data

    volume_files = sorted(SAMPLES_DIR.glob("Volume_*.txt"))
    if not volume_files:
        print(f"ERROR: No Volume_*.txt files found in {SAMPLES_DIR.resolve()}")
        sys.exit(1)

    print(f"Found {len(volume_files)} sample volumes. Pre-populating...")
    all_ann = []

    for vf in volume_files:
        print(f"\n  Processing {vf.name}...")
        lines, page_index = load_volume(vf)
        boundaries = find_all_boundaries(lines, page_index)
        print(f"    Total cases detected: {len(boundaries)}")

        selected_indices = select_representative(boundaries, lines, page_index, CASES_PER_VOL)
        print(f"    Selected {len(selected_indices)} representative cases")

        # Show what was selected
        for si in selected_indices:
            b = boundaries[si]
            nums = ", ".join(b["case_numbers"][:3]) or "(none)"
            div = b.get("division") or "(no div)"
            print(f"      [{si:>3}] {div:<25} {nums}")

        cases = []
        for si in selected_indices:
            ann = build_case_annotation(boundaries[si], lines, page_index, si)
            cases.append(ann)

        all_ann.append({
            "volume": vf.name,
            "total_lines": len(lines),
            "total_boundaries": len(boundaries),
            "selected_indices": selected_indices,
            "holdout_indices": [i for i in range(len(boundaries)) if i not in set(selected_indices)],
            "cases": cases,
        })

    save_annotations(all_ann)
    return all_ann


def save_annotations(data):
    with open(ANNOTATION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# CLI annotation interface
# ---------------------------------------------------------------------------

CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RESET   = "\033[0m"

STATUS_COLORS = {
    "unreviewed": DIM,
    "verified":   GREEN,
    "corrected":  YELLOW,
    "flagged":    RED,
}


def show_raw_text(vol_name, start_line, end_line, max_lines=60):
    """Display raw text with line numbers and page markers."""
    vf = SAMPLES_DIR / vol_name
    lines, pi = load_volume(vf)
    display_end = min(end_line + 1, start_line + max_lines)
    print(f"\n{DIM}{'─' * 80}{RESET}")
    for i in range(start_line, display_end):
        if i < len(lines):
            pg = pi.get(i, "?")
            marker = "►" if i == start_line else " "
            print(f"  {marker}{i:>6} {DIM}[p{pg:>3}]{RESET} │ {lines[i]}")
    remaining = end_line - display_end + 1
    if remaining > 0:
        print(f"  {DIM}       ... ({remaining} more lines until line {end_line}) ...{RESET}")
    print(f"{DIM}{'─' * 80}{RESET}")


def display_case(vol_ann, case):
    """Pretty-print one case annotation."""
    c = case
    nums = c.get("case_numbers_corrected") or c.get("case_numbers", [])
    label = ", ".join(nums) if isinstance(nums, list) else str(nums)
    status = c["status"]
    sc = STATUS_COLORS.get(status, "")

    print(f"\n{'═' * 80}")
    print(f" {BOLD}{vol_ann['volume']}{RESET}  │  Case {c['case_index'] + 1} of {vol_ann.get('total_boundaries', '?')}  │  "
          f"Annotated: {len(vol_ann['cases'])}  │  Status: {sc}{status.upper()}{RESET}")
    print(f"{'═' * 80}")
    print(f"  {BOLD}Case Numbers:{RESET}  {label}")
    if c.get("case_numbers_corrected"):
        print(f"    {YELLOW}(corrected from: {', '.join(c['case_numbers'])}){RESET}")
    print(f"  {BOLD}Bracket Text:{RESET}  {c.get('bracket_text', '')[:120]}")
    print(f"  {BOLD}Date:{RESET}          {c.get('date_corrected') or c.get('date_of_decision') or '(none)'}")
    print(f"  {BOLD}Division:{RESET}      {c.get('division_corrected') or c.get('division') or '(none)'}")
    print(f"  {BOLD}Ponente:{RESET}       {c.get('ponente_name_corrected') or c.get('ponente_name') or '(none)'} "
          f"{c.get('ponente_title', '')}")
    print(f"  {BOLD}Type:{RESET}          {c.get('doc_type') or '(none)'}")
    print(f"  {BOLD}Sections:{RESET}      ", end="")
    sections = []
    if c.get("has_syllabus"):   sections.append("Syllabus")
    if c.get("has_counsel"):    sections.append("Counsel")
    if c.get("has_decision"):   sections.append("Decision")
    if c.get("has_resolution"): sections.append("Resolution")
    if c.get("has_so_ordered"): sections.append("SO ORDERED")
    print(", ".join(sections) or "(none detected)")
    if c.get("separate_opinions"):
        print(f"  {BOLD}Sep. Opinions:{RESET} {json.dumps(c['separate_opinions'])}")
    print(f"  {BOLD}Lines:{RESET}         {c['start_line']}–{c['end_line']}  (pages {c.get('start_page', '?')}–{c.get('end_page', '?')})")
    if c.get("parties_raw"):
        excerpt = (c.get("parties_corrected") or c["parties_raw"])[:200].replace("\n", " ↵ ")
        print(f"  {BOLD}Parties:{RESET}       {excerpt}")
    if c.get("ocr_errors"):
        print(f"  {BOLD}OCR Errors:{RESET}    {len(c['ocr_errors'])} logged")
    if c.get("notes"):
        print(f"  {BOLD}Notes:{RESET}         {c['notes']}")


def prompt_edit(case, vol_name, lines_data):
    """Interactive edit loop for one case. Returns True if user wants to quit."""
    while True:
        print(f"\n{BOLD}Commands:{RESET}")
        print(f"  {GREEN}v{RESET}=verify  {YELLOW}c{RESET}=correct  {RED}f{RESET}=flag  "
              f"t=show text  e=edit field  o=add OCR error  n=notes")
        print(f"  {DIM}Enter{RESET}=next  p=prev  j=jump  q=quit volume  Q=quit all")
        cmd = input(f"  > ").strip().lower()

        if cmd in ("", "next"):
            return "next"
        elif cmd == "p":
            return "prev"
        elif cmd == "j":
            return "jump"
        elif cmd == "q":
            return "quit_vol"
        elif cmd.upper() == "Q":
            return "quit_all"
        elif cmd == "v":
            case["status"] = "verified"
            print(f"  {GREEN}✓ Marked as VERIFIED{RESET}")
            return "next"
        elif cmd == "f":
            case["status"] = "flagged"
            reason = input(f"  Flag reason (optional): ").strip()
            if reason:
                case["notes"] = (case.get("notes") or "") + f" [FLAG: {reason}]"
            print(f"  {RED}⚑ Marked as FLAGGED{RESET}")
            return "next"
        elif cmd == "t":
            show_raw_text(vol_name, case["start_line"], case["end_line"])
        elif cmd == "c":
            case["status"] = "corrected"
            print(f"  {YELLOW}✎ Entering correction mode...{RESET}")
            _edit_fields(case)
        elif cmd == "e":
            _edit_fields(case)
        elif cmd == "o":
            _add_ocr_error(case)
        elif cmd == "n":
            note = input(f"  Note: ").strip()
            if note:
                case["notes"] = note
                print(f"  Note saved.")


def _edit_fields(case):
    """Edit individual fields of a case."""
    print(f"\n  {BOLD}Editable fields:{RESET}")
    print(f"    1. Case numbers    [{', '.join(case.get('case_numbers_corrected') or case.get('case_numbers', []))}]")
    print(f"    2. Date            [{case.get('date_corrected') or case.get('date_of_decision') or ''}]")
    print(f"    3. Division        [{case.get('division_corrected') or case.get('division') or ''}]")
    print(f"    4. Ponente name    [{case.get('ponente_name_corrected') or case.get('ponente_name') or ''}]")
    print(f"    5. Ponente title   [{case.get('ponente_title') or ''}]")
    print(f"    6. Doc type        [{case.get('doc_type') or ''}]")
    print(f"    7. Start line      [{case.get('start_line')}]")
    print(f"    8. End line        [{case.get('end_line')}]")
    print(f"    9. Parties         [{'(set)' if case.get('parties_corrected') or case.get('parties_raw') else '(empty)'}]")
    print(f"   10. Syllabus        [has={case.get('has_syllabus')}]")
    print(f"   11. Counsel         [has={case.get('has_counsel')}]")
    print(f"    0. Done editing")
    while True:
        choice = input(f"  Edit field #: ").strip()
        if choice == "0" or choice == "":
            break
        elif choice == "1":
            val = input(f"    Case numbers (comma-sep): ").strip()
            if val:
                case["case_numbers_corrected"] = [v.strip() for v in val.split(",")]
                case["status"] = "corrected"
        elif choice == "2":
            val = input(f"    Date: ").strip()
            if val:
                case["date_corrected"] = val
                case["status"] = "corrected"
        elif choice == "3":
            val = input(f"    Division: ").strip()
            if val:
                case["division_corrected"] = val
                case["status"] = "corrected"
        elif choice == "4":
            val = input(f"    Ponente name: ").strip()
            if val:
                case["ponente_name_corrected"] = val
                case["status"] = "corrected"
        elif choice == "5":
            val = input(f"    Ponente title (J. or C.J.): ").strip()
            if val:
                case["ponente_title"] = val
        elif choice == "6":
            val = input(f"    Doc type (DECISION/RESOLUTION): ").strip()
            if val:
                case["doc_type"] = val
        elif choice == "7":
            val = input(f"    Start line: ").strip()
            if val.isdigit():
                case["start_line"] = int(val)
                case["status"] = "corrected"
        elif choice == "8":
            val = input(f"    End line: ").strip()
            if val.isdigit():
                case["end_line"] = int(val)
                case["status"] = "corrected"
        elif choice == "9":
            print(f"    Current: {(case.get('parties_corrected') or case.get('parties_raw', ''))[:200]}")
            val = input(f"    New parties (or Enter to keep): ").strip()
            if val:
                case["parties_corrected"] = val
                case["status"] = "corrected"
        elif choice == "10":
            val = input(f"    Has syllabus? (y/n): ").strip().lower()
            if val in ("y", "n"):
                case["has_syllabus"] = val == "y"
        elif choice == "11":
            val = input(f"    Has counsel? (y/n): ").strip().lower()
            if val in ("y", "n"):
                case["has_counsel"] = val == "y"


def _add_ocr_error(case):
    """Add an OCR error record."""
    line_num = input(f"  Line number: ").strip()
    orig = input(f"  Original text: ").strip()
    fixed = input(f"  Corrected text: ").strip()
    if orig:
        case.setdefault("ocr_errors", []).append({
            "line": int(line_num) if line_num.isdigit() else 0,
            "original": orig,
            "corrected": fixed,
        })
        print(f"  {YELLOW}OCR error logged.{RESET}")


def run_annotate():
    """Phase 1: Interactive annotation."""
    data = init_annotations()
    vol_names = [a["volume"] for a in data]

    print(f"\n{BOLD}Volumes available for annotation:{RESET}")
    for i, a in enumerate(data):
        reviewed = sum(1 for c in a["cases"] if c["status"] != "unreviewed")
        total = len(a["cases"])
        pct = (reviewed / total * 100) if total else 0
        print(f"  {i + 1}. {a['volume']:<25} {reviewed}/{total} reviewed ({pct:.0f}%)")

    vol_choice = input(f"\nStart at volume # (1-{len(data)}, or Enter for first incomplete): ").strip()
    if vol_choice.isdigit():
        vol_start = int(vol_choice) - 1
    else:
        # Find first volume with unreviewed cases
        vol_start = 0
        for i, a in enumerate(data):
            if any(c["status"] == "unreviewed" for c in a["cases"]):
                vol_start = i
                break

    for vi in range(vol_start, len(data)):
        vol_ann = data[vi]
        vol_name = vol_ann["volume"]
        cases = vol_ann["cases"]
        print(f"\n{'━' * 80}")
        print(f"  {BOLD}Volume: {vol_name}{RESET}  │  {len(cases)} cases to review")
        print(f"{'━' * 80}")

        # Find first unreviewed case
        ci = 0
        for j, c in enumerate(cases):
            if c["status"] == "unreviewed":
                ci = j
                break

        quit_all = False
        while 0 <= ci < len(cases):
            display_case(vol_ann, cases[ci])
            action = prompt_edit(cases[ci], vol_name, None)
            save_annotations(data)

            if action == "next":
                ci += 1
            elif action == "prev":
                ci = max(0, ci - 1)
            elif action == "jump":
                idx = input(f"  Jump to case # (1-{len(cases)}): ").strip()
                if idx.isdigit():
                    ci = int(idx) - 1
            elif action == "quit_vol":
                break
            elif action == "quit_all":
                quit_all = True
                break

        if quit_all:
            break

    save_annotations(data)
    print(f"\n{GREEN}Annotations saved to {ANNOTATION_FILE}{RESET}")


# ============================================================================
# EXPORT (Phase 2)
# ============================================================================

def run_export():
    """Phase 2: Export ground truth in JSON + CSV + Markdown."""
    if not ANNOTATION_FILE.exists():
        print("ERROR: No annotations found. Run 'annotate' first.")
        sys.exit(1)

    with open(ANNOTATION_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # --- JSON ---
    json_path = EXPORT_DIR / f"ground_truth_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"✅ JSON: {json_path}")

    # --- CSV ---
    csv_path = EXPORT_DIR / f"ground_truth_{ts}.csv"
    csv_fields = [
        "volume", "case_index", "status",
        "start_line", "end_line", "start_page", "end_page",
        "case_numbers", "case_numbers_corrected",
        "date_of_decision", "date_corrected",
        "division", "division_corrected",
        "ponente_name", "ponente_name_corrected", "ponente_title",
        "doc_type",
        "has_syllabus", "has_counsel", "has_decision", "has_resolution", "has_so_ordered",
        "ocr_error_count", "notes",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for ann in data:
            for c in ann["cases"]:
                row = {**c}
                row["volume"] = ann["volume"]
                row["case_numbers"] = ", ".join(c.get("case_numbers", []))
                row["case_numbers_corrected"] = ", ".join(c["case_numbers_corrected"]) if c.get("case_numbers_corrected") else ""
                row["ocr_error_count"] = len(c.get("ocr_errors", []))
                writer.writerow(row)
    print(f"✅ CSV:  {csv_path}")

    # --- Markdown ---
    md_path = EXPORT_DIR / f"ground_truth_{ts}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Ground Truth Annotations for SC Reports Regex Improvement\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")

        total_cases = sum(len(a["cases"]) for a in data)
        reviewed = sum(1 for a in data for c in a["cases"] if c["status"] != "unreviewed")
        corrected = sum(1 for a in data for c in a["cases"] if c["status"] == "corrected")
        ocr_total = sum(len(c.get("ocr_errors", [])) for a in data for c in a["cases"])

        f.write("## Summary\n\n")
        f.write(f"| Metric | Count |\n|---|---|\n")
        f.write(f"| Volumes | {len(data)} |\n")
        f.write(f"| Annotated cases | {total_cases} |\n")
        f.write(f"| Reviewed | {reviewed} |\n")
        f.write(f"| Corrected | {corrected} |\n")
        f.write(f"| OCR errors flagged | {ocr_total} |\n\n")

        # Per-volume case details
        for ann in data:
            f.write(f"## {ann['volume']}\n\n")
            f.write(f"Detected: {ann.get('total_boundaries', 0)} cases | Annotated: {len(ann['cases'])}\n\n")

            for c in ann["cases"]:
                nums = c.get("case_numbers_corrected") or c.get("case_numbers", [])
                label = ", ".join(nums) if isinstance(nums, list) else str(nums)
                f.write(f"### Case {c['case_index']}: {label}\n\n")
                f.write(f"- **Status:** {c['status']}\n")
                f.write(f"- **Lines:** {c['start_line']}–{c['end_line']} (pages {c.get('start_page', '?')}–{c.get('end_page', '?')})\n")
                f.write(f"- **Bracket:** `{c.get('bracket_text', '')[:150]}`\n")
                f.write(f"- **Date:** {c.get('date_corrected') or c.get('date_of_decision') or '(none)'}\n")
                f.write(f"- **Division:** {c.get('division_corrected') or c.get('division') or '(none)'}\n")
                f.write(f"- **Ponente:** {c.get('ponente_name_corrected') or c.get('ponente_name') or '(none)'} {c.get('ponente_title', '')}\n")
                f.write(f"- **Type:** {c.get('doc_type') or '(none)'}\n")

                secs = []
                if c.get("has_syllabus"):   secs.append("Syllabus")
                if c.get("has_counsel"):    secs.append("Counsel")
                if c.get("has_decision"):   secs.append("Decision")
                if c.get("has_resolution"): secs.append("Resolution")
                if c.get("has_so_ordered"): secs.append("SO ORDERED")
                f.write(f"- **Sections:** {', '.join(secs) or '(none)'}\n")

                # Corrections
                corrections = []
                if c.get("case_numbers_corrected"):
                    corrections.append(f"  - Case numbers: `{', '.join(c['case_numbers'])}` → `{', '.join(c['case_numbers_corrected'])}`")
                if c.get("date_corrected"):
                    corrections.append(f"  - Date: `{c['date_of_decision']}` → `{c['date_corrected']}`")
                if c.get("division_corrected"):
                    corrections.append(f"  - Division: `{c['division']}` → `{c['division_corrected']}`")
                if c.get("ponente_name_corrected"):
                    corrections.append(f"  - Ponente: `{c['ponente_name']}` → `{c['ponente_name_corrected']}`")
                if c.get("parties_corrected"):
                    corrections.append(f"  - Parties corrected")
                if corrections:
                    f.write("- **Corrections:**\n" + "\n".join(corrections) + "\n")

                parties = c.get("parties_corrected") or c.get("parties_raw") or ""
                if parties:
                    f.write(f"- **Parties (excerpt):** `{parties[:250].replace(chr(10), ' ')}`\n")

                if c.get("ocr_errors"):
                    f.write(f"- **OCR Errors ({len(c['ocr_errors'])}):**\n")
                    for err in c["ocr_errors"]:
                        f.write(f"  - Line {err['line']}: `{err['original']}` → `{err['corrected']}`\n")
                if c.get("notes"):
                    f.write(f"- **Notes:** {c['notes']}\n")
                f.write("\n")

        # Pattern failure analysis
        f.write("---\n\n## Pattern Failure Analysis\n\n")
        f.write("### Fields needing correction (regex missed or wrong):\n\n")
        for ann in data:
            for c in ann["cases"]:
                if c["status"] != "corrected":
                    continue
                issues = []
                if c.get("case_numbers_corrected"): issues.append("case_numbers")
                if c.get("date_corrected"):         issues.append("date")
                if c.get("division_corrected"):     issues.append("division")
                if c.get("ponente_name_corrected"): issues.append("ponente")
                if c.get("parties_corrected"):      issues.append("parties")
                if c.get("syllabus_corrected"):     issues.append("syllabus")
                if c.get("counsel_corrected"):      issues.append("counsel")
                if issues:
                    nums = c.get("case_numbers_corrected") or c.get("case_numbers", [])
                    label = ", ".join(nums) if isinstance(nums, list) else str(nums)
                    f.write(f"- **{ann['volume']} / {label}** — {', '.join(issues)}\n")

        f.write("\n### OCR errors observed:\n\n")
        all_ocr = []
        for ann in data:
            for c in ann["cases"]:
                for err in c.get("ocr_errors", []):
                    all_ocr.append((ann["volume"], err))
        if all_ocr:
            for vol, err in all_ocr:
                f.write(f"- {vol} line {err['line']}: `{err['original']}` → `{err['corrected']}`\n")
        else:
            f.write("(none flagged yet)\n")

        # Raw bracket samples for regex tuning
        f.write("\n### Raw bracket samples (for regex tuning):\n\n")
        f.write("```\n")
        for ann in data:
            for c in ann["cases"]:
                if c.get("bracket_text"):
                    f.write(f"{ann['volume']}: {c['bracket_text'][:200]}\n")
        f.write("```\n")

    print(f"✅ Markdown: {md_path}")
    print(f"\n📋 Copy {md_path.name} contents into Claude to generate improved regex.")


# ============================================================================
# TEST IMPROVED REGEX (Phase 3)
# ============================================================================

def run_test():
    """Phase 3: Test improved regex against ALL cases in sample volumes."""
    if not ANNOTATION_FILE.exists():
        print("ERROR: No annotations found. Run 'annotate' first.")
        sys.exit(1)

    with open(ANNOTATION_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Try to load improved regex
    improved_patterns = None
    if IMPROVED_REGEX.exists():
        print(f"Loading improved regex from {IMPROVED_REGEX}...")
        import importlib.util
        spec = importlib.util.spec_from_file_location("improved_regex", IMPROVED_REGEX)
        improved_patterns = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(improved_patterns)
        print(f"  ✅ Loaded improved patterns.")
    else:
        print(f"No {IMPROVED_REGEX} found. Testing with CURRENT (baseline) regex.")
        print(f"To test improved regex, create {IMPROVED_REGEX} with the same pattern names.")

    # Use improved patterns if available, else current
    test_case_start    = getattr(improved_patterns, "RE_CASE_START",    RE_CASE_START)    if improved_patterns else RE_CASE_START
    test_case_bracket  = getattr(improved_patterns, "RE_CASE_BRACKET",  RE_CASE_BRACKET)  if improved_patterns else RE_CASE_BRACKET
    test_case_num      = getattr(improved_patterns, "RE_CASE_NUM",      RE_CASE_NUM)      if improved_patterns else RE_CASE_NUM
    test_date          = getattr(improved_patterns, "RE_DATE",          RE_DATE)          if improved_patterns else RE_DATE
    test_division      = getattr(improved_patterns, "RE_DIVISION",      RE_DIVISION)      if improved_patterns else RE_DIVISION
    test_ponente       = getattr(improved_patterns, "RE_PONENTE",       RE_PONENTE)       if improved_patterns else RE_PONENTE
    test_decision      = getattr(improved_patterns, "RE_DECISION",      RE_DECISION)      if improved_patterns else RE_DECISION
    test_resolution    = getattr(improved_patterns, "RE_RESOLUTION",    RE_RESOLUTION)    if improved_patterns else RE_RESOLUTION
    test_syllabus      = getattr(improved_patterns, "RE_SYLLABUS",      RE_SYLLABUS)      if improved_patterns else RE_SYLLABUS
    test_counsel       = getattr(improved_patterns, "RE_COUNSEL",       RE_COUNSEL)       if improved_patterns else RE_COUNSEL

    print(f"\n{'═' * 80}")
    print(f"  REGEX TEST RESULTS")
    print(f"{'═' * 80}\n")

    overall_stats = {
        "total_annotated": 0,
        "boundary_match": 0,
        "boundary_miss": 0,
        "date_match": 0,
        "date_miss": 0,
        "division_match": 0,
        "division_miss": 0,
        "ponente_match": 0,
        "ponente_miss": 0,
        "case_num_match": 0,
        "case_num_miss": 0,
    }

    # Also test on ALL boundaries (not just annotated subset)
    unannotated_stats = {
        "total_unannotated": 0,
        "boundaries_detected": 0,
    }

    for ann in data:
        vol_name = ann["volume"]
        vf = SAMPLES_DIR / vol_name
        if not vf.exists():
            print(f"  ⚠ {vol_name}: file not found, skipping.")
            continue

        lines, page_index = load_volume(vf)
        combined = "\n".join(lines)

        # Run test regex to find all boundaries
        test_boundaries = list(test_case_start.finditer(combined))
        total_detected = len(test_boundaries)

        # Compare against annotated ground truth
        annotated_cases = ann["cases"]
        selected = set(ann.get("selected_indices", []))
        total_boundaries = ann.get('total_boundaries', 0)
        unannotated_count = total_boundaries - len(annotated_cases)

        unannotated_stats["total_unannotated"] += unannotated_count
        unannotated_stats["boundaries_detected"] += total_detected

        vol_match = 0
        vol_miss = 0
        vol_issues = []

        for c in annotated_cases:
            overall_stats["total_annotated"] += 1
            ground_truth_nums = c.get("case_numbers_corrected") or c.get("case_numbers", [])
            gt_date = c.get("date_corrected") or c.get("date_of_decision") or ""
            gt_div = c.get("division_corrected") or c.get("division") or ""
            gt_ponente = c.get("ponente_name_corrected") or c.get("ponente_name") or ""

            # Check if test regex finds a boundary near the ground truth start_line
            gt_start = c["start_line"]
            found_boundary = False
            for tb in test_boundaries:
                # Convert offset to approximate line
                approx_line = combined[:tb.start()].count("\n")
                if abs(approx_line - gt_start) <= 3:
                    found_boundary = True
                    break

            if found_boundary:
                overall_stats["boundary_match"] += 1
                vol_match += 1
            else:
                overall_stats["boundary_miss"] += 1
                vol_miss += 1
                nums_label = ", ".join(ground_truth_nums[:2])
                vol_issues.append(f"    ✗ BOUNDARY MISS: {nums_label} (line {gt_start})")

            # Check sub-field extraction on the case slice
            sl, el = c["start_line"], c["end_line"]
            case_text = "\n".join(lines[sl:min(el + 1, len(lines))])

            # Date
            brackets = list(test_case_bracket.finditer(case_text))
            found_date = ""
            for bm in brackets:
                dm = test_date.search(bm.group(0))
                if dm:
                    found_date = dm.group(1).strip()
                    break
            if gt_date and found_date and gt_date.lower().replace(",", "").replace(" ", "") == found_date.lower().replace(",", "").replace(" ", ""):
                overall_stats["date_match"] += 1
            elif gt_date:
                overall_stats["date_miss"] += 1
                vol_issues.append(f"    ✗ DATE: expected `{gt_date}`, got `{found_date}`")

            # Division
            div_m = test_division.search(case_text[:500])
            found_div = div_m.group(1).strip().upper() if div_m else ""
            found_div = re.sub(r"\s+", " ", found_div)
            if gt_div and found_div and gt_div.upper() == found_div:
                overall_stats["division_match"] += 1
            elif gt_div:
                overall_stats["division_miss"] += 1
                if gt_div.upper() != found_div:
                    vol_issues.append(f"    ✗ DIVISION: expected `{gt_div}`, got `{found_div}`")

            # Ponente
            dec_m = test_decision.search(case_text) or test_resolution.search(case_text)
            found_ponente = ""
            if dec_m:
                after = case_text[dec_m.end():dec_m.end() + 500]
                pm = test_ponente.search(after)
                if pm:
                    found_ponente = pm.group(1).strip()
            if gt_ponente and found_ponente and gt_ponente.upper() == found_ponente.upper():
                overall_stats["ponente_match"] += 1
            elif gt_ponente:
                overall_stats["ponente_miss"] += 1
                vol_issues.append(f"    ✗ PONENTE: expected `{gt_ponente}`, got `{found_ponente}`")

            # Case numbers (just check if at least the first number was found)
            found_nums = []
            for bm in brackets:
                for cn in test_case_num.finditer(bm.group(0)):
                    found_nums.append(re.sub(r"\s+", " ", cn.group()).strip())
            if ground_truth_nums and found_nums:
                # Check if first ground truth number is in found
                gt_first = ground_truth_nums[0].upper().replace(" ", "")
                if any(gt_first == fn.upper().replace(" ", "") for fn in found_nums):
                    overall_stats["case_num_match"] += 1
                else:
                    overall_stats["case_num_miss"] += 1
                    vol_issues.append(f"    ✗ CASE_NUM: expected `{ground_truth_nums[0]}`, got `{found_nums[:2]}`")
            elif ground_truth_nums:
                overall_stats["case_num_miss"] += 1
                vol_issues.append(f"    ✗ CASE_NUM: expected `{ground_truth_nums[0]}`, got nothing")

        # Volume summary
        pct = (vol_match / (vol_match + vol_miss) * 100) if (vol_match + vol_miss) else 0
        status_icon = "✅" if vol_miss == 0 else "⚠️"
        print(f"  {status_icon} {vol_name:<25} boundaries: {vol_match}/{vol_match + vol_miss} ({pct:.0f}%)  "
              f"total detected: {total_detected} (was {total_boundaries})")
        for issue in vol_issues[:10]:
            print(issue)
        if len(vol_issues) > 10:
            print(f"    ... and {len(vol_issues) - 10} more issues")

    # Overall summary
    t = overall_stats
    print(f"\n{'─' * 80}")
    print(f"  OVERALL RESULTS ({t['total_annotated']} annotated cases)")
    print(f"{'─' * 80}")

    def _pct(match, miss):
        total = match + miss
        return f"{match}/{total} ({match / total * 100:.0f}%)" if total else "N/A"

    print(f"  Boundaries:   {_pct(t['boundary_match'], t['boundary_miss'])}")
    print(f"  Case numbers: {_pct(t['case_num_match'], t['case_num_miss'])}")
    print(f"  Dates:        {_pct(t['date_match'], t['date_miss'])}")
    print(f"  Divisions:    {_pct(t['division_match'], t['division_miss'])}")
    print(f"  Ponentes:     {_pct(t['ponente_match'], t['ponente_miss'])}")
    print(f"\n  Unannotated cases in sample volumes: {unannotated_stats['total_unannotated']}")
    print(f"  Total boundaries detected by test regex: {unannotated_stats['boundaries_detected']}")

    # Save test results
    results_path = EXPORT_DIR / f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"overall": overall_stats, "unannotated": unannotated_stats}, f, indent=2)
    print(f"\n  Results saved to {results_path}")


# ============================================================================
# STATUS DASHBOARD
# ============================================================================

def run_status():
    """Show annotation progress."""
    if not ANNOTATION_FILE.exists():
        print("No annotations yet. Run 'annotate' first.")
        return

    with open(ANNOTATION_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"\n{'Volume':<25} {'Detected':>9} {'Annotated':>10} {'Unrev':>6} {'Verified':>9} {'Corrected':>10} {'Flagged':>8} {'OCR':>5}")
    print("=" * 95)
    totals = defaultdict(int)
    for ann in data:
        total_det = ann.get("total_boundaries", 0)
        cases = ann["cases"]
        counts = defaultdict(int)
        ocr_count = 0
        for c in cases:
            counts[c.get("status", "unreviewed")] += 1
            ocr_count += len(c.get("ocr_errors", []))
        print(f"  {ann['volume']:<23} {total_det:>9} {len(cases):>10} "
              f"{counts['unreviewed']:>6} {counts['verified']:>9} "
              f"{counts['corrected']:>10} {counts['flagged']:>8} {ocr_count:>5}")
        totals["detected"] += total_det
        totals["annotated"] += len(cases)
        for s in ("unreviewed", "verified", "corrected", "flagged"):
            totals[s] += counts[s]
        totals["ocr"] += ocr_count
    print("=" * 95)
    print(f"  {'TOTAL':<23} {totals['detected']:>9} {totals['annotated']:>10} "
          f"{totals['unreviewed']:>6} {totals['verified']:>9} "
          f"{totals['corrected']:>10} {totals['flagged']:>8} {totals['ocr']:>5}")


# ============================================================================
# MAIN
# ============================================================================

USAGE = """
SC Reports — Case Annotation & Regex Testing Tool

Usage:
  python annotate_tool.py annotate    Phase 1: Annotate ~10 representative cases per volume
  python annotate_tool.py export      Phase 2: Export ground truth (JSON + CSV + MD for Claude)
  python annotate_tool.py test        Phase 3: Test regex against ground truth
  python annotate_tool.py status      Show annotation progress

Workflow:
  1. Place sample Volume_*.txt files in ./samples/
  2. Run 'annotate' to review pre-populated cases
  3. Run 'export' to generate ground truth files
  4. Paste the .md file into Claude to get improved regex
  5. Save Claude's improved patterns to ./improved_regex.py
  6. Run 'test' to score the improved regex
  7. Iterate steps 3-6 until satisfied
  8. Apply final regex to your 900+ volume database
"""

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    if cmd == "annotate":
        run_annotate()
    elif cmd == "export":
        run_export()
    elif cmd == "test":
        run_test()
    elif cmd == "status":
        run_status()
    else:
        print(f"Unknown command: {cmd}")
        print(USAGE)
        sys.exit(1)
