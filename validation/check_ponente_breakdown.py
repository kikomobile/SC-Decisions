"""
Analyze ponente changes between two CSV extractions.

Reports:
  - Cases that lost/gained ponente
  - Per-volume regression breakdown
  - Root cause analysis (doc_type presence in JSON)

Usage:
    python validation/check_ponente_breakdown.py <before.csv> <after.csv>
    python validation/check_ponente_breakdown.py  # uses defaults
"""
import argparse
import csv
import json
import os
from collections import defaultdict


def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(description="Ponente change breakdown.")
    parser.add_argument("before", nargs="?", default="predictions_extract.csv")
    parser.add_argument("after", nargs="?", default="predictions_extract_fixed.csv")
    parser.add_argument(
        "--json-dir",
        default=os.path.join("downloads", "predictions"),
        help="Dir with predicted JSONs for root cause check",
    )
    parser.add_argument(
        "--root-cause-sample",
        type=int,
        default=50,
        help="Max cases to check for doc_type presence (default 50)",
    )
    args = parser.parse_args()

    old = load_csv(args.before)
    new = load_csv(args.after)

    old_map = {(r["volume"], r["case_number"]): r["ponente"] for r in old}
    new_map = {(r["volume"], r["case_number"]): r["ponente"] for r in new}

    # --- Lost / Gained ---
    lost = [
        (k, old_map[k])
        for k in old_map
        if old_map[k].strip() and k in new_map and not new_map[k].strip()
    ]
    gained = [
        (k, new_map[k])
        for k in new_map
        if k in old_map and not old_map[k].strip() and new_map[k].strip()
    ]

    print("=" * 65)
    print("PONENTE CHANGE BREAKDOWN")
    print("=" * 65)
    print(f"Cases that LOST ponente:   {len(lost)}")
    print(f"Cases that GAINED ponente: {len(gained)}")
    print(f"Net change:                {len(gained) - len(lost):+d}")
    print()

    # --- Per-volume ---
    def no_ponente_by_vol(rows):
        counts = defaultdict(lambda: [0, 0])
        for r in rows:
            vol = int(r["volume"])
            counts[vol][1] += 1
            if not r["ponente"].strip():
                counts[vol][0] += 1
        return counts

    old_c = no_ponente_by_vol(old)
    new_c = no_ponente_by_vol(new)
    all_vols = sorted(set(old_c) | set(new_c))

    worse = []
    better = []
    for vol in all_vols:
        old_np = old_c.get(vol, [0, 0])[0]
        new_np = new_c.get(vol, [0, 0])[0]
        tot = new_c.get(vol, old_c.get(vol, [0, 0]))[1]
        d = new_np - old_np
        if d > 0:
            worse.append((vol, old_np, new_np, d, tot))
        elif d < 0:
            better.append((vol, old_np, new_np, d, tot))

    print(
        f"Volumes with MORE missing ponente "
        f"({len(worse)} vols, net +{sum(d for *_, d, _ in worse)}):"
    )
    for vol, onp, nnp, d, tot in sorted(worse, key=lambda x: -x[3])[:20]:
        print(f"  Vol {vol:>3}: {onp:>2} -> {nnp:>2}  (+{d})  out of {tot}")
    if len(worse) > 20:
        print(f"  ... and {len(worse) - 20} more")

    print(
        f"\nVolumes with FEWER missing ponente "
        f"({len(better)} vols, net {sum(d for *_, d, _ in better)}):"
    )
    for vol, onp, nnp, d, tot in sorted(better, key=lambda x: x[3])[:20]:
        print(f"  Vol {vol:>3}: {onp:>2} -> {nnp:>2}  ({d})  out of {tot}")
    if len(better) > 20:
        print(f"  ... and {len(better) - 20} more")

    # --- Root cause: doc_type presence ---
    if not os.path.isdir(args.json_dir):
        print(f"\nSkipping root cause check — {args.json_dir} not found")
        return

    print(f"\nROOT CAUSE: doc_type presence for lost-ponente cases (sample={args.root_cause_sample})")
    has_dt, no_dt, sampled = 0, 0, 0
    for (vol, cn), old_p in sorted(lost)[: args.root_cause_sample]:
        jpath = os.path.join(args.json_dir, f"Volume_{vol}_predicted.json")
        if not os.path.exists(jpath):
            continue
        with open(jpath, encoding="utf-8") as f:
            data = json.load(f)
        for case in data["volumes"][0]["cases"]:
            cn_anns = [a for a in case["annotations"] if a["label"] == "case_number"]
            if cn_anns and cn_anns[0]["text"] == cn:
                dt = [a for a in case["annotations"] if a["label"] == "doc_type"]
                if dt:
                    has_dt += 1
                else:
                    no_dt += 1
                sampled += 1
                break
    print(f"  {sampled} cases checked: {has_dt} have doc_type, {no_dt} missing doc_type")
    if no_dt > sampled * 0.8:
        print(
            "  -> Most lost cases lack doc_type. Likely lost LLM-fallback "
            "ponentes from a prior --skip-llm=false run."
        )


if __name__ == "__main__":
    main()
