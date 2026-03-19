"""
Run the detection pipeline scorer against a ground truth file and display results.

This is a thin wrapper that runs the pipeline with --score and extracts
the summary table. Useful for regression testing after code changes.

Usage:
    python validation/check_ground_truth.py
    python validation/check_ground_truth.py --volume ../downloads/Volume_226.txt --gt annotation_exports/ground_truth_20260318_150802.json
"""
import argparse
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Run ground truth regression check.")
    parser.add_argument(
        "--volume",
        default="../downloads/Volume_226.txt",
        help="Volume .txt file to score",
    )
    parser.add_argument(
        "--gt",
        default="annotation_exports/ground_truth_20260318_150802.json",
        help="Ground truth JSON file",
    )
    parser.add_argument("--force", action="store_true", help="Force reprocess")
    args = parser.parse_args()

    cmd = [
        sys.executable, "-B", "-m", "detection",
        args.volume,
        "--score", args.gt,
        "--skip-llm",
    ]
    if args.force:
        cmd.append("--force")

    print(f"Running: {' '.join(cmd)}")
    print(f"  Volume: {args.volume}")
    print(f"  Ground truth: {args.gt}")
    print()

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd="regex_improve",
    )

    # Extract scoring section from output
    output = result.stdout + result.stderr
    in_scoring = False
    for line in output.split("\n"):
        if "SCORING RESULTS" in line:
            in_scoring = True
        if in_scoring:
            print(line)
        # Also print the micro line and per-label table from scorer output
        if re.match(r"^(Micro-averaged|Per-label|---|----|Label\s|start_of|case_num|date|division|parties|start_syl|end_syl|counsel|ponente|doc_type|start_dec|end_dec|votes|start_op|end_op|end_of|Case summary)", line):
            if not in_scoring:
                print(line)

    if result.returncode != 0:
        print(f"\nProcess exited with code {result.returncode}")
        if result.stderr:
            # Show last 10 lines of stderr for diagnosis
            err_lines = result.stderr.strip().split("\n")
            for line in err_lines[-10:]:
                print(f"  STDERR: {line}")


if __name__ == "__main__":
    main()
