"""
Build a weighted undirected graph of Supreme Court justices' voting patterns.

Nodes = justices, edge weight = number of cases where two justices voted together.
Reads predictions_extract.csv and outputs edge list, adjacency matrix, and GraphML.

Usage:
    python network/build_network.py
    python network/build_network.py --csv path/to/file.csv --min-confidence 0.8 --output-dir results/
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import networkx as nx

# Allow imports from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from regex_improve.detection.csv_extractor import JusticeMatcher

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXCLUDE_NAMES = {"LLM_TEST_MARKER", "Per curiam", "PER CURIAM", ""}

DEFAULT_CSV = "predictions_extract.csv"
DEFAULT_JUSTICES = "regex_improve/detection/justices.json"
DEFAULT_OUTPUT_DIR = "network_output"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Display name extraction  (full name → surname label)
# ---------------------------------------------------------------------------

# Compound surnames that can't be derived by "take the last word"
_DISPLAY_OVERRIDES = {
    "Jose Abad Santos":         "Abad Santos",
    "Vicente Abad Santos":      "Abad Santos",
    "Priscilla Baltazar-Padilla": "Baltazar-Padilla",
}


def extract_display_name(full_name: str) -> str:
    """Extract a short display surname from a full justice name.

    'Arturo Brion'          → 'Brion'
    'Andres Reyes Jr.'      → 'Reyes, Jr.'
    'J. B. L. Reyes'        → 'Reyes'
    'Roberto A. Abad'       → 'Abad'
    'Jose Abad Santos'      → 'Abad Santos'   (override)
    'Priscilla Baltazar-Padilla' → 'Baltazar-Padilla' (override)
    """
    if full_name in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[full_name]

    parts = full_name.strip().split()
    suffix_parts: list[str] = []
    while parts and parts[-1].rstrip(".").lower() in ("jr", "sr", "iii", "ii", "iv"):
        suffix_parts.insert(0, parts.pop())

    surname = parts[-1] if parts else full_name
    # Preserve hyphenated surnames
    if suffix_parts:
        sfx = " ".join(s.rstrip(".").capitalize() + "." for s in suffix_parts)
        return f"{surname}, {sfx}"
    return surname


# ---------------------------------------------------------------------------
# DissenterJoinParser — Rule #3: explicit joins/concurs with dissent
# ---------------------------------------------------------------------------

class DissenterJoinParser:
    """Parse votes_raw for explicit 'joins/concurs with dissent' relationships."""

    def __init__(self, matcher: JusticeMatcher):
        self.matcher = matcher
        # Verb phrases: joins / concurs in / concurs with / agrees with
        # followed by dissent / dissenting / separate opinion
        # "1 join" handles OCR artifact where I → 1
        self._verb_re = re.compile(
            r'(joins?|1 join|concurs? (?:in|with)|agrees? with)\s+'
            r'(?:the\s+)?'
            r'(?:dissent(?:ing)?|concurring and dissenting|separate)\s*'
            r'(?:opinion\s*)?'
            r'(?:of\s+)',
            re.IGNORECASE,
        )
        # Extract target justice after "of Justice X" / "of J. X" / "of X"
        self._target_re = re.compile(
            r"(?:(?:Mme\.\s*)?(?:Justice|J\.?)\s+)?"  # optional "Justice" / "J."
            r"([A-Z][A-Za-z\u00c0-\u00ff\-]+(?:,?\s*(?:Jr|Sr)\.?)?)",  # name capture
            re.IGNORECASE,
        )
        # Possessive form: "Justice Sarmientos' dissent" → target = Sarmientos
        self._possessive_re = re.compile(
            r"(?:(?:Justice|J\.?)\s+)?"
            r"([A-Z][A-Za-z\u00c0-\u00ff\-]+(?:,?\s*(?:Jr|Sr)\.?)?)"
            r"(?:['�\u2019]s?)\s+"
            r"(?:dissent|concurring and dissenting|separate)\s*(?:opinion)?",
            re.IGNORECASE,
        )

    def parse(self, votes_raw: str,
              case_date: str | None = None) -> list[tuple[str, str]]:
        """Return (joiner, target) pairs with names resolved via JusticeMatcher."""
        if not votes_raw:
            return []

        pairs = []
        # Split on sentence boundaries (period/semicolon followed by space + capital)
        sentences = re.split(r'(?<=[.;])\s+(?=[A-Z])', votes_raw)

        for sentence in sentences:
            # --- Strategy A: verb phrase + "of Justice X" ---
            for m in self._verb_re.finditer(sentence):
                after = sentence[m.end():]
                target_m = self._target_re.match(after)
                if not target_m:
                    continue
                target_raw = target_m.group(1).rstrip(".,")
                target_name, _ = self.matcher.match(target_raw,
                                                    case_date=case_date)
                if not target_name or target_name in EXCLUDE_NAMES:
                    continue

                # Extract joiner(s) from text before the verb
                before = sentence[:m.start()]
                joiners = self._extract_joiners(before, case_date)
                for j in joiners:
                    if j != target_name:
                        pairs.append((j, target_name))

            # --- Strategy B: possessive form "Justice X's dissent" ---
            for m in self._possessive_re.finditer(sentence):
                target_raw = m.group(1).rstrip(".,")
                target_name, _ = self.matcher.match(target_raw,
                                                    case_date=case_date)
                if not target_name or target_name in EXCLUDE_NAMES:
                    continue

                before = sentence[:m.start()]
                joiners = self._extract_joiners(before, case_date)
                for j in joiners:
                    if j != target_name:
                        pairs.append((j, target_name))

        return pairs

    def _extract_joiners(self, text: str,
                         case_date: str | None = None) -> list[str]:
        """Extract justice names from text preceding a join verb."""
        # Clean up: remove trailing commas, "JJ.", "J.", "C.J."
        text = text.strip().rstrip(",.")
        # Remove common prefixes/suffixes
        text = re.sub(r'\b(?:JJ|J|C\.?J)\.?,?\s*$', '', text, flags=re.IGNORECASE).strip()
        text = text.rstrip(",. ")

        # Split on comma / "and" to get individual names
        parts = re.split(r',\s*(?:and\s+)?|\s+and\s+', text)

        names = []
        for part in parts:
            part = part.strip()
            # Remove title suffixes
            part = re.sub(r',?\s*(?:JJ|J|C\.?J)\.?\s*$', '', part, flags=re.IGNORECASE).strip()
            part = part.rstrip(",. ")
            if not part or len(part) < 2:
                continue
            name, _ = self.matcher.match(part, case_date=case_date)
            if name and name not in EXCLUDE_NAMES:
                names.append(name)
        return names


# ---------------------------------------------------------------------------
# NetworkBuilder
# ---------------------------------------------------------------------------

class NetworkBuilder:
    """Build a justice co-voting network from predictions CSV."""

    def __init__(self, matcher: JusticeMatcher, min_confidence: float = 0.7):
        self.matcher = matcher
        self.min_confidence = min_confidence
        self.join_parser = DissenterJoinParser(matcher)
        self.G = nx.Graph()
        self.stats = {
            "total_rows": 0,
            "filtered_rows": 0,
            "per_curiam_cases": 0,
            "empty_ponente": 0,
            "skipped_low_confidence": 0,
            "skipped_volume_filter": 0,
            "majority_edges_added": 0,
            "dissent_edges_added": 0,
            "dissent_join_edges_added": 0,
        }
        self._case_counts: Counter = Counter()

    def build(
        self, csv_path: str, vol_min: int = None, vol_max: int = None,
        division_filter: list[str] | None = None,
        dissent_filter: str = "all",
    ) -> nx.Graph:
        """Build the network from a predictions CSV file.

        Args:
            csv_path: Path to predictions_extract.csv.
            vol_min: If set, skip rows with volume < vol_min.
            vol_max: If set, skip rows with volume > vol_max.
            division_filter: If set, only include cases whose division matches
                one of the given strings (case-insensitive substring match).
            dissent_filter: "all" (default), "unanimous" (no dissenters),
                or "with_dissent" (at least one dissenter).
        """
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.stats["total_rows"] = len(rows)
        self.stats["skipped_division_filter"] = 0
        self.stats["skipped_dissent_filter"] = 0

        for row in rows:
            # Volume range filtering
            if vol_min is not None or vol_max is not None:
                try:
                    vol = int(row.get("volume", 0))
                except (ValueError, TypeError):
                    self.stats["skipped_volume_filter"] += 1
                    continue
                if vol_min is not None and vol < vol_min:
                    self.stats["skipped_volume_filter"] += 1
                    continue
                if vol_max is not None and vol > vol_max:
                    self.stats["skipped_volume_filter"] += 1
                    continue

            # Division filtering
            if division_filter:
                row_div = (row.get("division") or "").upper()
                if not any(f.upper() in row_div for f in division_filter):
                    self.stats["skipped_division_filter"] += 1
                    continue

            # Dissent filtering
            if dissent_filter == "unanimous":
                if (row.get("dissenting") or "").strip():
                    self.stats["skipped_dissent_filter"] += 1
                    continue
            elif dissent_filter == "with_dissent":
                if not (row.get("dissenting") or "").strip():
                    self.stats["skipped_dissent_filter"] += 1
                    continue

            confidence = float(row.get("confidence", 0))
            if confidence < self.min_confidence:
                self.stats["skipped_low_confidence"] += 1
                continue
            self.stats["filtered_rows"] += 1
            self._process_case(row)

        # Set case_count and display_name as node attributes
        for node in self.G.nodes:
            self.G.nodes[node]["case_count"] = self._case_counts.get(node, 0)
            self.G.nodes[node]["display_name"] = extract_display_name(node)

        return self.G

    def _process_case(self, row: dict):
        """Process a single case row."""
        ponente = (row.get("ponente") or "").strip()
        concurring_raw = (row.get("concurring") or "").strip()
        dissenting_raw = (row.get("dissenting") or "").strip()
        votes_raw = (row.get("votes_raw") or "").strip()
        case_date = (row.get("date") or "").strip()

        # Parse concurring justices
        concurring = self._parse_names(concurring_raw)

        # Determine if PER CURIAM
        is_per_curiam = ponente in EXCLUDE_NAMES or not ponente

        if is_per_curiam:
            if not ponente or ponente in {"Per curiam", "PER CURIAM"}:
                self.stats["per_curiam_cases"] += 1
            if not ponente:
                self.stats["empty_ponente"] += 1

        # --- Rule 1: Majority bloc ---
        majority_bloc = list(concurring)
        if not is_per_curiam:
            majority_bloc.append(ponente)
            self._case_counts[ponente] += 1

        for name in concurring:
            self._case_counts[name] += 1

        for a, b in combinations(majority_bloc, 2):
            self._add_edge(a, b)
            self.stats["majority_edges_added"] += 1

        # --- Rule 2: Dissenting bloc ---
        dissenters = self._parse_names(dissenting_raw)
        for name in dissenters:
            self._case_counts[name] += 1

        if len(dissenters) >= 2:
            for a, b in combinations(dissenters, 2):
                self._add_edge(a, b)
                self.stats["dissent_edges_added"] += 1

        # --- Rule 3: Explicit joins ---
        join_pairs = self.join_parser.parse(votes_raw, case_date=case_date)
        for joiner, target in join_pairs:
            self._add_edge(joiner, target)
            self.stats["dissent_join_edges_added"] += 1

    def _parse_names(self, semicolon_str: str) -> list[str]:
        """Split semicolon-separated names, filtering exclusions."""
        if not semicolon_str:
            return []
        names = []
        for part in semicolon_str.split(";"):
            name = part.strip()
            if name and name not in EXCLUDE_NAMES:
                names.append(name)
        return names

    def _add_edge(self, a: str, b: str):
        """Add or increment an edge between two justices."""
        if a == b:
            return
        # Canonical ordering for consistency
        u, v = (a, b) if a < b else (b, a)
        if self.G.has_edge(u, v):
            self.G[u][v]["weight"] += 1
        else:
            self.G.add_edge(u, v, weight=1)


# ---------------------------------------------------------------------------
# Export functions
# ---------------------------------------------------------------------------

def export_edge_list(G: nx.Graph, path: str):
    """Export edge list as CSV sorted by weight descending."""
    edges = [(u, v, d["weight"]) for u, v, d in G.edges(data=True)]
    edges.sort(key=lambda x: (-x[2], x[0], x[1]))

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target", "weight"])
        for u, v, w in edges:
            writer.writerow([u, v, w])
    log.info("Edge list: %s (%d edges)", path, len(edges))


def export_adjacency_matrix(G: nx.Graph, path: str):
    """Export adjacency matrix as CSV with alphabetical node ordering."""
    nodes = sorted(G.nodes())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([""] + nodes)
        for u in nodes:
            row = [u]
            for v in nodes:
                if u == v:
                    row.append(0)
                elif G.has_edge(u, v):
                    row.append(G[u][v]["weight"])
                else:
                    row.append(0)
            writer.writerow(row)
    log.info("Adjacency matrix: %s (%dx%d)", path, len(nodes), len(nodes))


def export_graphml(G: nx.Graph, path: str):
    """Export graph in GraphML format for Gephi/igraph."""
    nx.write_graphml(G, path)
    log.info("GraphML: %s", path)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def print_statistics(G: nx.Graph, stats: dict):
    """Print network statistics to stdout."""
    print("\n" + "=" * 60)
    print("JUSTICE VOTING NETWORK — STATISTICS")
    print("=" * 60)

    print("\n--- Data Summary ---")
    print(f"  Total rows in CSV:         {stats['total_rows']:,}")
    print(f"  Rows after filtering:      {stats['filtered_rows']:,}")
    print(f"  Skipped (low confidence):  {stats['skipped_low_confidence']:,}")
    print(f"  PER CURIAM cases:          {stats['per_curiam_cases']:,}")
    print(f"  Empty ponente:             {stats['empty_ponente']:,}")

    print("\n--- Graph Metrics ---")
    print(f"  Nodes (justices):          {G.number_of_nodes()}")
    print(f"  Edges (co-voting pairs):   {G.number_of_edges()}")
    if G.number_of_nodes() > 1:
        print(f"  Density:                   {nx.density(G):.4f}")
    print(f"  Majority edges added:      {stats['majority_edges_added']:,}")
    print(f"  Dissent edges added:       {stats['dissent_edges_added']:,}")
    print(f"  Dissent-join edges added:  {stats['dissent_join_edges_added']:,}")

    # Top 20 pairs by co-voting weight
    edges = [(u, v, d["weight"]) for u, v, d in G.edges(data=True)]
    edges.sort(key=lambda x: -x[2])
    print("\n--- Top 20 Justice Pairs (by co-voting weight) ---")
    for i, (u, v, w) in enumerate(edges[:20], 1):
        print(f"  {i:2d}. {u:<25s} — {v:<25s}  weight={w}")

    # Top 10 by weighted degree
    w_deg = sorted(G.degree(weight="weight"), key=lambda x: -x[1])
    print("\n--- Top 10 Justices (by weighted degree) ---")
    for i, (node, deg) in enumerate(w_deg[:10], 1):
        print(f"  {i:2d}. {node:<25s}  weighted_degree={deg}")

    # Top 10 by case count
    case_counts = [(n, G.nodes[n].get("case_count", 0)) for n in G.nodes]
    case_counts.sort(key=lambda x: -x[1])
    print("\n--- Top 10 Justices (by case count) ---")
    for i, (node, cnt) in enumerate(case_counts[:10], 1):
        print(f"  {i:2d}. {node:<25s}  cases={cnt}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build justice co-voting network from predictions CSV."
    )
    parser.add_argument(
        "--csv", default=DEFAULT_CSV,
        help="Path to predictions_extract.csv (default: %(default)s)",
    )
    parser.add_argument(
        "--justices", default=DEFAULT_JUSTICES,
        help="Path to justices.json (default: %(default)s)",
    )
    parser.add_argument(
        "--min-confidence", type=float, default=0.7,
        help="Minimum confidence threshold (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help="Output directory (default: %(default)s)",
    )
    parser.add_argument(
        "--volume-range",
        help="Volume range filter as START-END (e.g. 226-500)",
    )
    args = parser.parse_args()

    # Resolve paths relative to repo root
    repo_root = Path(__file__).resolve().parent.parent
    csv_path = Path(args.csv) if Path(args.csv).is_absolute() else repo_root / args.csv
    justices_path = Path(args.justices) if Path(args.justices).is_absolute() else repo_root / args.justices
    output_dir = Path(args.output_dir) if Path(args.output_dir).is_absolute() else repo_root / args.output_dir

    if not csv_path.exists():
        log.error("CSV not found: %s", csv_path)
        sys.exit(1)
    if not justices_path.exists():
        log.error("justices.json not found: %s", justices_path)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse volume range
    vol_min = vol_max = None
    if args.volume_range:
        parts = args.volume_range.split("-")
        if len(parts) == 2:
            vol_min, vol_max = int(parts[0]), int(parts[1])
        else:
            log.error("Invalid --volume-range format. Expected START-END (e.g. 226-500)")
            sys.exit(1)

    # Build network
    matcher = JusticeMatcher(str(justices_path))
    builder = NetworkBuilder(matcher, min_confidence=args.min_confidence)
    G = builder.build(str(csv_path), vol_min=vol_min, vol_max=vol_max)

    # Export
    export_edge_list(G, str(output_dir / "edge_list.csv"))
    export_adjacency_matrix(G, str(output_dir / "adjacency_matrix.csv"))
    export_graphml(G, str(output_dir / "voting_network.graphml"))

    # Stats JSON
    stats_out = {**builder.stats, "nodes": G.number_of_nodes(), "edges": G.number_of_edges()}
    if G.number_of_nodes() > 1:
        stats_out["density"] = round(nx.density(G), 6)
    with open(output_dir / "network_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats_out, f, indent=2)
    log.info("Stats JSON: %s", output_dir / "network_stats.json")

    # Print to stdout
    print_statistics(G, builder.stats)


if __name__ == "__main__":
    main()
