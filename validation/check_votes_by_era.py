"""
Analyze extraction quality by era, with optional before/after comparison.

Modes:
  Single CSV:  Reports per-era metrics for all key fields (cases, ponente,
               votes, confidence) across all eras.
  Two CSVs:    Also reports gained/lost votes and delta columns.

Usage:
    python validation/check_votes_by_era.py predictions_extract.csv
    python validation/check_votes_by_era.py <before.csv> <after.csv>
    python validation/check_votes_by_era.py --html predictions_extract.csv
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


def _has(row, field):
    return bool(row.get(field, "").strip())


def compute_era_metrics(rows):
    """Compute per-era metrics. Returns (era_rows_dict, era_metrics_list, totals_dict)."""
    era_data = defaultdict(list)
    for r in rows:
        era_data[era_label(r["volume"])].append(r)

    era_metrics = []
    totals = {"cases": 0, "vols": 0, "ponente": 0, "votes": 0, "date": 0,
              "miss_pon": 0, "miss_vot": 0, "miss_dat": 0,
              "conf_sum": 0.0, "low_conf": 0}

    for era_name, _, _ in ERA_RANGES:
        era_rows = era_data.get(era_name, [])
        if not era_rows:
            continue

        n = len(era_rows)
        vols = len(set(r["volume"] for r in era_rows))
        pon = sum(1 for r in era_rows if _has(r, "ponente"))
        vot = sum(1 for r in era_rows if _has(r, "votes_raw"))
        dat = sum(1 for r in era_rows if _has(r, "date"))
        miss_pon = n - pon
        miss_vot = n - vot
        miss_dat = n - dat
        confs = [float(r["confidence"]) for r in era_rows if r.get("confidence", "").strip()]
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        low = sum(1 for c in confs if c < 0.65)

        m = {
            "era": era_name, "cases": n, "vols": vols,
            "ponente": pon, "miss_pon": miss_pon,
            "votes": vot, "miss_vot": miss_vot,
            "date": dat, "miss_dat": miss_dat,
            "avg_conf": avg_conf, "low_conf": low,
        }
        era_metrics.append(m)

        for k in ["cases", "vols", "ponente", "votes", "date",
                   "miss_pon", "miss_vot", "miss_dat", "low_conf"]:
            totals[k] += m[k]
        totals["conf_sum"] += sum(confs)

    n = totals["cases"] or 1
    totals["avg_conf"] = totals["conf_sum"] / n
    return era_data, era_metrics, totals


def _red_text(val):
    """Return val as red-colored string for plain text (no-op, just str)."""
    return str(val)


def report_single(rows):
    """Per-era metrics for a single CSV (plain text)."""
    era_data, era_metrics, totals = compute_era_metrics(rows)

    print("=" * 99)
    print("EXTRACTION METRICS BY ERA")
    print("=" * 99)

    header = (
        f"{'Era':<20} {'Cases':>6} {'Vols':>5} "
        f"{'Ponente':>8} {'Miss':>6} {'Votes':>8} {'Miss':>6} {'Date':>8} {'Miss':>6} "
        f"{'Avg Conf':>9} {'Low Conf':>9}"
    )
    print(header)
    print("-" * 99)

    for m in era_metrics:
        n = m["cases"]
        print(
            f"{m['era']:<20} {n:>6} {m['vols']:>5} "
            f"{m['ponente']:>5} {100*m['ponente']/n:>2.0f}% {m['miss_pon']:>6} "
            f"{m['votes']:>5} {100*m['votes']/n:>2.0f}% {m['miss_vot']:>6} "
            f"{m['date']:>5} {100*m['date']/n:>2.0f}% {m['miss_dat']:>6} "
            f"{m['avg_conf']:>8.3f} {m['low_conf']:>5} {100*m['low_conf']/n:>2.0f}%"
        )

    t = totals
    n = t["cases"] or 1
    print("-" * 99)
    print(
        f"{'TOTAL':<20} {t['cases']:>6} {t['vols']:>5} "
        f"{t['ponente']:>5} {100*t['ponente']/n:>2.0f}% {t['miss_pon']:>6} "
        f"{t['votes']:>5} {100*t['votes']/n:>2.0f}% {t['miss_vot']:>6} "
        f"{t['date']:>5} {100*t['date']/n:>2.0f}% {t['miss_dat']:>6} "
        f"{t['avg_conf']:>8.3f} {t['low_conf']:>5} {100*t['low_conf']/n:>2.0f}%"
    )

    # --- Missing fields detail ---
    print()
    print("MISSING FIELDS DETAIL:")
    for era_name, lo, hi in ERA_RANGES:
        era_rows = era_data.get(era_name, [])
        if not era_rows:
            continue
        missing_pon = [(r["volume"], r["case_number"]) for r in era_rows if not _has(r, "ponente")]
        missing_vot = [(r["volume"], r["case_number"]) for r in era_rows if not _has(r, "votes_raw")]
        if not missing_pon and not missing_vot:
            continue
        print(f"\n  {era_name}:")
        if missing_pon:
            print(f"    Missing ponente ({len(missing_pon)}):", end="")
            if len(missing_pon) <= 10:
                for vol, cn in missing_pon:
                    print(f" Vol{vol}/{cn}", end="")
            else:
                for vol, cn in missing_pon[:5]:
                    print(f" Vol{vol}/{cn}", end="")
                print(f" ... +{len(missing_pon)-5} more", end="")
            print()
        if missing_vot:
            print(f"    Missing votes ({len(missing_vot)}):", end="")
            if len(missing_vot) <= 10:
                for vol, cn in missing_vot:
                    print(f" Vol{vol}/{cn}", end="")
            else:
                for vol, cn in missing_vot[:5]:
                    print(f" Vol{vol}/{cn}", end="")
                print(f" ... +{len(missing_vot)-5} more", end="")
            print()

    return era_data


def report_single_html(rows):
    """Per-era metrics as an HTML table with red missing counts."""
    _, era_metrics, totals = compute_era_metrics(rows)

    def red_cell(val):
        if val:
            return f'<span style="color:red;font-weight:bold">{val}</span>'
        return str(val)

    lines = []
    lines.append('<table style="border-collapse:collapse;font-family:monospace;font-size:14px">')
    lines.append('<thead><tr style="border-bottom:2px solid #666">')
    for h in ["Era", "Cases", "Vols", "Ponente", "Miss", "Votes", "Miss", "Date", "Miss", "Avg Conf", "Low Conf"]:
        align = "left" if h == "Era" else "right"
        lines.append(f'<th style="padding:4px 10px;text-align:{align}">{h}</th>')
    lines.append('</tr></thead><tbody>')

    def _row_html(m, is_total=False):
        n = m["cases"] or 1
        tag = "th" if is_total else "td"
        style = 'style="padding:3px 10px;text-align:right"'
        style_l = 'style="padding:3px 10px;text-align:left;white-space:nowrap"'
        if is_total:
            style = 'style="padding:3px 10px;text-align:right;border-top:2px solid #666;font-weight:bold"'
            style_l = 'style="padding:3px 10px;text-align:left;border-top:2px solid #666;font-weight:bold;white-space:nowrap"'
        era = m.get("era", "TOTAL")
        cells = [
            f'<{tag} {style_l}>{era}</{tag}>',
            f'<{tag} {style}>{m["cases"]}</{tag}>',
            f'<{tag} {style}>{m["vols"]}</{tag}>',
            f'<{tag} {style}>{m["ponente"]} ({100*m["ponente"]/n:.0f}%)</{tag}>',
            f'<{tag} {style}>{red_cell(m["miss_pon"])}</{tag}>',
            f'<{tag} {style}>{m["votes"]} ({100*m["votes"]/n:.0f}%)</{tag}>',
            f'<{tag} {style}>{red_cell(m["miss_vot"])}</{tag}>',
            f'<{tag} {style}>{m["date"]} ({100*m["date"]/n:.0f}%)</{tag}>',
            f'<{tag} {style}>{red_cell(m["miss_dat"])}</{tag}>',
            f'<{tag} {style}>{m["avg_conf"]:.3f}</{tag}>',
            f'<{tag} {style}>{m["low_conf"]} ({100*m["low_conf"]/n:.0f}%)</{tag}>',
        ]
        return "<tr>" + "".join(cells) + "</tr>"

    for m in era_metrics:
        lines.append(_row_html(m))

    totals["era"] = "TOTAL"
    lines.append(_row_html(totals, is_total=True))

    lines.append('</tbody></table>')
    return "\n".join(lines)


def report_comparison(old, new):
    """Before/after comparison (plain text)."""
    old_map = {(r["volume"], r["case_number"]): r for r in old}
    new_map = {(r["volume"], r["case_number"]): r for r in new}

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

    print()
    print("=" * 65)
    print("VOTES CHANGE BREAKDOWN (before -> after)")
    print("=" * 65)
    print(f"Cases that GAINED votes: {len(gained)}")
    print(f"Cases that LOST votes:   {len(lost)}")
    print(f"Net change:              {len(gained) - len(lost):+d}")
    print()

    era_stats = defaultdict(lambda: {"old_missing": 0, "new_missing": 0,
                                     "old_total": 0, "new_total": 0})
    for r in old:
        era = era_label(r["volume"])
        era_stats[era]["old_total"] += 1
        if not r["votes_raw"].strip():
            era_stats[era]["old_missing"] += 1
    for r in new:
        era = era_label(r["volume"])
        era_stats[era]["new_total"] += 1
        if not r["votes_raw"].strip():
            era_stats[era]["new_missing"] += 1

    print("MISSING VOTES BY ERA:")
    header = f"{'Era':<20} {'Before':>8} {'After':>8} {'Delta':>8} {'Total':>8} {'Bef%':>7} {'Aft%':>7}"
    print(header)
    print("-" * len(header))
    for era_name, _, _ in ERA_RANGES:
        s = era_stats.get(era_name)
        if not s or not s["old_total"]:
            continue
        pct_b = 100 * s["old_missing"] / s["old_total"]
        pct_a = 100 * s["new_missing"] / s["new_total"] if s["new_total"] else 0
        d = s["new_missing"] - s["old_missing"]
        print(
            f"{era_name:<20} {s['old_missing']:>8} {s['new_missing']:>8} "
            f"{d:>+8} {s['old_total']:>8} {pct_b:>6.1f}% {pct_a:>6.1f}%"
        )

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


def main():
    parser = argparse.ArgumentParser(description="Extraction quality by era, with optional comparison.")
    parser.add_argument("csv_files", nargs="*", default=["predictions_extract.csv"],
                        help="One CSV for metrics, or two CSVs for before/after comparison")
    parser.add_argument("--html", action="store_true",
                        help="Output HTML table (for Streamlit)")
    args = parser.parse_args()

    if len(args.csv_files) == 1:
        rows = load_csv(args.csv_files[0])
        if args.html:
            print(report_single_html(rows))
        else:
            report_single(rows)
    elif len(args.csv_files) == 2:
        old = load_csv(args.csv_files[0])
        new = load_csv(args.csv_files[1])
        if args.html:
            print(report_single_html(new))
        else:
            report_single(new)
        report_comparison(old, new)
    else:
        parser.error("Provide 1 CSV (metrics) or 2 CSVs (before/after comparison)")


if __name__ == "__main__":
    main()
