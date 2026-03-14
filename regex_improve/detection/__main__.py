"""CLI entry point for the detection pipeline.

Usage:
  python -m detection <input> [-o OUTPUT] [--budget BUDGET] [--threshold THRESHOLD] 
          [--range START-END] [--score GROUND_TRUTH] [--skip-llm]
  
Examples:
  # Single volume processing
  python -m detection ../downloads/Volume_226.txt
  
  # Single volume with custom output
  python -m detection ../downloads/Volume_226.txt -o predictions/vol226.json
  
  # Batch processing
  python -m detection ../downloads --range 226-230
  
  # With scoring against ground truth
  python -m detection ../downloads/Volume_226.txt --score ground_truth.json
"""

import sys
import os
import argparse
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .pipeline import process_volume, process_batch
from .scorer import score_volume, format_results_table


def parse_volume_range(range_str: str) -> tuple[int, int]:
    """Parse volume range string like '226-961' or '226'."""
    if '-' in range_str:
        start, end = range_str.split('-', 1)
        return int(start), int(end)
    else:
        val = int(range_str)
        return val, val


def main():
    parser = argparse.ArgumentParser(
        description="Detection pipeline for Philippine Supreme Court cases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Single volume:  python -m detection ../downloads/Volume_226.txt
  Batch:          python -m detection ../downloads --range 226-230
  With scoring:   python -m detection ../downloads/Volume_226.txt --score ground_truth.json
        """
    )
    
    # Input argument (positional)
    parser.add_argument(
        "input",
        type=Path,
        help="Volume .txt file (single mode) or directory (batch mode)"
    )
    
    # Output options
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output path (single) or directory (batch). "
             "Defaults: <input>.predicted.json or <input>/predictions/"
    )
    
    # Processing options
    parser.add_argument(
        "--budget",
        type=float,
        default=5.0,
        help="LLM budget in USD (default: 5.00)"
    )
    
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="Confidence threshold for LLM fallback (default: 0.7)"
    )
    
    parser.add_argument(
        "--range",
        type=str,
        help="Volume range for batch, e.g., '226-961'"
    )
    
    parser.add_argument(
        "--score",
        type=Path,
        help="Optional ground truth path — run scorer after extraction"
    )
    
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM fallback entirely"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocessing even if manifest says volume is up to date"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON when scoring"
    )
    
    args = parser.parse_args()
    
    # Validate input path
    if not args.input.exists():
        print(f"Error: Input path '{args.input}' does not exist")
        sys.exit(1)
    
    # Determine mode: single file or batch directory
    is_batch = args.input.is_dir() or args.range is not None
    
    if is_batch:
        # Batch mode
        if args.input.is_file():
            print("Error: Batch mode requires a directory as input")
            sys.exit(1)
        
        # Parse volume range
        if args.range:
            try:
                volume_range = parse_volume_range(args.range)
            except ValueError:
                print(f"Error: Invalid range format '{args.range}'. Use 'START-END' or 'NUMBER'")
                sys.exit(1)
        else:
            # Default range from TASKS.md
            volume_range = (226, 961)
        
        # Set output directory
        if args.output:
            output_dir = args.output
        else:
            output_dir = args.input / "predictions"
        
        print(f"Batch processing: volumes {volume_range[0]}-{volume_range[1]}")
        print(f"Input directory: {args.input}")
        print(f"Output directory: {output_dir}")
        print(f"LLM budget: ${args.budget:.2f}")
        print(f"Confidence threshold: {args.threshold}")
        print(f"Skip LLM: {args.skip_llm}")
        print(f"Force reprocess: {args.force}")
        print()
        
        # Process batch
        summary = process_batch(
            volume_dir=args.input,
            output_dir=output_dir,
            volume_range=volume_range,
            llm_budget=args.budget,
            confidence_threshold=args.threshold,
            skip_llm=args.skip_llm,
            force=args.force
        )
        
        # Scoring not supported in batch mode
        if args.score:
            print("Warning: Scoring not supported in batch mode. Use --score with single volume.")
        
    else:
        # Single file mode
        volume_path = args.input
        
        # Set output path
        if args.output:
            output_path = args.output
        else:
            output_path = volume_path.with_suffix(".predicted.json")
        
        print(f"Single volume processing")
        print(f"Input file: {volume_path}")
        print(f"Output file: {output_path}")
        print(f"LLM budget: ${args.budget:.2f}")
        print(f"Confidence threshold: {args.threshold}")
        print(f"Skip LLM: {args.skip_llm}")
        print(f"Force reprocess: {args.force}")
        print()
        
        # Process volume
        result = process_volume(
            volume_path=volume_path,
            output_path=output_path,
            llm_budget=args.budget,
            confidence_threshold=args.threshold,
            skip_llm=args.skip_llm,
            force=args.force
        )
        
        # Run scorer if requested
        if args.score:
            print("\n" + "=" * 80)
            print("RUNNING SCORER")
            print("=" * 80)
            
            if not args.score.exists():
                print(f"Error: Ground truth file '{args.score}' does not exist")
                sys.exit(1)
            
            try:
                scoring_results = score_volume(
                    predicted_path=output_path,
                    ground_truth_path=args.score
                )
                
                if args.json:
                    import json
                    print(json.dumps(scoring_results, indent=2))
                else:
                    print(format_results_table(scoring_results))
                    
            except Exception as e:
                print(f"Scoring failed: {e}")
                sys.exit(1)


if __name__ == "__main__":
    main()