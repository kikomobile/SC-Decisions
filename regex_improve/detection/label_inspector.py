"""
Label Inspector — lookup cases by volume+case_number in predicted JSON files.

For spot-checking extraction quality, this module looks up specific cases from
predicted JSON files by (volume, case_number) pairs. The input comes from pasting
tab-separated rows copied from Excel (e.g., "227\tG.R. No. 71905"). The output
includes every annotation label with raw text, char offsets, page numbers, group,
and detection_method.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any


@dataclass
class CaseResult:
    """Result of a case lookup query."""
    volume: int
    case_number: str          # the queried case_number
    found: bool
    case_id: Optional[str] = None       # e.g. "vol227_case_3"
    confidence: Optional[float] = None  # parsed from notes field
    annotations: Optional[List[Dict[str, Any]]] = None   # raw annotation dicts from JSON
    error: Optional[str] = None         # error message if not found


def parse_lookup_input(text: str) -> List[Tuple[int, str]]:
    """
    Parse multi-line input where each line is `<volume><TAB><case_number>`.
    
    Args:
        text: Multi-line string with tab-separated volume and case_number
        
    Returns:
        List of (volume_number, case_number) tuples
        
    Example input:
        227	G.R. No. 71905
        227	G.R. No. 68661
        439	G.R. No. 145734
    """
    queries = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
            
        parts = line.split('\t')
        if len(parts) < 2:
            continue
            
        vol_str = parts[0].strip()
        case_num = parts[1].strip()
        
        # Extract digits from volume string (handles "Volume_227" or just "227")
        vol_match = re.search(r'\d+', vol_str)
        if not vol_match:
            continue
            
        vol_num = int(vol_match.group())
        queries.append((vol_num, case_num))
    
    return queries


def _normalize_case_number(case_num: str) -> str:
    """Normalize case number for comparison: lowercase and collapse multiple spaces."""
    # Convert to lowercase
    normalized = case_num.lower()
    # Collapse multiple spaces to single space
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip()


def lookup_cases(predictions_dir: str, queries: List[Tuple[int, str]]) -> List[CaseResult]:
    """
    Look up cases in prediction JSON files.
    
    Args:
        predictions_dir: Directory containing predicted JSON files
        queries: List of (volume_number, case_number) tuples to look up
        
    Returns:
        List of CaseResult objects, one per query
    """
    results = []
    
    # Group queries by volume for efficiency
    queries_by_volume: Dict[int, List[str]] = {}
    for vol, case_num in queries:
        queries_by_volume.setdefault(vol, []).append(case_num)
    
    for vol, case_numbers in queries_by_volume.items():
        # Build path to prediction file
        pred_file = Path(predictions_dir) / f"Volume_{vol}_predicted.json"
        
        if not pred_file.exists():
            # File doesn't exist - create not-found results for all queries for this volume
            for case_num in case_numbers:
                results.append(CaseResult(
                    volume=vol,
                    case_number=case_num,
                    found=False,
                    error=f"Prediction file not found: Volume_{vol}_predicted.json"
                ))
            continue
        
        # Load the JSON file with UTF-8 encoding
        try:
            with open(pred_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # Error reading file - create not-found results for all queries for this volume
            for case_num in case_numbers:
                results.append(CaseResult(
                    volume=vol,
                    case_number=case_num,
                    found=False,
                    error=f"Error reading prediction file: {e}"
                ))
            continue
        
        # Find the volumes list in the JSON
        volumes_data = data.get('volumes', [])
        volume_data = None
        for v in volumes_data:
            if v.get('volume_name') == f"Volume_{vol}":
                volume_data = v
                break
        
        if not volume_data:
            # Volume not found in JSON - create not-found results
            for case_num in case_numbers:
                results.append(CaseResult(
                    volume=vol,
                    case_number=case_num,
                    found=False,
                    error=f"Volume {vol} not found in prediction file"
                ))
            continue
        
        # Get cases for this volume
        cases = volume_data.get('cases', [])
        
        # Create a mapping from normalized case_number to case data
        case_map: Dict[str, Dict[str, Any]] = {}
        for case in cases:
            # Collect all case_number annotations for this case
            case_number_annotations = []
            for ann in case.get('annotations', []):
                if ann.get('label') == 'case_number':
                    case_number_annotations.append(ann.get('text', ''))
            
            # Add to map for each case_number annotation
            for case_num_text in case_number_annotations:
                normalized = _normalize_case_number(case_num_text)
                case_map[normalized] = case
        
        # Process each query for this volume
        for case_num in case_numbers:
            normalized_query = _normalize_case_number(case_num)
            
            if normalized_query in case_map:
                # Case found
                case = case_map[normalized_query]
                annotations = case.get('annotations', [])
                
                # Extract confidence from notes field
                confidence = None
                notes = case.get('notes', '')
                if notes:
                    match = re.search(r'confidence:\s*([\d.]+)', notes)
                    if match:
                        try:
                            confidence = float(match.group(1))
                        except ValueError:
                            confidence = None
                
                results.append(CaseResult(
                    volume=vol,
                    case_number=case_num,
                    found=True,
                    case_id=case.get('case_id'),
                    confidence=confidence,
                    annotations=annotations,
                    error=None
                ))
            else:
                # Case not found
                results.append(CaseResult(
                    volume=vol,
                    case_number=case_num,
                    found=False,
                    error=f"Case {case_num} not found in Volume {vol} ({len(cases)} cases searched)"
                ))
    
    return results


def format_case_text(result: CaseResult) -> str:
    """
    Format case result as a readable text block for display.
    
    Args:
        result: CaseResult object
        
    Returns:
        Formatted text string
    """
    if not result.found:
        return f"=== Volume {result.volume} | {result.case_number} | NOT FOUND ===\n{result.error}"
    
    # Build header
    conf_str = f"{result.confidence:.3f}" if result.confidence is not None else "N/A"
    header = f"=== Volume {result.volume} | {result.case_number} | {result.case_id} | confidence: {conf_str} ===\n\n"
    
    # Build annotation lines
    lines = []
    for ann in result.annotations:
        label = ann.get('label', '')
        start_page = ann.get('start_page', '')
        end_page = ann.get('end_page', '')
        start_char = ann.get('start_char', '')
        end_char = ann.get('end_char', '')
        group = ann.get('group', '')
        detection_method = ann.get('detection_method', '')
        text = ann.get('text', '')
        
        # Format group as string (could be None, int, or other)
        group_str = str(group) if group is not None else 'None'
        
        # Format page range
        if start_page == end_page:
            page_range = f"{start_page}"
        else:
            page_range = f"{start_page}-{end_page}"
        
        line = f"[{label}] (pages {page_range}, chars {start_char}-{end_char}, group: {group_str}, method: {detection_method})\n{text}\n"
        lines.append(line)
    
    return header + '\n'.join(lines)


def compile_results(results: List[CaseResult]) -> Dict[str, Any]:
    """
    Compile lookup results into a JSON-serializable dict.
    
    Args:
        results: List of CaseResult objects
        
    Returns:
        Dict with summary and detailed results
    """
    found_count = sum(1 for r in results if r.found)
    
    # Convert CaseResult objects to dicts
    cases_data = []
    for r in results:
        case_dict = {
            'volume': r.volume,
            'case_number': r.case_number,
            'found': r.found,
            'case_id': r.case_id,
            'confidence': r.confidence,
            'annotations': r.annotations,
            'error': r.error
        }
        cases_data.append(case_dict)
    
    return {
        'generated': datetime.now().isoformat(),
        'query_count': len(results),
        'found_count': found_count,
        'not_found_count': len(results) - found_count,
        'cases': cases_data
    }


if __name__ == '__main__':
    # Enhanced command-line interface
    import sys
    import argparse
    import json
    
    parser = argparse.ArgumentParser(
        description="Look up cases by volume+case_number in predicted JSON files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single case lookup
  python -m regex_improve.detection.label_inspector ../downloads/predictions 227 "G.R. No. 71905"
  
  # Multiple cases from file
  python -m regex_improve.detection.label_inspector --query-file queries.txt --output results.txt
  
  # Multiple cases from stdin
  echo -e "227\\tG.R. No. 71905\\n227\\tG.R. No. 68661" | python -m regex_improve.detection.label_inspector ../downloads/predictions -
        """
    )
    
    parser.add_argument(
        "predictions_dir",
        nargs="?",
        default="../downloads/predictions",
        help="Directory containing predicted JSON files (default: ../downloads/predictions)"
    )
    
    parser.add_argument(
        "volume",
        nargs="?",
        type=int,
        help="Volume number (optional when using --query-file)"
    )
    
    parser.add_argument(
        "case_number",
        nargs="?",
        help="Case number (optional when using --query-file)"
    )
    
    parser.add_argument(
        "--query-file",
        type=argparse.FileType('r', encoding='utf-8'),
        help="File containing tab-separated volume and case_number pairs"
    )
    
    parser.add_argument(
        "--output",
        type=argparse.FileType('w', encoding='utf-8'),
        help="Output file (default: stdout)"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON format instead of human-readable text"
    )
    
    args = parser.parse_args()
    
    # Determine queries
    queries = []
    
    if args.query_file:
        # Read queries from file
        query_text = args.query_file.read()
        args.query_file.close()
        queries = parse_lookup_input(query_text)
    elif args.volume is not None and args.case_number is not None:
        # Single query from command line
        queries = [(args.volume, args.case_number)]
    else:
        # Try reading from stdin if no arguments provided
        import select
        if select.select([sys.stdin], [], [], 0.0)[0]:
            # Data available on stdin
            query_text = sys.stdin.read()
            queries = parse_lookup_input(query_text)
        else:
            # No input provided
            parser.print_help()
            sys.exit(1)
    
    if not queries:
        print("Error: No valid queries found")
        sys.exit(1)
    
    # Look up cases
    results = lookup_cases(args.predictions_dir, queries)
    
    # Output results
    output_file = args.output or sys.stdout
    
    if args.json:
        # JSON output
        compiled = compile_results(results)
        json.dump(compiled, output_file, indent=2, ensure_ascii=False)
    else:
        # Human-readable text output
        for result in results:
            output_file.write(format_case_text(result))
            output_file.write("\n" + "="*80 + "\n\n")
    
    # Close output file if it's not stdout
    if args.output:
        args.output.close()
