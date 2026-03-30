"""Temporal voting analysis for the Philippine Supreme Court justice network.

Computes sliding-window metrics that normalize for temporal co-service and
isolate genuine deviations from expected voting patterns.

Metrics:
    1. Dissent rate timeline — per-justice dissent rate over sliding windows
    2. Dissent affinity — who dissents together, who dissents against whom
    3. Bloc deviation — cross-appointment-bloc voting deviations
    4. Temporal drift — how a justice's alignment shifts over time
    5. Agreement vs expected — observed agreement minus independence-model expectation
"""

import csv
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path

import networkx as nx
import pandas as pd

from .appointed_by import (
    PRESIDENT_COLORS,
    FALLBACK_COLOR,
    build_appointed_by_map,
    load_justices_csv,
    resolve_appointed_by,
)
from .build_network import extract_display_name

EXCLUDE_NAMES = {"LLM_TEST_MARKER", "Per curiam", "PER CURIAM", ""}

# Volume-to-year linear interpolation anchors for fallback date estimation
_VOL_DATE_ANCHORS = [(226, 1986), (500, 2005), (700, 2014), (961, 2024)]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CaseRecord:
    volume: int
    case_number: str
    division: str
    date: date
    ponente: str
    majority: list[str]
    dissenters: list[str]
    no_part: list[str]
    on_leave: list[str]


@dataclass
class JusticeTenure:
    name: str
    tenure_start: date | None
    tenure_end: date | None  # None = incumbent
    appointed_by: str


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_DATE_REGEX = re.compile(r'([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})')

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date_core(text: str) -> date | None:
    """Parse a clean date string like 'May 23, 1986' or 'June 15 1901'."""
    parts = re.split(r'[\s,]+', text)
    parts = [p for p in parts if p]
    if len(parts) >= 3:
        month_str = parts[0].lower().rstrip(".")
        month = _MONTH_MAP.get(month_str)
        try:
            day = int(parts[1])
            year = int(parts[2])
            if month and 1 <= day <= 31 and 1800 <= year <= 2100:
                return date(year, month, min(day, 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31))
        except (ValueError, IndexError):
            pass
    return None


def _parse_date(text: str) -> date | None:
    """Parse a date string, with fallback regex extraction from garbage."""
    if not text or not text.strip():
        return None
    text = text.strip().rstrip(".")

    # Try direct parse first
    result = _parse_date_core(text)
    if result:
        return result

    # Fallback: extract date substring from surrounding garbage
    m = _DATE_REGEX.search(text)
    if m:
        return _parse_date_core(m.group(1))

    return None


def _estimate_date_from_volume(vol: int) -> date:
    """Estimate a case date from its volume number via linear interpolation."""
    for i in range(len(_VOL_DATE_ANCHORS) - 1):
        v0, y0 = _VOL_DATE_ANCHORS[i]
        v1, y1 = _VOL_DATE_ANCHORS[i + 1]
        if vol <= v1:
            frac = (vol - v0) / max(v1 - v0, 1)
            year = y0 + frac * (y1 - y0)
            return date(int(year), 6, 15)  # mid-year estimate
    # Beyond last anchor
    return date(2024, 6, 15)


# ---------------------------------------------------------------------------
# Division normalization
# ---------------------------------------------------------------------------

def _normalize_division(raw: str) -> str:
    """Normalize OCR division typos to canonical values."""
    raw = raw.upper().strip()
    if not raw:
        return ""
    if "BANC" in raw:
        return "EN BANC"
    if "FIRST" in raw or "FIRS" in raw or "1ST" in raw:
        return "FIRST DIVISION"
    if "SECOND" in raw or "SECON" in raw or "2ND" in raw:
        return "SECOND DIVISION"
    if "THIRD" in raw or "THIR" in raw or "3RD" in raw:
        return "THIRD DIVISION"
    if "SPECIAL" in raw:
        return "SPECIAL DIVISION"
    return raw


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _split_names(semicolon_str: str) -> list[str]:
    """Split semicolon-separated names, filtering exclusions."""
    if not semicolon_str or not semicolon_str.strip():
        return []
    return [
        n.strip() for n in semicolon_str.split(";")
        if n.strip() and n.strip() not in EXCLUDE_NAMES
    ]


def load_cases(
    csv_path: str | Path,
    min_confidence: float = 0.0,
    en_banc_only: bool = False,
) -> list[CaseRecord]:
    """Load and parse cases from predictions_extract.csv.

    Args:
        csv_path: Path to predictions_extract.csv.
        min_confidence: Skip cases below this confidence.
        en_banc_only: If True, only include EN BANC cases.

    Returns:
        List of CaseRecord sorted by date.
    """
    csv_path = Path(csv_path)
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    cases = []
    for row in rows:
        # Confidence filter
        try:
            conf = float(row.get("confidence") or 0)
        except ValueError:
            conf = 0
        if conf < min_confidence:
            continue

        # Division
        division = _normalize_division(row.get("division") or "")
        if en_banc_only and division != "EN BANC":
            continue

        # Date
        case_date = _parse_date(row.get("date") or "")
        if case_date is None:
            try:
                vol = int(row.get("volume") or 0)
            except ValueError:
                continue
            case_date = _estimate_date_from_volume(vol)

        # Volume
        try:
            volume = int(row.get("volume") or 0)
        except ValueError:
            volume = 0

        # Names
        ponente = (row.get("ponente") or "").strip()
        concurring = _split_names(row.get("concurring") or "")
        dissenters = _split_names(row.get("dissenting") or "")
        no_part = _split_names(row.get("no_part") or "")
        on_leave = _split_names(row.get("on_leave") or "")

        # Build majority list
        majority = list(concurring)
        if ponente and ponente not in EXCLUDE_NAMES:
            majority.append(ponente)

        case_number = (row.get("case_number") or "").strip()
        if not case_number:
            continue

        cases.append(CaseRecord(
            volume=volume,
            case_number=case_number,
            division=division,
            date=case_date,
            ponente=ponente if ponente not in EXCLUDE_NAMES else "",
            majority=majority,
            dissenters=dissenters,
            no_part=no_part,
            on_leave=on_leave,
        ))

    cases.sort(key=lambda c: c.date)
    return cases


