"""
Extract case_number, date, ponente, votes from predicted JSON files into a CSV.
Uses fuzzy matching against justices.json for clean justice name resolution.

Thin wrapper around regex_improve/detection/csv_extractor.py.

Usage:
    python extract_predictions_csv.py
    python extract_predictions_csv.py --output my_output.csv
    python extract_predictions_csv.py --no-archive
"""

import argparse
import os
import sys

# Add regex_improve to path so we can import from the detection package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "regex_improve"))

from detection.csv_extractor import write_predictions_csv


def main():
    parser = argparse.ArgumentParser(
        description="Extract predictions to CSV for Excel."
    )
    parser.add_argument(
        "--input-dir",
        default=os.path.join("downloads", "predictions"),
        help="Directory containing *_predicted.json files",
    )
    parser.add_argument(
        "--output",
        default="predictions_extract.csv",
        help="Output CSV file path (default: predictions_extract.csv)",
    )
    parser.add_argument(
        "--justices",
        default=os.path.join("regex_improve", "detection", "justices.json"),
        help="Path to justices.json",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="Fuzzy match threshold (0.0–1.0, default 0.75)",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Do not archive the previous CSV before overwriting",
    )
    parser.add_argument(
        "--justices-csv",
        default="ph_sc_justices.csv",
        help="Path to ph_sc_justices.csv for full-name resolution (default: ph_sc_justices.csv)",
    )
    args = parser.parse_args()

    csv_path = args.justices_csv if os.path.exists(args.justices_csv) else None

    try:
        stats = write_predictions_csv(
            input_dir=args.input_dir,
            output_path=args.output,
            justices_path=args.justices,
            threshold=args.threshold,
            archive=not args.no_archive,
            csv_path=csv_path,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
