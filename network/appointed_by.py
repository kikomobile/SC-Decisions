"""Load ph_sc_justices.csv and resolve each justice's appointing president.

For justices with dual entries (Associate Justice + Chief Justice), the
appointing president of the longer-tenured position is used.
"""

import csv
import re
from pathlib import Path

# Bright colors for each appointing president (dark-background friendly).
# Ordered roughly chronologically; only modern-era presidents are likely
# to appear in the graph (volumes 121+, ~1965 onward).
PRESIDENT_COLORS = {
    # US-era (rare in graph)
    "William McKinley":       "#888888",
    "Theodore Roosevelt":     "#888888",
    "William Howard Taft":    "#888888",
    "Woodrow Wilson":         "#888888",
    "Warren G. Harding":      "#888888",
    "Calvin Coolidge":        "#888888",
    "Herbert Hoover":         "#888888",
    "Franklin D. Roosevelt":  "#888888",
    # Japanese occupation
    "Masaharu Homma":         "#888888",
    "Jorge B. Vargas":        "#888888",
    "Jose P. Laurel":         "#888888",
    # Early Philippine presidents
    "Sergio Osmeña":          "#888888",
    "Manuel L. Quezon":       "#888888",
    "Manuel Roxas":           "#888888",
    "Elpidio Quirino":        "#888888",
    # Modern Philippine presidents (likely in graph)
    "Ramon Magsaysay":        "#f28e2b",  # warm orange
    "Carlos P. Garcia":       "#e15759",  # soft red
    "Diosdado Macapagal":     "#76b7b2",  # teal
    "Ferdinand Marcos":       "#ff4d6a",  # neon pink
    "Corazon Aquino":         "#ffcc44",  # gold
    "Fidel V. Ramos":         "#4dff91",  # neon green
    "Joseph Estrada":         "#33eeff",  # neon cyan
    "Gloria Macapagal Arroyo": "#bb66ff", # neon purple
    "Benigno Aquino III":     "#4d8bff",  # neon blue
    "Rodrigo Duterte":        "#ff55cc",  # neon magenta
    "Bongbong Marcos":        "#ccff44",  # neon lime
}

FALLBACK_COLOR = "#666666"

# Manual aliases for registry names that don't straightforwardly match CSV names.
# Format: registry_name (uppercase) -> CSV "Name" substring to look for.
_ALIASES = {
    "ARANAL-SERENO":      "Sereno",
    "CARPIO MORALES":     "Carpio-Morales",
    "GRINO-AQUINO":       "Aquino",          # Carolina Griño-Aquino
    "LEONARDO-DE CASTRO": "Teresita de Castro",
    "J. LOPEZ":           "Jhosep Lopez",
    "M. LOPEZ":           "Mario Lopez",
    "REYES, A. JR.":      "Andres Reyes",
    "REYES, J. JR.":      "Jose Reyes Jr.",
}


def _parse_tenure_days(tenure_str: str) -> int:
    """Parse 'X years Y days' into total days. Returns 0 on failure."""
    if not tenure_str:
        return 0
    years = 0
    days = 0
    m = re.search(r'(\d+)\s+year', tenure_str)
    if m:
        years = int(m.group(1))
    m = re.search(r'(\d+)\s+day', tenure_str)
    if m:
        days = int(m.group(1))
    return years * 365 + days


def load_justices_csv(csv_path: str | Path) -> list[dict]:
    """Load ph_sc_justices.csv and return list of row dicts."""
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def resolve_appointed_by(rows: list[dict]) -> dict[str, str]:
    """Build {full_name: appointed_by_president} resolving dual appointments.

    For justices with two entries (AJ + CJ), the president who appointed
    them to the position with the longer tenure is used.
    """
    # Group entries by name
    by_name: dict[str, list[dict]] = {}
    for r in rows:
        name = r["Name"]
        by_name.setdefault(name, []).append(r)

    result = {}
    for name, entries in by_name.items():
        if len(entries) == 1:
            result[name] = entries[0]["Appointed By"]
        else:
            # Pick the entry with the longer tenure
            best = max(entries, key=lambda e: _parse_tenure_days(e.get("Tenure Length", "")))
            result[name] = best["Appointed By"]
    return result


def build_appointed_by_map(
    node_names: list[str], csv_path: str | Path,
) -> dict[str, str]:
    """Map graph node names to appointing presidents.

    Supports both full-name nodes (e.g. "Arturo Brion") and legacy
    surname-only nodes (e.g. "CARPIO").

    Args:
        node_names: List of graph node names.
        csv_path: Path to ph_sc_justices.csv.

    Returns:
        {node_name: president_name} for each node that could be matched.
        Unmatched nodes are omitted from the dict.
    """
    rows = load_justices_csv(csv_path)
    name_to_president = resolve_appointed_by(rows)

    # Build lookup helpers
    csv_names = list(name_to_president.keys())

    result = {}
    for node in node_names:
        # --- Strategy 0: Exact full-name match (new pipeline with full names) ---
        if node in name_to_president:
            result[node] = name_to_president[node]
            continue

        node_upper = node.upper().strip()

        # --- Strategy 1: Check manual aliases ---
        if node_upper in _ALIASES:
            alias = _ALIASES[node_upper]
            for csv_name in csv_names:
                if alias.lower() in csv_name.lower():
                    result[node] = name_to_president[csv_name]
                    break
            if node in result:
                continue

        # --- Strategy 2: Word-level token matching ---
        clean = node_upper.replace(",", "").replace("JR.", "").replace("SR.", "").strip()
        tokens = clean.split()

        matched = False
        for csv_name in csv_names:
            csv_words = set(csv_name.upper().split())
            if all(t in csv_words for t in tokens):
                result[node] = name_to_president[csv_name]
                matched = True
                break

        if matched:
            continue

        # --- Strategy 3: Last-token unambiguous match ---
        last_token = tokens[-1] if tokens else ""
        if last_token and len(last_token) >= 4:
            candidates = [
                cn for cn in csv_names if last_token in cn.upper().split()
            ]
            if len(candidates) == 1:
                result[node] = name_to_president[candidates[0]]

    return result
