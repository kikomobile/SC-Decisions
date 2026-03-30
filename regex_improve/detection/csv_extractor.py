"""
CSV extraction module for detection pipeline.
Extracts case_number, date, ponente, votes from predicted JSON files into a CSV.
Uses fuzzy matching against justices.json for clean justice name resolution.
Includes auto-archiving of previous CSV runs.

When ph_sc_justices.csv is provided, resolves ambiguous surnames to full names
using tenure dates (e.g. "Brion" + case date 2010 → "Arturo Brion").
"""

import csv
import glob
import json
import os
import re
import shutil
from datetime import datetime, date as _date, timedelta
from difflib import SequenceMatcher
from pathlib import Path


# ---------------------------------------------------------------------------
# Title-casing
# ---------------------------------------------------------------------------

def title_case_justice(name: str) -> str:
    """Convert UPPER_CASE justice name to Title Case.

    GUTIERREZ, JR. → Gutierrez, Jr.
    MELENCIO-HERRERA → Melencio-Herrera
    CARPIO MORALES → Carpio Morales
    """
    def _title_token(tok: str) -> str:
        if "-" in tok:
            return "-".join(w.capitalize() for w in tok.split("-"))
        return tok.capitalize()

    tokens = name.split()
    result = []
    for tok in tokens:
        trail = ""
        if tok.endswith(","):
            trail = ","
            tok = tok[:-1]
        dot = ""
        if tok.endswith("."):
            dot = "."
            tok = tok[:-1]
        result.append(_title_token(tok) + dot + trail)
    return " ".join(result)


# ---------------------------------------------------------------------------
# Date parsing helper
# ---------------------------------------------------------------------------

