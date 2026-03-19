"""
Compare headline metrics between two CSV extractions.

Usage:
    python validation/check_headlines.py <before.csv> <after.csv>
    python validation/check_headlines.py  # defaults: predictions_extract.csv vs predictions_extract_fixed.csv
"""
import argparse
import csv
import sys


def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def compute_metrics(rows):
    total = len(rows)
    return {
        "total": total,
        "no_case_number": sum(1 for r in rows if not r["case_number"].strip()),
        "no_ponente": sum(1 for r in rows if not r["ponente"].strip()),
        "no_votes": sum(1 for r in rows if not r["votes_raw"].strip()),
        "overflow_1k": sum(1 for r in rows if len(r["votes_raw"]) > 1000),
        "overflow_5k": sum(1 for r in rows if len(r["votes_raw"]) > 5000),
    }


def main():
    parser = argparse.ArgumentParser(description="Compare headline CSV metrics.")
    parser.add_argument("before", nargs="?", default="predictions_extract.csv")
    parser.add_argument("after", nargs="?", default="predictions_extract_fixed.csv")
    args = parser.parse_args()

    old = load_csv(args.before)
    new = load_csv(args.after)
    m_old = compute_metrics(old)
    m_new = compute_metrics(new)

    labels = [
        ("Total cases", "total"),
        ("No case_number", "no_case_number"),
        ("No ponente", "no_ponente"),
        ("No votes", "no_votes"),
        ("Votes overflow >1k", "overflow_1k"),
        ("Votes overflow >5k", "overflow_5k"),
    ]

    print("=" * 65)
    print(f"HEADLINE COMPARISON: {args.before} vs {args.after}")
    print("=" * 65)
    print(f"{'Metric':<25} {'Before':>10} {'After':>10} {'Delta':>10}")
    print("-" * 65)

    for name, key in labels:
        b, a = m_old[key], m_new[key]
        d = a - b
        sign = "+" if d > 0 else ""
        print(f"{name:<25} {b:>10,} {a:>10,} {sign}{d:>9,}")

    print()
    print("DEFECT RATES (% of total):")
    for name, key in labels[2:]:
        pct_b = 100 * m_old[key] / m_old["total"] if m_old["total"] else 0
        pct_a = 100 * m_new[key] / m_new["total"] if m_new["total"] else 0
        print(f"  {name:<25} {pct_b:>6.1f}%  ->  {pct_a:>6.1f}%")


if __name__ == "__main__":
    main()
