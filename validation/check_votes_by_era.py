"""
Analyze votes changes between two CSV extractions, broken down by era.

Reports:
  - Cases gained/lost votes (net flow)
  - Missing votes by era (ERA-1 vs ERA-2 vs ERA-3+)
  - Lost-votes classification by old text length

Usage:
    python validation/check_votes_by_era.py <before.csv> <after.csv>
    python validation/check_votes_by_era.py  # uses defaults
"""
import argparse
import csv
from collections import defaultdict


ERA_RANGES = [
    ("ERA-1 (121-260)", 121, 260),
    ("ERA-2 (261-500)", 261, 500),
    ("ERA-3 (501-660)", 501, 660),
    ("ERA-4 (661-850)", 661, 850),
    ("ERA-5 (851-999)", 851, 999),
]


def era_label(vol):
    v = int(vol)
    for name, lo, hi in ERA_RANGES:
        if lo <= v <= hi:
            return name
    return f"Other ({vol})"


def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(description="Votes change breakdown by era.")
    parser.add_argument("before", nargs="?", default="predictions_extract.csv")
    parser.add_argument("after", nargs="?", default="predictions_extract_fixed.csv")
    args = parser.parse_args()

    old = load_csv(args.before)
    new = load_csv(args.after)

    old_map = {(r["volume"], r["case_number"]): r for r in old}
    new_map = {(r["volume"], r["case_number"]): r for r in new}

    # --- Gained / Lost ---
    gained = [
        (k, len(new_map[k]["votes_raw"]))
        for k in new_map
        if k in old_map
        and not old_map[k]["votes_raw"].strip()
        and new_map[k]["votes_raw"].strip()
    ]
    lost = [
        (k, len(old_map[k]["votes_raw"]))
        for k in old_map
        if old_map[k]["votes_raw"].strip()
        and k in new_map
        and not new_map[k]["votes_raw"].strip()
    ]

    print("=" * 65)
    print("VOTES CHANGE BREAKDOWN")
    print("=" * 65)
    print(f"Cases that GAINED votes: {len(gained)}")
    print(f"Cases that LOST votes:   {len(lost)}")
    print(f"Net change:              {len(gained) - len(lost):+d}")
    print()

    # --- Per-era missing ---
    era_stats = defaultdict(lambda: {"old_missing": 0, "new_missing": 0, "total": 0})
    for r in old:
        era = era_label(r["volume"])
        era_stats[era]["total"] += 1
        if not r["votes_raw"].strip():
            era_stats[era]["old_missing"] += 1
    for r in new:
        era = era_label(r["volume"])
        if not r["votes_raw"].strip():
            era_stats[era]["new_missing"] += 1

    print("MISSING VOTES BY ERA:")
    header = f"{'Era':<20} {'Before':>8} {'After':>8} {'Delta':>8} {'Total':>8} {'Bef%':>7} {'Aft%':>7}"
    print(header)
    print("-" * len(header))
    for era_name, _, _ in ERA_RANGES:
        s = era_stats.get(era_name)
        if not s or not s["total"]:
            continue
        pct_b = 100 * s["old_missing"] / s["total"]
        pct_a = 100 * s["new_missing"] / s["total"]
        d = s["new_missing"] - s["old_missing"]
        print(
            f"{era_name:<20} {s['old_missing']:>8} {s['new_missing']:>8} "
            f"{d:>+8} {s['total']:>8} {pct_b:>6.1f}% {pct_a:>6.1f}%"
        )

    # --- Lost-votes classification by old text length ---
    print()
    for era_name, lo, hi in ERA_RANGES:
        era_lost = [
            vlen
            for (vol, _cn), vlen in lost
            if lo <= int(vol) <= hi
        ]
        if not era_lost:
            continue
        short = sum(1 for x in era_lost if x < 25)
        medium = sum(1 for x in era_lost if 25 <= x < 100)
        long_ = sum(1 for x in era_lost if x >= 100)
        print(f"{era_name} lost votes by old text length ({len(era_lost)} total):")
        print(f"  < 25 chars  (likely ponente misclass): {short}")
        print(f"  25-99 chars (borderline):              {medium}")
        print(f"  >= 100 chars (real votes):             {long_}")


if __name__ == "__main__":
    main()
