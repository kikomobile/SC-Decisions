"""
List all votes overflow cases (>1000 chars) in a CSV extraction.

Usage:
    python validation/check_overflow.py <csv_file>
    python validation/check_overflow.py  # defaults to predictions_extract_fixed.csv
"""
import argparse
import csv
from collections import Counter


def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(description="List votes overflow cases.")
    parser.add_argument("csv_file", nargs="?", default="predictions_extract_fixed.csv")
    parser.add_argument(
        "--threshold", type=int, default=1000, help="Char threshold (default 1000)"
    )
    args = parser.parse_args()

    rows = load_csv(args.csv_file)
    overflow = [
        r for r in rows if len(r["votes_raw"]) > args.threshold
    ]

    total = len(rows)
    print("=" * 65)
    print(f"OVERFLOW CHECK: {args.csv_file} (threshold={args.threshold})")
    print("=" * 65)
    print(f"Total cases: {total:,}")
    print(f"Overflow cases: {len(overflow)}")
    print()

    if not overflow:
        print("No overflow cases found.")
        return

    # Sort by descending length
    overflow.sort(key=lambda r: -len(r["votes_raw"]))

    print(f"{'Vol':<6} {'Case Number':<40} {'Chars':>8}")
    print("-" * 58)
    for r in overflow:
        cn = r["case_number"][:38]
        print(f"{r['volume']:<6} {cn:<40} {len(r['votes_raw']):>8,}")

    # Per-volume summary
    vol_counts = Counter(r["volume"] for r in overflow)
    print(f"\nBy volume ({len(vol_counts)} volumes):")
    for vol, cnt in sorted(vol_counts.items(), key=lambda x: int(x[0])):
        print(f"  Vol {vol}: {cnt}")


if __name__ == "__main__":
    main()