def load_tenures(justices_csv_path: str | Path) -> dict[str, JusticeTenure]:
    """Load justice tenure data from ph_sc_justices.csv.

    Returns:
        {justice_name: JusticeTenure} using the longer-tenured position
        for justices with dual entries.
    """
    rows = load_justices_csv(justices_csv_path)
    name_to_president = resolve_appointed_by(rows)

    tenures = {}
    for r in rows:
        name = r["Name"]
        start = _parse_date(r.get("Tenure Start", ""))
        end_str = (r.get("Tenure End") or "").strip()
        end = None if end_str.lower() == "incumbent" else _parse_date(end_str)
        president = name_to_president.get(name, r.get("Appointed By", "Unknown"))

        # For dual entries (e.g. Associate Justice → Chief Justice),
        # merge by taking earliest start and latest end to span full service.
        if name in tenures:
            existing = tenures[name]
            merged_start = min(
                s for s in (existing.tenure_start, start) if s is not None
            ) if (existing.tenure_start or start) else None
            # None means incumbent — always the latest possible end
            if existing.tenure_end is None or end is None:
                merged_end = None
            else:
                merged_end = max(existing.tenure_end, end)
            tenures[name] = JusticeTenure(
                name=name,
                tenure_start=merged_start,
                tenure_end=merged_end,
                appointed_by=existing.appointed_by,
            )
            continue

        tenures[name] = JusticeTenure(
            name=name,
            tenure_start=start,
            tenure_end=end,
            appointed_by=president,
        )

    return tenures


# ---------------------------------------------------------------------------
# TemporalAnalyzer
# ---------------------------------------------------------------------------