def _parse_date_flexible(s: str) -> "_date | None":
    """Parse various date formats to datetime.date, or None."""
    if not s or not s.strip():
        return None
    s = s.strip()
    if s.lower() == "incumbent":
        return None
    s = re.sub(r'(\d+)(st|nd|rd|th)\b', r'\1', s)
    for fmt in ("%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y",
                "%B %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Explicit CSV overrides for known ambiguous registry names.
# Each key is a justices.json entry; values are full names from
# ph_sc_justices.csv that can match that registry entry.
# ---------------------------------------------------------------------------

_REGISTRY_CSV_OVERRIDE = {
    # Both "Brion" and "Briones" OCR variants may match registry "BRION";
    # include both candidates so case date picks the correct one.
    "BRION":    ["Arturo Brion", "Manuel Briones"],
    "BRIONES":  ["Manuel Briones", "Arturo Brion"],
    # Prevent fuzzy-match leakage into Fernando / Fernandez
    "FERNAN":   ["Marcelo Fernan"],
    # Prevent leakage into Abad Santos
    "ABAD":     ["Roberto A. Abad"],
}


# ---------------------------------------------------------------------------
# JusticeMatcher — fuzzy matching against justices.json
# ---------------------------------------------------------------------------

class JusticeMatcher:
    """Match noisy OCR tokens to canonical justice names.

    When *csv_path* (``ph_sc_justices.csv``) is provided, resolves ambiguous
    surname matches to full names using the case date vs. tenure dates.
    """

    def __init__(self, justices_path: str, threshold: float = 0.75,
                 csv_path: str | None = None):
        with open(justices_path, encoding="utf-8") as f:
            data = json.load(f)
        raw_list = data["justices"] if isinstance(data, dict) else data

        self.justices = [j.upper().strip() for j in raw_list]
        self.title_map = {j: title_case_justice(j) for j in self.justices}
        self.threshold = threshold
        self._cache: dict[str, tuple[str | None, float]] = {}

        # Reverse lookup: title-cased → UPPER registry name
        self._title_to_registry = {v: k for k, v in self.title_map.items()}

        # Aliases: alternate names that should resolve to a canonical justice
        self._aliases: dict[str, str] = {
            "ARANAL-SERENO": "SERENO",
            "SANTIAGO": "YNARES-SANTIAGO",
        }

        # Exact lookup: full name AND base name (without Jr./Sr. suffix)
        self._exact: dict[str, str] = {}
        for j in self.justices:
            self._exact[j] = j
            base = re.sub(r",?\s*(JR|SR)\.?\s*$", "", j).strip()
            if base and base != j:
                self._exact[base] = j
        # Map last token of compound names (e.g., "MORALES" → "CARPIO MORALES")
        # Only for unambiguous cases: token appears in exactly one compound name
        # and isn't already a standalone justice or a suffix like JR/SR
        from collections import Counter
        last_token_counts: Counter = Counter()
        last_token_source: dict[str, str] = {}
        for j in self.justices:
            tokens = j.split()
            if len(tokens) >= 2:
                last = tokens[-1].rstrip(".,")
                if last and len(last) >= 3:  # skip JR, SR
                    last_token_counts[last] += 1
                    last_token_source[last] = j
        for tok, count in last_token_counts.items():
            if count == 1 and tok not in self._exact:
                self._exact[tok] = last_token_source[tok]

        # --- Full-name resolution via ph_sc_justices.csv ---
        self._persons: dict[str, dict] = {}          # full_name → {tenure_start, tenure_end}
        self._registry_to_persons: dict[str, list[str]] = {}  # REGISTRY → [full_name, ...]
        if csv_path and Path(csv_path).exists():
            self._load_csv_data(csv_path)

    # ------------------------------------------------------------------
    # CSV loading and full-name resolution
    # ------------------------------------------------------------------

    def _load_csv_data(self, csv_path: str):
        """Load ph_sc_justices.csv and build registry → full-name mappings."""
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        # Group CSV rows by person name; compute combined tenure range
        from collections import defaultdict
        by_name: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_name[row["Name"].strip()].append(row)

        for name, entries in by_name.items():
            starts, ends = [], []
            for e in entries:
                s = _parse_date_flexible(e.get("Tenure Start", ""))
                en = _parse_date_flexible(e.get("Tenure End", ""))
                if s:
                    starts.append(s)
                if en:
                    ends.append(en)
            self._persons[name] = {
                "tenure_start": min(starts) if starts else None,
                "tenure_end": max(ends) if ends else None,  # None → incumbent
            }

        # Map each registry name to matching CSV persons
        self._build_registry_mapping()

    def _match_registry_to_person(self, reg_name: str, person_name: str) -> bool:
        """Test whether a registry surname matches a full person name."""
        # Parse registry name into tokens
        reg_clean = reg_name.replace(",", " ").replace(".", " ").replace("-", " ")
        has_jr = bool(re.search(r"\bJR\b", reg_clean, re.IGNORECASE))
        reg_clean = re.sub(r"\b(JR|SR)\b", "", reg_clean, flags=re.IGNORECASE).strip()
        reg_tokens = [t.upper() for t in reg_clean.split() if t]

        # Parse person name
        pn = person_name.replace(".", " ")
        pn_has_jr = bool(re.search(r"\bJr\b", person_name, re.IGNORECASE))
        pn_clean = re.sub(r"\b(Jr|Sr)\.?\b", "", pn, flags=re.IGNORECASE)
        pn_clean = pn_clean.replace("-", " ").strip()
        pn_tokens = [t.upper() for t in pn_clean.split() if t]
        # Also keep hyphen-joined forms as words
        pn_words = set(pn_tokens) | set(person_name.upper().split())

        # Jr/Sr constraint: if registry has Jr, person must have Jr
        if has_jr and not pn_has_jr:
            return False

        for rt in reg_tokens:
            if len(rt) == 1:
                # Initial: must match first letter of some person token
                if not any(pt.startswith(rt) for pt in pn_tokens):
                    return False
            else:
                if rt not in pn_words:
                    return False
        return True

    def _build_registry_mapping(self):
        """Map each justices.json entry to matching ph_sc_justices.csv persons."""
        # Sort by specificity (more tokens → more specific → processed first)
        def _token_count(reg):
            c = reg.replace(",", " ").replace(".", " ").replace("-", " ")
            c = re.sub(r"\b(JR|SR)\b", "", c, flags=re.IGNORECASE).strip()
            return len([t for t in c.split() if t])

        sorted_reg = sorted(self.justices, key=lambda j: -_token_count(j))
        claimed: set[str] = set()

        for reg_name in sorted_reg:
            # Check explicit overrides first
            if reg_name in _REGISTRY_CSV_OVERRIDE:
                valid = [n for n in _REGISTRY_CSV_OVERRIDE[reg_name]
                         if n in self._persons]
                if valid:
                    self._registry_to_persons[reg_name] = valid
                    for v in valid:
                        claimed.add(v)
                    continue

            # Generic word-level + initial matching
            matches = []
            for person_name in self._persons:
                if person_name in claimed:
                    continue
                if self._match_registry_to_person(reg_name, person_name):
                    matches.append(person_name)

            if matches:
                self._registry_to_persons[reg_name] = matches
                if len(matches) == 1:
                    claimed.add(matches[0])

    def _resolve_full_name(self, registry_name: str,
                           case_date_str: str | None = None) -> str:
        """Resolve a UPPER registry name to a full CSV name.

        Uses case date to disambiguate when multiple persons share a surname.
        Falls back to title-cased registry name if CSV was not loaded.
        """
        if not self._persons:
            return self.title_map.get(registry_name,
                                      title_case_justice(registry_name))

        candidates = self._registry_to_persons.get(registry_name)
        if not candidates:
            return self.title_map.get(registry_name,
                                      title_case_justice(registry_name))

        if len(candidates) == 1:
            return candidates[0]

        # Multiple candidates — use case date to disambiguate
        if case_date_str:
            case_date = _parse_date_flexible(case_date_str)
            if case_date:
                buffer = timedelta(days=730)  # decisions published up to ~2yr post-term
                for cand in candidates:
                    person = self._persons[cand]
                    start = person["tenure_start"]
                    end = person["tenure_end"]
                    if start is None:
                        continue
                    if case_date < start - timedelta(days=365):
                        continue
                    if end is not None and case_date > end + buffer:
                        continue
                    return cand

        # No date or no tenure overlap — return most recent candidate
        with_dates = [(n, self._persons[n]["tenure_start"])
                      for n in candidates if self._persons[n]["tenure_start"]]
        if with_dates:
            with_dates.sort(key=lambda x: x[1], reverse=True)
            return with_dates[0][0]

        return candidates[0]

    # ------------------------------------------------------------------
    def match(self, candidate: str, case_date: str | None = None,
              ) -> tuple[str | None, float]:
        """Return (resolved_name, score) or (None, 0.0).

        When CSV data is loaded and *case_date* is provided, returns the
        full name from ph_sc_justices.csv (e.g. "Arturo Brion").
        Otherwise returns the title-cased registry surname (e.g. "Brion").
        """
        key = candidate.strip()
        if not key or len(key) < 2:
            return None, 0.0

        # Step 1: fuzzy-match to registry surname (cached, date-independent)
        if key in self._cache:
            reg_name, score = self._cache[key]
        else:
            reg_name, score = self._do_match(key)
            self._cache[key] = (reg_name, score)

        if not reg_name:
            return None, 0.0

        # Step 2: resolve to full name using CSV + date (if available)
        if self._persons:
            registry_upper = self._title_to_registry.get(reg_name, reg_name.upper())
            full = self._resolve_full_name(registry_upper, case_date)
            return full, score

        return reg_name, score

    def match_pair(self, tok1: str, tok2: str,
                   case_date: str | None = None) -> tuple[str | None, float]:
        """Try matching two adjacent tokens as a compound name."""
        return self.match(f"{tok1} {tok2}", case_date=case_date)

    # ------------------------------------------------------------------
    def _do_match(self, candidate: str) -> tuple[str | None, float]:
        cu = candidate.upper().strip()

        # 0. Check aliases (alternate names for the same justice)
        if cu in self._aliases:
            canonical = self._aliases[cu]
            if canonical in self._exact:
                return self.title_map[self._exact[canonical]], 1.0

        # 1. Exact match
        if cu in self._exact:
            return self.title_map[self._exact[cu]], 1.0

        # 2. Try appending common suffixes
        for suffix in [", JR.", ", SR."]:
            aug = cu + suffix
            if aug in self._exact:
                return self.title_map[self._exact[aug]], 1.0

        # 3. Fuzzy match
        best_justice = None
        best_ratio = 0.0

        for j in self.justices:
            ratio = SequenceMatcher(None, cu, j).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_justice = j
            # Also compare against base (without Jr./Sr.)
            base = re.sub(r",?\s*(JR|SR)\.?\s*$", "", j).strip()
            if base != j:
                r2 = SequenceMatcher(None, cu, base).ratio()
                if r2 > best_ratio:
                    best_ratio = r2
                    best_justice = j

        if best_ratio >= self.threshold and best_justice:
            return self.title_map[best_justice], best_ratio

        return None, 0.0

    # ------------------------------------------------------------------
    # Vote parsing
    # ------------------------------------------------------------------

    def parse_votes(self, raw_votes: str,
                    case_date: str | None = None) -> dict:
        """Parse votes text into categories with clean justice names.

        Returns dict with keys:
            concurring, dissenting, no_part, on_leave, other, unmatched
        Each value is a list of strings.
        """
        result = {
            "concurring": [],
            "dissenting": [],
            "no_part": [],
            "on_leave": [],
            "other": [],
            "unmatched": [],
        }

        if not raw_votes:
            return result

        text = " ".join(raw_votes.split())

        # --- Normalize OCR variants of "concur" to canonical form ---
        # Hyphenated line breaks: "con- cur" or "con cur" → "concur"
        text = re.sub(r'\bcon-\s*cur', 'concur', text, flags=re.IGNORECASE)
        text = re.sub(r'\bcon\s+cur', 'concur', text, flags=re.IGNORECASE)
        # Underscore-prefixed (blocks \b): "_concur" → " concur"
        text = re.sub(r'_concur', ' concur', text, flags=re.IGNORECASE)
        # Single-word OCR misspellings → "concur"
        text = re.sub(
            r'\b(?:coneur|concue|concuf|soncur|concor|coricur|conour|'
            r'concut|conrur|concui)\b',
            'concur', text, flags=re.IGNORECASE,
        )

        # Find all vote action verbs in the text.
        # Each verb classifies the justice names that PRECEDE it.
        actions = list(self._VOTE_VERB_RE.finditer(text))

        if not actions:
            return result

        prev_end = 0
        for m in actions:
            names_text = text[prev_end:m.start()]
            verb = m.group().lower()

            # Classify by the verb
            if 'dissent' in verb:
                category = 'dissenting'
            elif 'no' in verb and 'part' in verb:
                category = 'no_part'
            elif 'leave' in verb:
                category = 'on_leave'
            else:  # concur / concut / conrur / concui
                category = 'concurring'

            matched, unmatched = self._extract_justices(names_text,
                                                        case_date=case_date)
            result[category].extend(matched)
            result["unmatched"].extend(unmatched)

            prev_end = m.end()

        # Deduplicate while preserving order
        for key in result:
            seen = set()
            deduped = []
            for name in result[key]:
                if name not in seen:
                    seen.add(name)
                    deduped.append(name)
            result[key] = deduped

        return result

    # ------------------------------------------------------------------

    # Tokens that are never justice names
    _NOISE = {
        "JJ", "CJ", "Jr", "Jr.", "Sr", "Sr.", "III", "II", "IV", "J", "C",
        "Acting", "Chairman", "Chief", "Justice", "Associate",
        "Ponente", "ponente", "PONENTE",
        "OPINION", "Opinion", "CONCURRING", "DISSENTING", "SEPARATE",
        "Acting C.J", "Acting CJ",
        "S.A.J", "S.A", "Senior Associate Justice",
        "Chairperson", "JJ/", "J//", "JA/", "C./", "C.F",
        "Wife", "However", "Please sce",
    }

    # Regex matching vote action verbs (including OCR variants).
    # Longer alternatives listed first so finditer prefers them.
    _VOTE_VERB_RE = re.compile(
        r'\b(?:'
        r'(?:took|1ook|look)\s+no\s+part|'   # "took no part" + OCR
        r'no\s+part|'                         # bare "no part"
        r'on\s+(?:official\s+)?leave|'        # "on leave" / "on official leave"
        r'concur\w*|'                         # "concur" (OCR variants pre-normalized)
        r'dissent\w*'                         # "dissent"
        r')',
        re.IGNORECASE,
    )

    def _extract_justices(self, clause: str,
                          case_date: str | None = None,
                          ) -> tuple[list[str], list[str]]:
        """Extract justice names from a single clause via fuzzy matching."""
        matched = []
        unmatched = []

        # --- Step 0: protect initial-prefixed names (J. Lopez, M. Lopez,
        #             Reyes, J. Jr., Reyes, A. Jr.) before suffix stripping
        text = clause
        text = re.sub(r"\bJ\.\s+Lopez", "J__Lopez", text)
        text = re.sub(r"\bM\.\s+Lopez", "M__Lopez", text)
        text = re.sub(r"\bReyes,\s*J\.\s*Jr", "Reyes_J_Jr", text)
        text = re.sub(r"\bReyes,\s*A\.\s*Jr", "Reyes_A_Jr", text)

        # --- Step 1: strip justice suffixes (JJ., J., C.J., etc.) ----------
        text = re.sub(
            r",?\s*(?:JJ|J/J|J/\.|C\.?\s*/?\s*J|J)\s*[.,]",
            ",", text, flags=re.IGNORECASE,
        )

        # --- Step 2: remove parentheticals like (Chairman), (Chairman} -----
        text = re.sub(r"\s*\([^)}]*[)}]\s*", " ", text)

        # --- Step 3: cut at the action verb --------------------------------
        action = re.search(
            r"\b(?:concur\w*|dissent\w*|"
            r"(?:took|1ook|look)\s+no\s+part|no\s+part|"
            r"on\s+(?:official\s+)?leave|"
            r"see\s+(?:separate|concurring|dissenting)|"
            r"please\s+see|joins?\s|maintained?\b|reserves?\b|"
            r"following\s|reiterates?\b|in\s+the\s+result)",
            text, re.IGNORECASE,
        )
        if action:
            text = text[: action.start()]

        # --- Step 4: protect Jr./Sr. from comma-splitting ------------------
        # Replace "Jr." / "Jr," with marker + comma so the comma delimiter
        # between Jr and the next name is preserved
        text = re.sub(r"\bJr\s*[.,]\s*", "Jr##, ", text)
        text = re.sub(r"\bSr\s*[.,]\s*", "Sr##, ", text)

        # --- Step 5: split on commas / "and" / OCR artifacts ---------------
        parts = re.split(
            r"\s*[,.][\s.\-]*and\s+|\s*,\s*and\s+|\s*,\s*|\s+and\s+", text
        )
        parts = [p.replace("Jr##", ", Jr.").replace("Sr##", ", Sr.")
                  .replace("J__Lopez", "J. Lopez").replace("M__Lopez", "M. Lopez")
                  .replace("Reyes_J_Jr", "Reyes, J. Jr.")
                  .replace("Reyes_A_Jr", "Reyes, A. Jr.")
                  .strip()
                 for p in parts]

        # --- Step 6: basic cleanup of each token --------------------------
        cleaned = []
        for p in parts:
            p = re.sub(r"^[\s.,;:\-*\x93\x94\x97'\"]+", "", p)
            p = re.sub(r"[\s.,;:\-*\x93\x94\x97'\"]+$", "", p)
            p = p.strip()
            if p and len(p) >= 2 and p not in self._NOISE:
                cleaned.append(p)

        # --- Step 7: greedy match — try pairs first, then singles ---------
        i = 0
        while i < len(cleaned):
            pair_name, pair_score = None, 0.0
            single_name, single_score = None, 0.0

            # Try combining with next token (for compound names like Abad Santos)
            if i + 1 < len(cleaned):
                pair_name, pair_score = self.match_pair(
                    cleaned[i], cleaned[i + 1], case_date=case_date)

            single_name, single_score = self.match(cleaned[i],
                                                   case_date=case_date)

            if pair_name and pair_score >= single_score and pair_score >= self.threshold:
                matched.append(pair_name)
                i += 2
            elif single_name and single_score >= self.threshold:
                matched.append(single_name)
                i += 1
            else:
                # Fallback: split the token on whitespace and try matching
                # each sub-token. Handles OCR-jammed names like
                # "Fernan Alampay" (missing comma) or "Bellosillo Acting"
                tok = cleaned[i]
                sub_tokens = tok.split()
                any_sub_matched = False
                if len(sub_tokens) >= 2:
                    for st in sub_tokens:
                        st = re.sub(
                            r"^[\s.,;:\-*\x93\x94\x97'\"]+|"
                            r"[\s.,;:\-*\x93\x94\x97'\"]+$", "", st
                        )
                        if not st or len(st) < 2 or st in self._NOISE:
                            continue
                        sub_name, sub_score = self.match(st,
                                                        case_date=case_date)
                        if sub_name and sub_score >= self.threshold:
                            matched.append(sub_name)
                            any_sub_matched = True
                if not any_sub_matched:
                    if (
                        re.search(r"[A-Z]", tok)
                        and len(tok) >= 3
                        and tok.upper() not in {n.upper() for n in self._NOISE}
                    ):
                        unmatched.append(tok)
                i += 1

        return matched, unmatched


# ---------------------------------------------------------------------------
# Case extraction
# ---------------------------------------------------------------------------

def parse_confidence(notes: str) -> str:
    if not notes:
        return ""
    m = re.search(r"confidence:\s*([\d.]+)", notes)
    return m.group(1) if m else ""


def extract_cases(filepath: str, matcher: JusticeMatcher) -> list:
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for vol in data.get("volumes", []):
        volume_name = vol.get("volume_name", "")
        vol_match = re.search(r"(\d+)", volume_name)
        volume_num = int(vol_match.group(1)) if vol_match else volume_name

        for case in vol.get("cases", []):
            annotations = case.get("annotations", [])

            by_label: dict[str, list] = {}
            for a in annotations:
                by_label.setdefault(a["label"], []).append(a)

            case_numbers = [a["text"] for a in by_label.get("case_number", [])]
            case_number_combined = "; ".join(case_numbers)

            divisions = by_label.get("division", [])
            division_text = divisions[0]["text"].strip() if divisions else ""

            dates = by_label.get("date", [])
            date_text = dates[0]["text"] if dates else ""

            ponentes = by_label.get("ponente", [])
            ponente_text = ponentes[0]["text"] if ponentes else ""
            # Also resolve ponente through matcher for consistency
            if ponente_text:
                matched_ponente, _ = matcher.match(ponente_text,
                                                   case_date=date_text)
                if matched_ponente:
                    ponente_text = matched_ponente

            votes_annotations = by_label.get("votes", [])
            votes_raw = " ".join(
                " ".join(a["text"].split()) for a in votes_annotations
            )

            parsed = matcher.parse_votes(votes_raw, case_date=date_text)
            confidence = parse_confidence(case.get("notes", ""))

            # Skip ghost cases — no case_number means the boundary FSM detected a
            # case start but the extractor found no content fields
            if not case_number_combined.strip():
                continue

            rows.append(
                {
                    "volume": volume_num,
                    "case_number": case_number_combined,
                    "division": division_text,
                    "date": date_text,
                    "ponente": ponente_text,
                    "votes_raw": votes_raw,
                    "concurring": "; ".join(parsed["concurring"]),
                    "dissenting": "; ".join(parsed["dissenting"]),
                    "no_part": "; ".join(parsed["no_part"]),
                    "on_leave": "; ".join(parsed["on_leave"]),
                    "other_votes": "; ".join(parsed["other"]),
                    "unmatched_tokens": "; ".join(parsed["unmatched"]),
                    "confidence": confidence,
                }
            )

    return rows


# ---------------------------------------------------------------------------
# CSV fieldnames and auto-archive functions
# ---------------------------------------------------------------------------

CSV_FIELDNAMES = [
    "volume", "case_number", "division", "date", "ponente", "votes_raw",
    "concurring", "dissenting", "no_part", "on_leave",
    "other_votes", "unmatched_tokens", "confidence",
]


def archive_csv(csv_path) -> "Path | None":
    """Move an existing CSV to an archive directory with a timestamp suffix.

    Archive dir is ``csv_archive/`` next to the CSV file.
    Returns the archive path, or None if source doesn't exist.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return None

    archive_dir = csv_path.parent / "csv_archive"
    archive_dir.mkdir(exist_ok=True)

    mtime = datetime.fromtimestamp(csv_path.stat().st_mtime)
    timestamp = mtime.strftime("%Y%m%d_%H%M%S")
    archive_name = f"{csv_path.stem}_{timestamp}{csv_path.suffix}"
    archive_path = archive_dir / archive_name

    # If archive already exists (same second), add a counter
    counter = 1
    while archive_path.exists():
        archive_name = f"{csv_path.stem}_{timestamp}_{counter}{csv_path.suffix}"
        archive_path = archive_dir / archive_name
        counter += 1

    shutil.move(str(csv_path), str(archive_path))
    return archive_path


def write_predictions_csv(
    input_dir,
    output_path,
    justices_path,
    threshold: float = 0.75,
    archive: bool = True,
    csv_path: str | None = None,
) -> dict:
    """Extract predictions from JSON files and write a CSV.

    Args:
        input_dir: Directory containing \\*_predicted.json files
        output_path: Path to write the CSV
        justices_path: Path to justices.json
        threshold: Fuzzy match threshold for JusticeMatcher
        archive: If True, archive existing CSV before writing
        csv_path: Optional path to ph_sc_justices.csv for full-name resolution

    Returns:
        dict with keys: total_cases, no_case_number, no_ponente, no_votes,
        overflow_1k, archived_to (or None)
    """
    input_dir = Path(input_dir)
    output_path = Path(output_path)
    justices_path = Path(justices_path)

    if not justices_path.exists():
        raise FileNotFoundError(f"justices.json not found at {justices_path}")

    # Auto-detect ph_sc_justices.csv if not provided
    if csv_path is None:
        auto = justices_path.parent.parent.parent / "ph_sc_justices.csv"
        if auto.exists():
            csv_path = str(auto)

    matcher = JusticeMatcher(str(justices_path), threshold=threshold,
                             csv_path=csv_path)
    print(f"Loaded {len(matcher.justices)} justices (threshold={threshold})")

    pattern = str(input_dir / "*_predicted.json")
    files = sorted(glob.glob(pattern))

    if not files:
        raise FileNotFoundError(f"No predicted JSON files found in {input_dir}")

    print(f"Processing {len(files)} prediction files...")

    all_rows = []
    for filepath in files:
        try:
            rows = extract_cases(filepath, matcher)
            all_rows.extend(rows)
        except Exception as e:
            print(f"  ERROR processing {os.path.basename(filepath)}: {e}")

    all_rows.sort(key=lambda r: (r["volume"] if isinstance(r["volume"], int) else 0))

    # Archive previous CSV
    archived_to = None
    if archive:
        archived_to = archive_csv(output_path)
        if archived_to:
            print(f"Archived previous CSV to {archived_to}")

    # Write CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    # Compute stats
    stats = {
        "total_cases": len(all_rows),
        "no_case_number": sum(1 for r in all_rows if not r["case_number"].strip()),
        "no_ponente": sum(1 for r in all_rows if not r["ponente"].strip()),
        "no_votes": sum(1 for r in all_rows if not r["votes_raw"].strip()),
        "overflow_1k": sum(1 for r in all_rows if len(r["votes_raw"]) > 1000),
        "archived_to": str(archived_to) if archived_to else None,
    }

    print(f"Wrote {len(all_rows)} cases to {output_path}")
    print(f"  No ponente: {stats['no_ponente']}  |  No votes: {stats['no_votes']}  |  Overflow: {stats['overflow_1k']}")

    # Justice matcher stats
    has_unmatched = sum(1 for r in all_rows if r["unmatched_tokens"])
    print(f"Justice matcher cache: {len(matcher._cache)} unique tokens resolved")
    print(f"Cases with unmatched tokens: {has_unmatched} / {len(all_rows)}")

    return stats
