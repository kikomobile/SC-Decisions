"""Harvest justice names from pipeline output files.

Scans predicted.json files, extracts ponente names from high-confidence cases,
and adds new unique names to justices.json registry.
"""

import json
import sys
import argparse
import re
from pathlib import Path
from typing import List, Dict, Any, Set

from .justice_registry import add_justices


def parse_confidence_from_notes(notes: str) -> float:
    """Parse confidence score from notes field.
    
    The pipeline writes "confidence: 0.950" into the notes field.
    
    Args:
        notes: Notes string from case data
        
    Returns:
        Confidence score as float, or 0.0 if not found/parseable
    """
    if not notes:
        return 0.0
    
    # Look for pattern "confidence: 0.950"
    match = re.search(r'confidence:\s*([0-9.]+)', notes, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def extract_ponente_names(predicted_path: Path, threshold: float = 0.9) -> List[str]:
    """Extract ponente names from predicted.json file.
    
    Args:
        predicted_path: Path to predicted.json file
        threshold: Minimum confidence score to harvest from
        
    Returns:
        List of ponente names found in high-confidence cases
    """
    try:
        with open(predicted_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not read {predicted_path}: {e}")
        return []
    
    ponente_names = []
    
    # Navigate through the JSON structure: data["volumes"][i]["cases"][j]
    volumes = data.get("volumes", [])
    if not isinstance(volumes, list):
        print(f"Warning: Invalid format in {predicted_path}: 'volumes' is not a list")
        return []
    
    for volume in volumes:
        cases = volume.get("cases", [])
        if not isinstance(cases, list):
            continue
        
        for case in cases:
            # Parse confidence from notes
            notes = case.get("notes", "")
            confidence = parse_confidence_from_notes(notes)
            
            if confidence < threshold:
                continue
            
            # Find ponente annotation
            annotations = case.get("annotations", [])
            if not isinstance(annotations, list):
                continue
            
            for ann in annotations:
                if ann.get("label") == "ponente":
                    text = ann.get("text", "").strip()
                    
                    # Skip empty or invalid names
                    if not text or len(text) < 3:
                        continue
                    
                    # Skip "PER CURIAM" (not a justice name)
                    if "PER CURIAM" in text.upper():
                        continue
                    
                    ponente_names.append(text)
                    break  # Only take first ponente annotation per case
    
    return ponente_names


def harvest(input_path: Path, threshold: float = 0.9, dry_run: bool = False) -> Dict[str, Any]:
    """Harvest justice names from predicted.json files.
    
    Args:
        input_path: Path to file or directory
        threshold: Minimum confidence score
        dry_run: If True, don't modify justices.json
        
    Returns:
        Summary dictionary with harvest results
    """
    # Collect files to process
    files_to_process = []
    
    if input_path.is_file():
        files_to_process.append(input_path)
    elif input_path.is_dir():
        # Find all *_predicted.json and *.predicted.json files
        for pattern in ["*_predicted.json", "*.predicted.json"]:
            files_to_process.extend(input_path.glob(pattern))
    else:
        return {
            "files_scanned": 0,
            "cases_above_threshold": 0,
            "ponente_names_found": 0,
            "new_names_added": [],
            "already_known": [],
            "skipped_per_curiam": 0,
            "dry_run": dry_run,
            "error": f"Path does not exist: {input_path}"
        }
    
    # Process files
    all_names = []
    files_scanned = 0
    cases_above_threshold = 0
    
    for file_path in files_to_process:
        try:
            names = extract_ponente_names(file_path, threshold)
            all_names.extend(names)
            files_scanned += 1
            
            # Count cases above threshold (rough estimate - each name represents a case)
            cases_above_threshold += len(names)
            
        except Exception as e:
            print(f"Warning: Error processing {file_path}: {e}")
    
    # Case-insensitive deduplication
    unique_names = []
    seen = set()
    
    for name in all_names:
        name_upper = name.upper()
        if name_upper not in seen:
            seen.add(name_upper)
            unique_names.append(name)
    
    # Add to registry (or simulate if dry-run)
    if dry_run:
        new_names_added = unique_names  # In dry-run, show all names that would be added
        already_known = []
    else:
        new_names_added = add_justices(unique_names)
        already_known = [name for name in unique_names if name not in new_names_added]
    
    return {
        "files_scanned": files_scanned,
        "cases_above_threshold": cases_above_threshold,
        "ponente_names_found": len(unique_names),
        "new_names_added": new_names_added,
        "already_known": already_known,
        "skipped_per_curiam": len(all_names) - len(unique_names),  # Rough estimate
        "dry_run": dry_run
    }


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Harvest justice names from pipeline output files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m detection.harvest_justices ../downloads/predictions/
  python -m detection.harvest_justices ../downloads/predictions/ --dry-run
  python -m detection.harvest_justices ../downloads/predictions/ --threshold 0.85
  python -m detection.harvest_justices ../downloads/Volume_226.predicted.json
        """
    )
    
    parser.add_argument(
        "input",
        type=Path,
        help="Path to a single predicted.json OR a directory containing *_predicted.json files"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be added without writing to justices.json"
    )
    
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.9,
        help="Minimum case confidence score to harvest ponente from (default: 0.9)"
    )
    
    args = parser.parse_args()
    
    # Validate threshold
    if args.threshold < 0 or args.threshold > 1:
        print("Error: Threshold must be between 0 and 1")
        sys.exit(1)
    
    # Run harvest
    result = harvest(args.input, args.threshold, args.dry_run)
    
    # Print summary
    print("\n" + "=" * 60)
    print("JUSTICE HARVEST SUMMARY")
    print("=" * 60)
    
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)
    
    print(f"Files scanned: {result['files_scanned']}")
    print(f"Cases above threshold ({args.threshold}): {result['cases_above_threshold']}")
    print(f"Unique ponente names found: {result['ponente_names_found']}")
    print(f"Already in registry: {len(result['already_known'])}")
    print(f"New names to add: {len(result['new_names_added'])}")
    
    if result['skipped_per_curiam'] > 0:
        print(f"Skipped PER CURIAM entries: {result['skipped_per_curiam']}")
    
    if result['already_known']:
        print(f"\nAlready known justices:")
        for name in sorted(result['already_known']):
            print(f"  - {name}")
    
    if result['new_names_added']:
        print(f"\nNew justices to add:")
        for name in sorted(result['new_names_added']):
            print(f"  - {name}")
        
        if not result['dry_run']:
            print(f"\n{len(result['new_names_added'])} new justice(s) added to justices.json.")
            print("Consider re-running the pipeline on previously processed volumes to benefit")
            print("from improved ponente matching:")
            print("    python -m detection <volume_dir> --range <range> --skip-llm")
        else:
            print(f"\nDRY RUN: {len(result['new_names_added'])} justice(s) would be added.")
            print("Run without --dry-run to actually update justices.json")
    else:
        print("\nNo new justice names found to add.")
    
    print("=" * 60)


if __name__ == "__main__":
    main()