class TemporalAnalyzer:
    """Compute temporal voting metrics from case records."""

    def __init__(
        self,
        cases: list[CaseRecord],
        tenures: dict[str, JusticeTenure],
        treat_no_part_as_dissent: bool = False,
    ):
        self.tenures = tenures

        # Optionally reclassify no_part as dissent
        if treat_no_part_as_dissent:
            self.cases = []
            for c in cases:
                self.cases.append(CaseRecord(
                    volume=c.volume,
                    case_number=c.case_number,
                    division=c.division,
                    date=c.date,
                    ponente=c.ponente,
                    majority=c.majority,
                    dissenters=c.dissenters + c.no_part,
                    no_part=[],
                    on_leave=c.on_leave,
                ))
        else:
            self.cases = cases

        # Build appointed_by lookup
        self._appointed_by: dict[str, str] = {}
        for name, t in tenures.items():
            self._appointed_by[name] = t.appointed_by

        # Build participation index: {justice: [(case_idx, role), ...]}
        self._participation: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for i, c in enumerate(self.cases):
            for name in c.majority:
                self._participation[name].append((i, "majority"))
            for name in c.dissenters:
                self._participation[name].append((i, "dissent"))
            for name in c.no_part:
                self._participation[name].append((i, "no_part"))
            for name in c.on_leave:
                self._participation[name].append((i, "on_leave"))

        # All justice names that appear in the data
        self.all_justices = sorted(self._participation.keys())

        # Date range
        if self.cases:
            self._date_min = self.cases[0].date
            self._date_max = self.cases[-1].date
        else:
            self._date_min = date(1986, 1, 1)
            self._date_max = date(2024, 12, 31)

    def _generate_windows(
        self, window_years: int, step_months: int,
    ) -> list[tuple[date, date, date]]:
        """Generate sliding window boundaries.

        Returns:
            [(window_start, window_end, window_center), ...]
        """
        window_days = int(window_years * 365.25)
        step_days = int(step_months * 30.44)
        windows = []
        start = self._date_min
        while start + timedelta(days=window_days) <= self._date_max + timedelta(days=step_days):
            end = start + timedelta(days=window_days)
            center = start + timedelta(days=window_days // 2)
            windows.append((start, end, center))
            start += timedelta(days=step_days)
        return windows

    def _cases_in_window(
        self, window_start: date, window_end: date,
    ) -> list[int]:
        """Return indices of cases within the given date window."""
        # Binary search could be faster but N is small enough
        return [
            i for i, c in enumerate(self.cases)
            if window_start <= c.date < window_end
        ]

    def _justice_role_in_case(self, justice: str, case_idx: int) -> str | None:
        """Return the role of a justice in a given case, or None."""
        c = self.cases[case_idx]
        if justice in c.majority:
            return "majority"
        if justice in c.dissenters:
            return "dissent"
        if justice in c.no_part:
            return "no_part"
        if justice in c.on_leave:
            return "on_leave"
        return None

    # --- Metric 1: Dissent Rate Timeline ---

    def dissent_rate_timeline(
        self, window_years: int = 3, step_months: int = 6,
    ) -> pd.DataFrame:
        """Per-justice dissent rate over sliding time windows."""
        windows = self._generate_windows(window_years, step_months)
        rows = []

        for w_start, w_end, w_center in windows:
            case_idxs = self._cases_in_window(w_start, w_end)
            if not case_idxs:
                continue

            # Count per-justice participation and dissents in this window
            justice_participated: Counter = Counter()
            justice_dissented: Counter = Counter()

            for idx in case_idxs:
                c = self.cases[idx]
                for name in c.majority:
                    justice_participated[name] += 1
                for name in c.dissenters:
                    justice_participated[name] += 1
                    justice_dissented[name] += 1

            for justice, participated in justice_participated.items():
                dissented = justice_dissented.get(justice, 0)
                rate = dissented / participated if participated > 0 else 0
                rows.append({
                    "window_center": w_center,
                    "justice": justice,
                    "cases_participated": participated,
                    "dissent_count": dissented,
                    "dissent_rate": round(rate, 4),
                    "appointed_by": self._appointed_by.get(justice, "Unknown"),
                })

        return pd.DataFrame(rows)

    # --- Metric 2: Dissent Affinity ---

    def dissent_affinity(self, min_dissents: int = 5) -> pd.DataFrame:
        """Pairwise co-dissent affinity between justices.

        Returns DataFrame with co-dissent counts and rates for pairs
        where both justices have >= min_dissents.
        """
        # Count total dissents per justice
        dissent_counts: Counter = Counter()
        # Track which cases each justice dissented in
        dissent_cases: dict[str, set[int]] = defaultdict(set)

        for i, c in enumerate(self.cases):
            for name in c.dissenters:
                dissent_counts[name] += 1
                dissent_cases[name].add(i)

        # Filter to justices with enough dissents
        eligible = [j for j, cnt in dissent_counts.items() if cnt >= min_dissents]
        eligible.sort()

        rows = []
        for a, b in combinations(eligible, 2):
            co = len(dissent_cases[a] & dissent_cases[b])
            denom = min(dissent_counts[a], dissent_counts[b])
            rate = co / denom if denom > 0 else 0
            rows.append({
                "justice_a": a,
                "justice_b": b,
                "co_dissent_count": co,
                "co_dissent_rate": round(rate, 4),
                "dissents_a": dissent_counts[a],
                "dissents_b": dissent_counts[b],
                "appointed_by_a": self._appointed_by.get(a, "Unknown"),
                "appointed_by_b": self._appointed_by.get(b, "Unknown"),
            })

        return pd.DataFrame(rows)

    def dissent_against(self, min_dissents: int = 5) -> pd.DataFrame:
        """Who dissents when whom is ponente/majority.

        Returns DataFrame: (dissenter, target, count, rate).
        'target' is a justice who was in the majority when 'dissenter' dissented.
        """
        dissent_counts: Counter = Counter()
        against_counts: Counter = Counter()  # (dissenter, target) -> count

        for c in self.cases:
            for d in c.dissenters:
                dissent_counts[d] += 1
                for m in c.majority:
                    against_counts[(d, m)] += 1

        eligible = {j for j, cnt in dissent_counts.items() if cnt >= min_dissents}

        rows = []
        for (d, m), cnt in against_counts.items():
            if d not in eligible:
                continue
            rate = cnt / dissent_counts[d] if dissent_counts[d] > 0 else 0
            rows.append({
                "dissenter": d,
                "target": m,
                "dissent_against_count": cnt,
                "dissent_against_rate": round(rate, 4),
                "total_dissents": dissent_counts[d],
                "appointed_by_dissenter": self._appointed_by.get(d, "Unknown"),
                "appointed_by_target": self._appointed_by.get(m, "Unknown"),
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("dissent_against_count", ascending=False)
        return df

    # --- Metric 3: Bloc Deviation ---

    def bloc_deviation(
        self, window_years: int = 3, step_months: int = 6,
    ) -> pd.DataFrame:
        """Per-justice deviation from their appointment bloc's majority position."""
        windows = self._generate_windows(window_years, step_months)
        rows = []

        for w_start, w_end, w_center in windows:
            case_idxs = self._cases_in_window(w_start, w_end)
            if not case_idxs:
                continue

            # Per-justice stats in this window
            justice_cases: Counter = Counter()
            justice_with_bloc: Counter = Counter()
            justice_against_bloc: Counter = Counter()

            for idx in case_idxs:
                c = self.cases[idx]
                all_participants = set(c.majority) | set(c.dissenters)

                # Group participants by appointing president
                bloc_votes: dict[str, dict[str, int]] = defaultdict(lambda: {"majority": 0, "dissent": 0})
                for name in c.majority:
                    pres = self._appointed_by.get(name, "Unknown")
                    bloc_votes[pres]["majority"] += 1
                for name in c.dissenters:
                    pres = self._appointed_by.get(name, "Unknown")
                    bloc_votes[pres]["dissent"] += 1

                # For each participant, check if they voted with their bloc
                for name in all_participants:
                    pres = self._appointed_by.get(name, "Unknown")
                    bv = bloc_votes.get(pres, {"majority": 0, "dissent": 0})
                    bloc_majority_position = "majority" if bv["majority"] >= bv["dissent"] else "dissent"

                    justice_role = "majority" if name in c.majority else "dissent"
                    justice_cases[name] += 1
                    if justice_role == bloc_majority_position:
                        justice_with_bloc[name] += 1
                    else:
                        justice_against_bloc[name] += 1

            for justice in justice_cases:
                total = justice_cases[justice]
                with_bloc = justice_with_bloc.get(justice, 0)
                against_bloc = justice_against_bloc.get(justice, 0)
                bloc_rate = with_bloc / total if total > 0 else 1.0
                deviation = against_bloc / total if total > 0 else 0.0
                rows.append({
                    "window_center": w_center,
                    "justice": justice,
                    "appointed_by": self._appointed_by.get(justice, "Unknown"),
                    "cases_in_window": total,
                    "with_bloc": with_bloc,
                    "against_bloc": against_bloc,
                    "bloc_agreement_rate": round(bloc_rate, 4),
                    "deviation_score": round(deviation, 4),
                })

        return pd.DataFrame(rows)

    # --- Metric 4: Temporal Drift ---

    def temporal_drift(
        self, window_years: int = 3, step_months: int = 6,
    ) -> pd.DataFrame:
        """Track per-justice alignment with own bloc and overall court over time."""
        windows = self._generate_windows(window_years, step_months)
        rows = []

        for w_start, w_end, w_center in windows:
            case_idxs = self._cases_in_window(w_start, w_end)
            if not case_idxs:
                continue

            # Per-justice: how often they agree with majority, with own bloc
            justice_total: Counter = Counter()
            justice_with_majority: Counter = Counter()
            justice_dissents: Counter = Counter()
            justice_with_own_bloc: Counter = Counter()

            for idx in case_idxs:
                c = self.cases[idx]
                all_participants = set(c.majority) | set(c.dissenters)

                # Bloc majority position for this case
                bloc_positions: dict[str, str] = {}
                bloc_votes: dict[str, dict[str, int]] = defaultdict(lambda: {"majority": 0, "dissent": 0})
                for name in c.majority:
                    bloc_votes[self._appointed_by.get(name, "Unknown")]["majority"] += 1
                for name in c.dissenters:
                    bloc_votes[self._appointed_by.get(name, "Unknown")]["dissent"] += 1
                for pres, bv in bloc_votes.items():
                    bloc_positions[pres] = "majority" if bv["majority"] >= bv["dissent"] else "dissent"

                for name in all_participants:
                    justice_total[name] += 1
                    role = "majority" if name in c.majority else "dissent"
                    if role == "majority":
                        justice_with_majority[name] += 1
                    else:
                        justice_dissents[name] += 1

                    pres = self._appointed_by.get(name, "Unknown")
                    if role == bloc_positions.get(pres, "majority"):
                        justice_with_own_bloc[name] += 1

            for justice in justice_total:
                total = justice_total[justice]
                if total == 0:
                    continue
                rows.append({
                    "window_center": w_center,
                    "justice": justice,
                    "appointed_by": self._appointed_by.get(justice, "Unknown"),
                    "cases_in_window": total,
                    "alignment_with_court": round(
                        justice_with_majority.get(justice, 0) / total, 4),
                    "alignment_with_own_bloc": round(
                        justice_with_own_bloc.get(justice, 0) / total, 4),
                    "dissent_rate": round(
                        justice_dissents.get(justice, 0) / total, 4),
                })

        return pd.DataFrame(rows)

    # --- Metric 5: Agreement vs Expected ---

    def agreement_normalized(self, min_shared_cases: int = 20) -> pd.DataFrame:
        """Observed vs expected agreement for justice pairs.

        Expected agreement under independence:
            E(agree) = 1 - (d_A + d_B - d_A * d_B)
        where d_A, d_B are overall dissent rates.

        Affinity score = observed - expected.
        Positive = unusual allies, negative = unusual friction.
        """
        # Build per-justice case sets and roles
        justice_majority_cases: dict[str, set[int]] = defaultdict(set)
        justice_dissent_cases: dict[str, set[int]] = defaultdict(set)
        justice_all_cases: dict[str, set[int]] = defaultdict(set)

        for i, c in enumerate(self.cases):
            for name in c.majority:
                justice_majority_cases[name].add(i)
                justice_all_cases[name].add(i)
            for name in c.dissenters:
                justice_dissent_cases[name].add(i)
                justice_all_cases[name].add(i)

        # Overall dissent rates
        dissent_rate = {}
        for j in justice_all_cases:
            total = len(justice_all_cases[j])
            dissent_rate[j] = len(justice_dissent_cases[j]) / total if total > 0 else 0

        # Pairwise
        justices = sorted(justice_all_cases.keys())
        rows = []
        for a, b in combinations(justices, 2):
            shared = justice_all_cases[a] & justice_all_cases[b]
            if len(shared) < min_shared_cases:
                continue

            # Count agreements (both majority or both dissent)
            agreements = 0
            for idx in shared:
                a_majority = idx in justice_majority_cases[a]
                b_majority = idx in justice_majority_cases[b]
                if a_majority == b_majority:
                    agreements += 1

            observed = agreements / len(shared)
            d_a, d_b = dissent_rate[a], dissent_rate[b]
            expected = 1 - (d_a + d_b - d_a * d_b)
            affinity = observed - expected

            same_bloc = (self._appointed_by.get(a, "") == self._appointed_by.get(b, "")
                         and self._appointed_by.get(a, "") != "Unknown")

            rows.append({
                "justice_a": a,
                "justice_b": b,
                "cases_both_participated": len(shared),
                "agreements": agreements,
                "observed_agreement": round(observed, 4),
                "expected_agreement": round(expected, 4),
                "affinity_score": round(affinity, 4),
                "same_bloc": same_bloc,
                "appointed_by_a": self._appointed_by.get(a, "Unknown"),
                "appointed_by_b": self._appointed_by.get(b, "Unknown"),
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("affinity_score")
        return df

    # --- Summary stats ---

    def summary(self) -> dict:
        """Return summary statistics about the loaded data."""
        total = len(self.cases)
        with_dissent = sum(1 for c in self.cases if c.dissenters)
        with_no_part = sum(1 for c in self.cases if c.no_part)
        en_banc = sum(1 for c in self.cases if c.division == "EN BANC")

        return {
            "total_cases": total,
            "cases_with_dissent": with_dissent,
            "cases_with_no_part": with_no_part,
            "en_banc_cases": en_banc,
            "date_range": f"{self._date_min} to {self._date_max}",
            "unique_justices": len(self.all_justices),
        }


# ---------------------------------------------------------------------------
# Temporal Community Detection Network
# ---------------------------------------------------------------------------

@dataclass
class WindowSnapshot:
    """A single time-window snapshot of the co-voting network."""

    step: int
    window_start: date
    window_end: date
    window_center: date
    graph: nx.Graph
    communities: list[set[str]]
    community_ids: list[int]
    positions: dict[str, tuple[float, float]]
    node_community: dict[str, int]
    cases_in_window: int
    dissent_count: int
    active_justices: int
    transitions: dict  # {"entered": list[str], "exited": list[str]}
    stability: float | None  # mean Jaccard vs previous step, None for step 0


class TemporalNetwork:
    """Build sliding-window co-voting networks with tracked communities."""

    def __init__(
        self,
        cases: list[CaseRecord],
        tenures: dict[str, JusticeTenure],
        justices_csv_path: str | Path | None = None,
        treat_no_part_as_dissent: bool = False,
    ):
        self.tenures = tenures

        # Optionally reclassify no_part as dissent
        if treat_no_part_as_dissent:
            self.cases = []
            for c in cases:
                self.cases.append(CaseRecord(
                    volume=c.volume,
                    case_number=c.case_number,
                    division=c.division,
                    date=c.date,
                    ponente=c.ponente,
                    majority=c.majority,
                    dissenters=c.dissenters + c.no_part,
                    no_part=[],
                    on_leave=c.on_leave,
                ))
        else:
            self.cases = cases

        # Build appointed_by using the same multi-strategy name matcher
        # that the Graph View uses (exact → alias → token → surname).
        all_names: set[str] = set()
        for c in self.cases:
            all_names.update(c.majority)
            all_names.update(c.dissenters)
            all_names.update(c.no_part)
            all_names.update(c.on_leave)
        all_names.discard("")

        if justices_csv_path:
            self._appointed_by = build_appointed_by_map(
                list(all_names), justices_csv_path,
            )
        else:
            # Fallback: direct tenure lookup (less accurate)
            self._appointed_by: dict[str, str] = {}
            for name, t in tenures.items():
                self._appointed_by[name] = t.appointed_by

        # Build case-name → JusticeTenure lookup for tenure validation.
        # Maps each case name to its matched tenure record (by president match).
        self._tenure_lookup: dict[str, JusticeTenure] = {}
        # Direct match first
        for name in all_names:
            if name in tenures:
                self._tenure_lookup[name] = tenures[name]
                continue
            # Match via appointed_by: find the tenure whose president matches
            pres = self._appointed_by.get(name)
            if pres:
                for t_name, t in tenures.items():
                    if t.appointed_by == pres and self._name_match(name, t_name):
                        self._tenure_lookup[name] = t
                        break

        if self.cases:
            self._date_min = self.cases[0].date
            self._date_max = self.cases[-1].date
        else:
            self._date_min = date(1986, 1, 1)
            self._date_max = date(2024, 12, 31)

        self._next_community_id = 0

    @staticmethod
    def _name_match(case_name: str, csv_name: str) -> bool:
        """Check if a case name plausibly matches a CSV name (surname match)."""
        case_tokens = case_name.upper().replace(",", "").replace(".", "").split()
        csv_tokens = csv_name.upper().replace(",", "").replace(".", "").split()
        if not case_tokens or not csv_tokens:
            return False
        # Strip suffixes for comparison
        suffixes = {"JR", "SR", "II", "III", "IV"}
        case_core = [t for t in case_tokens if t not in suffixes]
        csv_core = [t for t in csv_tokens if t not in suffixes]
        if not case_core or not csv_core:
            return False
        # Last substantive token (surname) must match
        return case_core[-1] == csv_core[-1]

    # -- Window generation (same logic as TemporalAnalyzer) --

    def _generate_windows(
        self, window_years: int, step_months: int,
    ) -> list[tuple[date, date, date]]:
        window_days = int(window_years * 365.25)
        step_days = int(step_months * 30.44)
        windows: list[tuple[date, date, date]] = []
        start = self._date_min
        while start + timedelta(days=window_days) <= self._date_max + timedelta(days=step_days):
            end = start + timedelta(days=window_days)
            center = start + timedelta(days=window_days // 2)
            windows.append((start, end, center))
            start += timedelta(days=step_days)
        return windows

    # -- Build co-voting graph for a single window --

    def _is_valid_in_window(self, name: str, w_start: date, w_end: date) -> bool:
        """Check if a justice's tenure overlaps with the window dates.

        Filters out OCR misidentifications (e.g. a 2009-appointed justice
        appearing in 1986 cases).
        """
        tenure = self._tenure_lookup.get(name)
        if tenure is None:
            return True  # unknown tenure — keep (could be valid unlisted justice)
        t_start = tenure.tenure_start or date.min
        t_end = tenure.tenure_end or date.max
        # Tenure must overlap with window (with 1-year grace for edge cases)
        grace = timedelta(days=365)
        return t_start <= w_end + grace and t_end >= w_start - grace

    def _build_window_graph(
        self, window_cases: list[CaseRecord],
        w_start: date, w_end: date,
        dissent_only: bool = False,
    ) -> nx.Graph:
        G = nx.Graph()
        case_counts: Counter = Counter()

        for c in window_cases:
            if not dissent_only:
                # Rule 1: Majority co-voting
                majority = [
                    n for n in c.majority
                    if n and n not in EXCLUDE_NAMES
                    and self._is_valid_in_window(n, w_start, w_end)
                ]
                for name in majority:
                    case_counts[name] += 1
                for a, b in combinations(majority, 2):
                    if G.has_edge(a, b):
                        G[a][b]["weight"] += 1
                    else:
                        G.add_edge(a, b, weight=1)

            # Rule 2: Dissenter co-voting
            dissenters = [
                n for n in c.dissenters
                if n and n not in EXCLUDE_NAMES
                and self._is_valid_in_window(n, w_start, w_end)
            ]
            for name in dissenters:
                case_counts[name] += 1
            if len(dissenters) >= 2:
                for a, b in combinations(dissenters, 2):
                    if G.has_edge(a, b):
                        G[a][b]["weight"] += 1
                    else:
                        G.add_edge(a, b, weight=1)

        # Set node attributes
        for node in G.nodes():
            G.nodes[node]["case_count"] = case_counts.get(node, 0)
            G.nodes[node]["display_name"] = extract_display_name(node)
            G.nodes[node]["appointed_by"] = self._appointed_by.get(node, "Unknown")

        return G

    # -- Community tracking across steps --

    def _track_communities(
        self,
        prev_communities: list[set[str]] | None,
        prev_ids: list[int] | None,
        new_communities: list[set[str]],
    ) -> list[int]:
        if prev_communities is None or prev_ids is None:
            # First step — assign fresh sequential IDs
            ids = list(range(self._next_community_id, self._next_community_id + len(new_communities)))
            self._next_community_id += len(new_communities)
            return ids

        # Compute Jaccard similarities between all (new, prev) pairs
        similarities = []
        for ni, nc in enumerate(new_communities):
            for pi, pc in enumerate(prev_communities):
                union = len(nc | pc)
                if union > 0:
                    jaccard = len(nc & pc) / union
                    similarities.append((jaccard, ni, prev_ids[pi]))

        # Greedy assignment: highest Jaccard first
        similarities.sort(reverse=True)
        assigned_new: set[int] = set()
        assigned_prev_id: set[int] = set()
        result = [None] * len(new_communities)

        for jaccard, ni, pid in similarities:
            if jaccard <= 0:
                break
            if ni not in assigned_new and pid not in assigned_prev_id:
                result[ni] = pid
                assigned_new.add(ni)
                assigned_prev_id.add(pid)

        # Assign fresh IDs to unmatched communities
        for i in range(len(result)):
            if result[i] is None:
                result[i] = self._next_community_id
                self._next_community_id += 1

        return result

    # -- Community stability metric --

    @staticmethod
    def _compute_stability(
        prev_node_community: dict[str, int] | None,
        curr_node_community: dict[str, int],
    ) -> float | None:
        if prev_node_community is None:
            return None

        shared = set(prev_node_community.keys()) & set(curr_node_community.keys())
        if len(shared) < 2:
            return None

        # Group shared justices by community in both steps
        prev_groups: dict[int, set[str]] = defaultdict(set)
        curr_groups: dict[int, set[str]] = defaultdict(set)
        for name in shared:
            prev_groups[prev_node_community[name]].add(name)
            curr_groups[curr_node_community[name]].add(name)

        # Mean Jaccard across current communities (restricted to shared justices)
        jaccards = []
        for cid, curr_members in curr_groups.items():
            # Find best-matching prev community for these members
            best_j = 0.0
            for pid, prev_members in prev_groups.items():
                union = len(curr_members | prev_members)
                if union > 0:
                    j = len(curr_members & prev_members) / union
                    best_j = max(best_j, j)
            jaccards.append(best_j)

        return sum(jaccards) / len(jaccards) if jaccards else None

    # -- Layout with seeding from previous step --

    @staticmethod
    def _seed_layout(
        graph: nx.Graph,
        communities: list[set[str]],
        prev_positions: dict[str, tuple[float, float]] | None,
    ) -> dict[str, tuple[float, float]]:
        N = graph.number_of_nodes()
        if N == 0:
            return {}
        if N == 1:
            return {list(graph.nodes())[0]: (0.0, 0.0)}

        k = 2.0 / math.sqrt(N)

        if prev_positions is None:
            return nx.spring_layout(
                graph, k=k, iterations=100, seed=42, weight="weight",
            )

        # Seed: reuse previous positions for existing nodes (pinned)
        seeded: dict[str, tuple[float, float]] = {}
        fixed_nodes = []
        for node in graph.nodes():
            if node in prev_positions:
                seeded[node] = prev_positions[node]
                fixed_nodes.append(node)

        # Place new nodes near their community centroid
        import random
        rng = random.Random(42)
        for comm in communities:
            existing_in_comm = [n for n in comm if n in prev_positions]
            new_in_comm = [n for n in comm if n not in prev_positions and n in graph.nodes()]
            if not new_in_comm:
                continue
            if existing_in_comm:
                cx = sum(prev_positions[n][0] for n in existing_in_comm) / len(existing_in_comm)
                cy = sum(prev_positions[n][1] for n in existing_in_comm) / len(existing_in_comm)
            else:
                cx, cy = 0.0, 0.0
            for node in new_in_comm:
                seeded[node] = (cx + rng.uniform(-0.15, 0.15), cy + rng.uniform(-0.15, 0.15))

        # Pin existing nodes — only run spring layout to settle new nodes
        if fixed_nodes:
            return nx.spring_layout(
                graph, pos=seeded, fixed=fixed_nodes,
                k=k, iterations=30, seed=42, weight="weight",
            )
        return nx.spring_layout(
            graph, pos=seeded, k=k, iterations=50, seed=42, weight="weight",
        )

    # -- Main computation --

    def compute_snapshots(
        self, window_years: int, step_months: int,
        dissent_only: bool = False,
    ) -> list[WindowSnapshot]:
        windows = self._generate_windows(window_years, step_months)
        snapshots: list[WindowSnapshot] = []

        prev_nodes: set[str] = set()
        prev_communities: list[set[str]] | None = None
        prev_ids: list[int] | None = None
        prev_positions: dict[str, tuple[float, float]] | None = None
        prev_node_community: dict[str, int] | None = None

        step_idx = 0
        for w_start, w_end, w_center in windows:
            window_cases = [
                c for c in self.cases
                if w_start <= c.date < w_end
            ]
            if not window_cases:
                continue

            G = self._build_window_graph(window_cases, w_start, w_end, dissent_only)
            if G.number_of_nodes() == 0:
                continue

            # Community detection
            if G.number_of_nodes() < 2 or G.number_of_edges() == 0:
                communities = [set(G.nodes())]
            else:
                communities = list(
                    nx.community.louvain_communities(G, weight="weight", seed=42)
                )

            # Track communities
            community_ids = self._track_communities(prev_communities, prev_ids, communities)

            # Build node→community mapping
            node_community: dict[str, int] = {}
            for comm, cid in zip(communities, community_ids):
                for name in comm:
                    node_community[name] = cid

            # Stability
            stability = self._compute_stability(prev_node_community, node_community)

            # Layout
            positions = self._seed_layout(G, communities, prev_positions)

            # Transitions
            curr_nodes = set(G.nodes())
            entered = sorted(curr_nodes - prev_nodes)
            exited = sorted(prev_nodes - curr_nodes)

            # Stats
            dissent_count = sum(1 for c in window_cases if c.dissenters)

            snapshots.append(WindowSnapshot(
                step=step_idx,
                window_start=w_start,
                window_end=w_end,
                window_center=w_center,
                graph=G,
                communities=communities,
                community_ids=community_ids,
                positions=positions,
                node_community=node_community,
                cases_in_window=len(window_cases),
                dissent_count=dissent_count,
                active_justices=G.number_of_nodes(),
                transitions={"entered": entered, "exited": exited},
                stability=stability,
            ))

            # Update prev state
            prev_nodes = curr_nodes
            prev_communities = communities
            prev_ids = community_ids
            prev_positions = positions
            prev_node_community = node_community
            step_idx += 1

        return snapshots


def compute_global_bounds(
    snapshots: list[WindowSnapshot], padding: float = 0.1,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Compute global (x_range, y_range) across all snapshots.

    Returns fixed axis bounds so the viewport stays stable during playback.
    """
    all_x, all_y = [], []
    for snap in snapshots:
        for x, y in snap.positions.values():
            all_x.append(x)
            all_y.append(y)
    if not all_x:
        return ((-1, 1), (-1, 1))
    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)
    x_pad = (x_max - x_min) * padding or 0.5
    y_pad = (y_max - y_min) * padding or 0.5
    return ((x_min - x_pad, x_max + x_pad), (y_min - y_pad, y_max + y_pad))


def _convex_hull_2d(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew's monotone chain convex hull for 2-D points."""
    pts = sorted(points, key=lambda p: (float(p[0]), float(p[1])))
    if len(pts) <= 2:
        return pts

    def cross(O, A, B):
        return (A[0] - O[0]) * (B[1] - O[1]) - (A[1] - O[1]) * (B[0] - O[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


_PRESIDENT_ORDER = [
    "Ferdinand Marcos", "Corazon Aquino", "Fidel V. Ramos",
    "Joseph Estrada", "Gloria Macapagal Arroyo",
    "Benigno Aquino III", "Rodrigo Duterte", "Bongbong Marcos",
]


def build_temporal_network_plotly(
    snapshot: WindowSnapshot,
    edge_threshold: int = 0,
    community_colors: list[str] | None = None,
    axis_range: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> "go.Figure":
    """Build a Plotly figure styled like Graph View community clusters.

    Nodes colored by appointing president, community boundaries drawn as
    dashed convex hulls.
    """
    import plotly.graph_objects as go

    if community_colors is None:
        from .visualize import COMMUNITY_COLORS
        community_colors = COMMUNITY_COLORS

    pos = snapshot.positions
    G = snapshot.graph

    traces = []

    # -- Community boundary hulls (drawn first, behind everything) --
    comm_members_pos: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for name, cid in snapshot.node_community.items():
        if name in pos:
            comm_members_pos[cid].append(pos[name])

    for cid, pts in comm_members_pos.items():
        hull_color = community_colors[cid % len(community_colors)]
        if len(pts) < 3:
            continue
        hull = _convex_hull_2d(pts)
        # Expand hull outward from centroid for padding
        cx = sum(p[0] for p in hull) / len(hull)
        cy = sum(p[1] for p in hull) / len(hull)
        pad = 0.04
        expanded = []
        for hx, hy in hull:
            dx, dy = hx - cx, hy - cy
            dist = math.sqrt(dx * dx + dy * dy) or 1
            expanded.append((hx + dx / dist * pad, hy + dy / dist * pad))
        # Close the polygon
        hx_list = [p[0] for p in expanded] + [expanded[0][0]]
        hy_list = [p[1] for p in expanded] + [expanded[0][1]]
        # Filled area
        traces.append(go.Scatter(
            x=hx_list, y=hy_list,
            mode="lines",
            fill="toself",
            fillcolor=_hex_to_rgba(hull_color, 0.08),
            line=dict(width=1.5, color=_hex_to_rgba(hull_color, 0.45), dash="dash"),
            hoverinfo="skip",
            showlegend=False,
        ))
        # Community label at centroid
        traces.append(go.Scatter(
            x=[cx], y=[cy],
            mode="text",
            text=[f"C{cid}"],
            textfont=dict(size=9, color=_hex_to_rgba(hull_color, 0.5)),
            hoverinfo="skip",
            showlegend=False,
        ))

    # -- Edge traces --
    max_weight = max((d["weight"] for _, _, d in G.edges(data=True)), default=1)
    edge_x, edge_y = [], []
    for u, v, d in G.edges(data=True):
        if d["weight"] < edge_threshold:
            continue
        if u in pos and v in pos:
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])

    traces.append(go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=0.8, color="rgba(150,150,170,0.25)"),
        hoverinfo="skip",
        showlegend=False,
    ))

    # -- Node traces (one per appointing president for legend) --
    max_cases = max((G.nodes[n].get("case_count", 1) for n in G.nodes()), default=1)

    pres_members: dict[str, list[str]] = defaultdict(list)
    for name in G.nodes():
        if name in pos:
            pres = G.nodes[name].get("appointed_by", "Unknown")
            pres_members[pres].append(name)

    # Sort presidents chronologically
    pres_order = [p for p in _PRESIDENT_ORDER if p in pres_members]
    for p in sorted(pres_members.keys()):
        if p not in pres_order:
            pres_order.append(p)

    for pres in pres_order:
        members = pres_members[pres]
        color = PRESIDENT_COLORS.get(pres, FALLBACK_COLOR)
        xs, ys, texts, customdata, sizes = [], [], [], [], []
        for name in members:
            x, y = pos[name]
            xs.append(x)
            ys.append(y)
            display = G.nodes[name].get("display_name", name)
            texts.append(display)
            cc = G.nodes[name].get("case_count", 0)
            cid = snapshot.node_community.get(name, "?")
            customdata.append([name, pres, cid, cc])
            size = 18 + 22 * (cc / max_cases) if max_cases > 0 else 22
            sizes.append(size)

        traces.append(go.Scatter(
            x=xs, y=ys,
            mode="markers+text",
            marker=dict(
                size=sizes,
                color=color,
                line=dict(width=2, color="#222"),
            ),
            text=texts,
            textposition="top center",
            textfont=dict(size=11, color="#eee", family="Arial"),
            customdata=customdata,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Appointed by: %{customdata[1]}<br>"
                "Community: %{customdata[2]}<br>"
                "Cases in window: %{customdata[3]}"
                "<extra></extra>"
            ),
            name=pres,
            legendgroup=pres,
        ))

    # -- Figure layout --
    title = (
        f"{snapshot.window_start.strftime('%b %Y')} — "
        f"{snapshot.window_end.strftime('%b %Y')}  "
        f"({snapshot.active_justices} justices, "
        f"{snapshot.cases_in_window} cases)"
    )

    x_axis = dict(showgrid=False, zeroline=False, showticklabels=False, visible=False)
    y_axis = dict(showgrid=False, zeroline=False, showticklabels=False, visible=False)
    if axis_range is not None:
        x_axis["range"] = list(axis_range[0])
        y_axis["range"] = list(axis_range[1])

    fig = go.Figure(
        data=traces,
        layout=go.Layout(
            title=dict(
                text=title,
                font=dict(size=15, color="#eee", family="Arial"),
                x=0.5, xanchor="center",
            ),
            template="plotly_dark",
            plot_bgcolor="#111111",
            paper_bgcolor="#111111",
            showlegend=True,
            legend=dict(
                font=dict(size=13, color="#ddd", family="Arial"),
                bgcolor="rgba(17,17,17,0.85)",
                bordercolor="#444",
                borderwidth=1,
                itemsizing="constant",
                tracegroupgap=2,
            ),
            height=600,
            xaxis=x_axis,
            yaxis=y_axis,
            margin=dict(l=5, r=5, t=45, b=5),
            hovermode="closest",
        ),
    )

    return fig


def build_tenure_timeline_plotly(
    snapshot: WindowSnapshot,
    tenures: dict[str, JusticeTenure],
    appointed_by_map: dict[str, str],
) -> "go.Figure":
    """Build a horizontal bar chart showing justice tenures for a window.

    X-axis = years, Y-axis = justices ordered by tenure start (earliest at top).
    Bars colored by appointing president. Current window highlighted with
    a vertical shaded band.
    """
    import plotly.graph_objects as go
    from datetime import date as _date

    G = snapshot.graph
    justices = list(G.nodes())
    if not justices:
        fig = go.Figure()
        fig.update_layout(template="plotly_dark", height=300)
        return fig

    # Resolve tenure and president for each justice in the window
    entries = []
    for name in justices:
        tenure = None
        # Try direct match, then fuzzy via _tenure_lookup pattern
        if name in tenures:
            tenure = tenures[name]
        else:
            # Match by surname
            name_upper = name.upper().split()
            surname = name_upper[-1] if name_upper else ""
            for t_name, t in tenures.items():
                if surname and surname in t_name.upper().split():
                    tenure = t
                    break

        t_start = tenure.tenure_start if tenure and tenure.tenure_start else None
        t_end = tenure.tenure_end if tenure and tenure.tenure_end else None

        pres = appointed_by_map.get(name, G.nodes[name].get("appointed_by", "Unknown"))
        display = G.nodes[name].get("display_name", name)

        entries.append({
            "name": name,
            "display": display,
            "start": t_start or snapshot.window_start,
            "end": t_end or _date.today(),
            "president": pres,
        })

    # Sort by tenure start (earliest at top → reversed for plotly y-axis)
    entries.sort(key=lambda e: e["start"])

    # Build traces grouped by president for legend.
    # Use one thick scatter-line per justice (reliable with date x-axis).
    pres_groups: dict[str, list] = {}
    for i, e in enumerate(entries):
        pres_groups.setdefault(e["president"], []).append((i, e))

    pres_order = [p for p in _PRESIDENT_ORDER if p in pres_groups]
    for p in sorted(pres_groups.keys()):
        if p not in pres_order:
            pres_order.append(p)

    y_labels = [e["display"] for e in entries]
    bar_height = 8  # line width in px

    traces = []
    for pres in pres_order:
        color = PRESIDENT_COLORS.get(pres, FALLBACK_COLOR)
        group = pres_groups[pres]
        first = True
        for _, e in group:
            traces.append(go.Scatter(
                x=[e["start"], e["end"]],
                y=[e["display"], e["display"]],
                mode="lines",
                line=dict(color=color, width=bar_height),
                name=pres,
                legendgroup=pres,
                showlegend=first,
                hovertemplate=(
                    f"<b>{e['name']}</b><br>"
                    f"Appointed by: {pres}<br>"
                    f"Tenure: {e['start'].strftime('%b %Y')} — "
                    f"{e['end'].strftime('%b %Y')}"
                    "<extra></extra>"
                ),
            ))
            first = False

    # Window highlight band
    w_start = snapshot.window_start.isoformat()
    w_end = snapshot.window_end.isoformat()

    fig = go.Figure(data=traces)

    fig.add_vrect(
        x0=w_start, x1=w_end,
        fillcolor="rgba(255,255,255,0.07)",
        line=dict(color="rgba(255,255,255,0.3)", width=1, dash="dash"),
        annotation_text="window",
        annotation_position="top left",
        annotation_font=dict(size=10, color="rgba(255,255,255,0.5)"),
    )

    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="#111111",
        paper_bgcolor="#111111",
        height=max(250, len(entries) * 28 + 80),
        xaxis=dict(
            type="date",
            title="Year",
            title_font=dict(size=12, color="#aaa"),
            tickfont=dict(size=11, color="#aaa"),
            gridcolor="rgba(255,255,255,0.06)",
        ),
        yaxis=dict(
            categoryorder="array",
            categoryarray=y_labels,
            tickfont=dict(size=11, color="#ddd"),
        ),
        legend=dict(
            font=dict(size=12, color="#ddd"),
            bgcolor="rgba(17,17,17,0.85)",
            bordercolor="#444",
            borderwidth=1,
            tracegroupgap=2,
        ),
        margin=dict(l=5, r=5, t=10, b=30),
        showlegend=True,
    )

    return fig
