"""Pipeline orchestrator for the detection system.

Wires all stages together: preprocessing → boundary detection → section extraction →
OCR correction → confidence scoring → LLM fallback → JSON output.
"""

import json
import logging
import sys
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import detection modules
from .preprocess import VolumePreprocessor
from .boundary_fsm import CaseBoundaryDetector, CaseBoundary
from .section_extractor import SectionExtractor, ExtractedCase
from .ocr_correction import correct_annotations, Correction
from .confidence import score_all_cases, score_case, KNOWN_JUSTICES
from .llm_fallback import (
    BudgetTracker, 
    extract_with_llm, 
    determine_labels_to_re_extract,
    convert_llm_labels_to_annotations,
    get_client
)
from .diagnostics import run_diagnostics, DiagnosticReport
from .manifest import (
    load_manifest, save_manifest, get_volume_entry, update_volume_entry,
    should_reprocess, load_previous_predictions, merge_annotations,
    _get_source_mtime, PIPELINE_VERSION
)
from .pattern_registry import get_era, get_era_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of processing a volume."""
    volume_name: str
    cases: List[Dict[str, Any]] = field(default_factory=list)
    corrections: List[Correction] = field(default_factory=list)
    llm_calls: int = 0
    llm_cost: float = 0.0
    confidence_summary: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    diagnostics: Optional[Dict[str, Any]] = None


def process_volume(
    volume_path: Path,
    output_path: Optional[Path] = None,
    llm_budget: float = 5.0,
    confidence_threshold: float = 0.7,
    skip_llm: bool = False,
    budget: Optional[BudgetTracker] = None,
    force: bool = False
) -> PipelineResult:
    """Process a single volume through the detection pipeline.

    Args:
        volume_path: Path to volume text file
        output_path: Optional path to write JSON output
        llm_budget: LLM budget in USD (default 5.00)
        confidence_threshold: Confidence threshold for LLM fallback (default 0.7)
        skip_llm: If True, skip LLM fallback entirely
        budget: Optional BudgetTracker to share across multiple volumes. If None,
                a new BudgetTracker will be created with llm_budget.
        force: If True, reprocess even if manifest says volume is up to date.

    Returns:
        PipelineResult with all processing results
    """
    logger.info(f"Processing volume: {volume_path.name}")

    # Initialize budget tracker
    if budget is None:
        budget = BudgetTracker(total_budget=llm_budget)

    # Manifest check: skip if up to date
    volume_name = volume_path.stem
    output_dir = output_path.parent if output_path else None
    manifest = {}
    if output_dir:
        manifest = load_manifest(output_dir)
        needs_reprocess, reason = should_reprocess(manifest, volume_name, volume_path, force or skip_llm)
        if not needs_reprocess:
            logger.info(f"Volume {volume_name} is up to date, skipping ({reason})")
            # Return a cached result from previous predictions
            entry = get_volume_entry(manifest, volume_name)
            prev_data = load_previous_predictions(output_dir, entry["prediction_file"])
            cached_cases = []
            if prev_data:
                for vol in prev_data.get("volumes", []):
                    cached_cases.extend(vol.get("cases", []))
            return PipelineResult(
                volume_name=volume_path.name,
                cases=cached_cases,
                corrections=[],
                llm_calls=entry.get("llm_calls", 0),
                llm_cost=0.0,
                confidence_summary={
                    "high_confidence": entry.get("total_cases", 0),
                    "low_confidence": 0,
                    "threshold": entry.get("confidence_threshold", confidence_threshold)
                },
                metadata={
                    "total_cases": entry.get("total_cases", 0),
                    "cached": True,
                    "cache_reason": reason
                }
            )
        else:
            logger.info(f"Reprocessing {volume_name}: {reason}")
    
    # Extract volume number from filename (e.g., "Volume_226" -> 226)
    vol_match = re.search(r'(\d+)', volume_name)
    vol_num = int(vol_match.group(1)) if vol_match else None
    era = get_era(vol_num)
    logger.info(f"Volume number: {vol_num}, era: {era.name}")
    
    # Step 1: Preprocess
    logger.info("Step 1: Preprocessing volume...")
    preprocessor = VolumePreprocessor(vol_num=vol_num)
    try:
        volume_text = preprocessor.load(volume_path)
    except Exception as e:
        logger.error(f"Failed to load volume: {e}")
        raise
    
    # Step 2: Detect case boundaries
    logger.info("Step 2: Detecting case boundaries...")
    detector = CaseBoundaryDetector(preprocessor, vol_num=vol_num)
    try:
        boundaries = detector.detect()
    except Exception as e:
        logger.error(f"Failed to detect boundaries: {e}")
        raise
    
    logger.info(f"Detected {len(boundaries)} case boundaries")
    
    # Step 3: Extract sections
    logger.info("Step 3: Extracting sections...")
    extractor = SectionExtractor(preprocessor, vol_num=vol_num)
    try:
        extracted_cases = extractor.extract_all(boundaries)
    except Exception as e:
        logger.error(f"Failed to extract sections: {e}")
        raise
    
    logger.info(f"Extracted {len(extracted_cases)} cases")
    
    # Collect matched line numbers for near-miss detection
    matched_lines = set()
    
    # From boundary FSM: division headers and bracket lines
    for boundary in boundaries:
        matched_lines.add(boundary.start_line)  # division line
        for cn in boundary.case_numbers:
            # Convert char offsets to line numbers
            start_line = preprocessor.loader.char_to_line(cn.start_char)
            end_line = preprocessor.loader.char_to_line(cn.end_char - 1)
            for line_num in range(start_line, end_line + 1):
                matched_lines.add(line_num)
    
    # From section extractor: all annotation lines
    for case in extracted_cases:
        for ann in case.annotations:
            ann_start_line = preprocessor.loader.char_to_line(ann.start_char)
            ann_end_line = preprocessor.loader.char_to_line(ann.end_char - 1)
            # For position labels (start_of_case, end_decision, etc.), add exact line
            # For span labels (parties, counsel, votes), add the start line only
            # to avoid over-excluding body text within the span
            if ann.label in ("start_of_case", "end_of_case", "start_decision",
                             "end_decision", "start_syllabus", "end_syllabus",
                             "start_opinion", "end_opinion", "division",
                             "doc_type", "ponente"):
                # Position/header labels: add all lines in the span
                for line_num in range(ann_start_line, ann_end_line + 1):
                    matched_lines.add(line_num)
            elif ann.label in ("case_number", "date"):
                # Short labels: add all lines
                for line_num in range(ann_start_line, ann_end_line + 1):
                    matched_lines.add(line_num)
            else:
                # Long span labels (parties, counsel, votes, syllabus content):
                # Only add the first and last line to avoid masking body text issues
                matched_lines.add(ann_start_line)
                matched_lines.add(ann_end_line)
    
    # Step 4: OCR correction
    logger.info("Step 4: Applying OCR corrections...")
    all_corrections = []
    corrected_cases = []
    
    for case in extracted_cases:
        # Convert Annotation objects to dictionaries for OCR correction
        annotation_dicts = []
        for ann in case.annotations:
            # Convert Annotation dataclass to dict
            ann_dict = {
                "label": ann.label,
                "text": ann.text,
                "start_char": ann.start_char,
                "end_char": ann.end_char,
                "start_page": ann.start_page,
                "end_page": ann.end_page,
                "group": ann.group,
                "detection_method": "regex"
            }
            annotation_dicts.append(ann_dict)
        
        corrected_annotations, corrections = correct_annotations(annotation_dicts)
        all_corrections.extend(corrections)
        
        # Store corrected annotations as dict structure for steps 5+
        corrected_case = {
            "case_id": case.case_id,
            "annotations": corrected_annotations,
            "confidence": case.confidence,
            "notes": case.notes
        }
        corrected_cases.append(corrected_case)
    
    logger.info(f"Applied {len(all_corrections)} OCR corrections")

    # Step 4b: Merge with previous predictions (preserve cached LLM results)
    # Always merge when previous predictions exist — --force only bypasses the
    # manifest skip check, it does NOT discard expensive cached LLM annotations.
    if output_dir:
        entry = get_volume_entry(manifest, volume_name)
        if entry and entry.get("prediction_file"):
            prev_data = load_previous_predictions(output_dir, entry["prediction_file"])
            if prev_data:
                # Build a map of previous cases by case_id
                prev_cases_map = {}
                for vol in prev_data.get("volumes", []):
                    for prev_case in vol.get("cases", []):
                        prev_cases_map[prev_case["case_id"]] = prev_case

                merged_count = 0
                for case in corrected_cases:
                    case_id = case["case_id"]
                    if case_id in prev_cases_map:
                        prev_anns = prev_cases_map[case_id].get("annotations", [])
                        case["annotations"] = merge_annotations(
                            prev_anns, case["annotations"], force_llm_rerun=False
                        )
                        merged_count += 1

                if merged_count > 0:
                    logger.info(f"Merged annotations for {merged_count} cases with previous predictions")

    # Step 5: Confidence scoring
    logger.info("Step 5: Scoring confidence...")
    
    # corrected_cases are already dicts, use them directly
    case_dicts = corrected_cases
    
    high_confidence, low_confidence = score_all_cases(
        case_dicts, 
        KNOWN_JUSTICES, 
        threshold=confidence_threshold
    )
    
    logger.info(f"Confidence split: {len(high_confidence)} high, {len(low_confidence)} low")
    
    # Step 6: LLM fallback for low-confidence cases
    llm_calls = 0
    llm_cost = 0.0
    
    if not skip_llm and low_confidence:
        logger.info(f"Step 6: LLM fallback for {len(low_confidence)} low-confidence cases...")
        
        # Try to get LLM client
        client = None
        try:
            client = get_client()
            logger.info("LLM client initialized successfully")
        except Exception as e:
            logger.warning(f"Cannot initialize LLM client: {e}")
            logger.warning("Skipping LLM fallback")
            skip_llm = True
        
        if not skip_llm:
            # Process low-confidence cases
            for case in low_confidence:
                case_id = case["case_id"]
                annotations = case["annotations"]
                confidence_score = case.get("confidence_score", 0.0)
                confidence_flags = case.get("confidence_flags", [])
                
                # Score case to get individual check scores
                confidence_result = score_case(annotations, KNOWN_JUSTICES)
                
                # Determine which labels to re-extract
                labels_to_re_extract = determine_labels_to_re_extract(
                    {"score": confidence_score, "flags": confidence_flags},
                    confidence_result.checks
                )
                
                if not labels_to_re_extract:
                    logger.debug(f"No labels to re-extract for case {case_id}")
                    continue

                # Filter out labels that already have cached LLM results (unless force)
                if not force:
                    existing_llm_labels = {
                        ann["label"] for ann in annotations
                        if ann.get("detection_method") == "llm"
                    }
                    if existing_llm_labels:
                        labels_to_re_extract = [
                            l for l in labels_to_re_extract
                            if l not in existing_llm_labels
                        ]
                        if not labels_to_re_extract:
                            logger.debug(f"All labels for case {case_id} already have cached LLM results")
                            continue
                
                # Get case text from volume
                # Find start_of_case annotation to get case start position
                case_start_char = None
                for ann in annotations:
                    if ann["label"] == "start_of_case":
                        case_start_char = ann["start_char"]
                        break
                
                if case_start_char is None:
                    logger.warning(f"Cannot find start_of_case for case {case_id}, skipping LLM")
                    continue
                
                # Find end_of_case annotation to get case end position
                case_end_char = None
                for ann in annotations:
                    if ann["label"] == "end_of_case":
                        case_end_char = ann["end_char"]
                        break
                
                if case_end_char is None:
                    # Use next case start or end of volume
                    # For simplicity, use a large chunk
                    case_end_char = min(case_start_char + 10000, len(volume_text))
                
                case_text = volume_text[case_start_char:case_end_char]
                
                # Call LLM
                logger.info(f"Calling LLM for case {case_id}, labels: {labels_to_re_extract}")
                llm_labels = extract_with_llm(
                    case_text=case_text,
                    labels_to_extract=labels_to_re_extract,
                    existing_labels=annotations,
                    budget=budget,
                    client=client,
                    case_id=case_id
                )
                
                if llm_labels:
                    llm_calls += 1
                    llm_cost = budget.total_cost
                    
                    # Convert LLM labels to annotations
                    llm_annotations = convert_llm_labels_to_annotations(
                        llm_labels, case_start_char, case_id
                    )
                    
                    # Merge LLM annotations with original annotations
                    # Remove original annotations for re-extracted labels
                    merged_annotations = []
                    labels_replaced = set()
                    
                    for ann in annotations:
                        if ann["label"] not in labels_to_re_extract:
                            merged_annotations.append(ann)
                        else:
                            labels_replaced.add(ann["label"])
                    
                    # Add LLM annotations
                    for llm_ann in llm_annotations:
                        merged_annotations.append(llm_ann)
                    
                    # Update case with merged annotations
                    case["annotations"] = merged_annotations
                    logger.info(f"Replaced {len(labels_replaced)} labels in case {case_id}")
                else:
                    logger.warning(f"LLM extraction failed for case {case_id}")
    
    # Combine high and low confidence cases
    all_cases = high_confidence + low_confidence
    
    # Step 7: Assemble final JSON
    logger.info("Step 7: Assembling final JSON...")
    
    # Build format_version=2 structure
    volume_data = {
        "volume_name": volume_path.stem,
        "total_cases": len(all_cases),
        "cases": []
    }
    
    for case in all_cases:
        case_data = {
            "case_id": case["case_id"],
            "annotations": case["annotations"],
            "status": "auto_extracted",
            "notes": f"confidence: {case.get('confidence_score', 0.0):.3f}"
        }
        volume_data["cases"].append(case_data)
    
    final_output = {
        "format_version": 2,
        "status": "auto_extracted",
        "volumes": [volume_data],
        "metadata": {
            "pipeline_version": PIPELINE_VERSION,
            "llm_budget_used": llm_cost,
            "llm_calls": llm_calls,
            "confidence_threshold": confidence_threshold,
            "ocr_corrections": len(all_corrections)
        }
    }
    
    # Step 8: Run diagnostics
    logger.info("Step 8: Running diagnostics...")
    diagnostic_report = None
    try:
        diagnostic_report = run_diagnostics(
            all_cases,
            volume_text=volume_text,
            matched_lines=matched_lines
        )
        logger.info(f"Diagnostics completed: {diagnostic_report.worst_severity}")
    except Exception as e:
        logger.error(f"Diagnostics failed: {e}")
        # Continue without diagnostics
    
    # Step 9: Write output if requested
    if output_path:
        logger.info(f"Step 9: Writing output to {output_path}")
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(final_output, f, indent=2, ensure_ascii=False)
            logger.info(f"Output written successfully")

            # Update manifest
            has_llm = any(
                ann.get("detection_method") == "llm"
                for case in all_cases
                for ann in case.get("annotations", [])
            )
            update_volume_entry(
                manifest, volume_name,
                prediction_file=output_path.name,
                total_cases=len(all_cases),
                llm_calls=llm_calls,
                has_llm_labels=has_llm,
                confidence_threshold=confidence_threshold,
                source_file_mtime=_get_source_mtime(volume_path)
            )
            save_manifest(output_path.parent, manifest)
            logger.info(f"Manifest updated for {volume_name}")

        except Exception as e:
            logger.error(f"Failed to write output: {e}")
            raise

    # Create result summary
    result = PipelineResult(
        volume_name=volume_path.name,
        cases=all_cases,
        corrections=all_corrections,
        llm_calls=llm_calls,
        llm_cost=llm_cost,
        confidence_summary={
            "high_confidence": len(high_confidence),
            "low_confidence": len(low_confidence),
            "threshold": confidence_threshold
        },
        metadata={
            "total_cases": len(all_cases),
            "boundaries_detected": len(boundaries),
            "ocr_corrections": len(all_corrections)
        }
    )
    
    # Add diagnostics to result if available
    if diagnostic_report:
        result.diagnostics = {
            "worst_severity": diagnostic_report.worst_severity,
            "checks": [
                {"name": c.name, "severity": c.severity, "message": c.message}
                for c in diagnostic_report.checks
            ],
            "near_miss_count": len(diagnostic_report.near_misses)
        }
    
    # Write summary log
    if output_path:
        log_path = output_path.with_suffix(".log")
        write_summary_log(result, budget, log_path, diagnostic_report=diagnostic_report)

    # Print summary
    print_summary(result, budget)

    return result


def process_batch(
    volume_dir: Path,
    output_dir: Path,
    volume_range: Tuple[int, int] = (226, 961),
    llm_budget: float = 5.0,
    confidence_threshold: float = 0.7,
    skip_llm: bool = False,
    force: bool = False
) -> Dict[str, Any]:
    """Process multiple volumes in batch mode.

    Args:
        volume_dir: Directory containing volume text files
        output_dir: Directory to write JSON outputs
        volume_range: Inclusive range of volume numbers to process
        llm_budget: LLM budget in USD (shared across all volumes)
        confidence_threshold: Confidence threshold for LLM fallback
        skip_llm: If True, skip LLM fallback entirely
        force: If True, reprocess even if manifest says volumes are up to date

    Returns:
        Summary dictionary with batch results
    """
    logger.info(f"Starting batch processing for volumes {volume_range[0]}-{volume_range[1]}")
    
    # Find volume files
    volume_files = []
    for vol_num in range(volume_range[0], volume_range[1] + 1):
        # Try different naming patterns
        patterns = [
            f"Volume_{vol_num}.txt",
            f"Volume {vol_num}.txt",
            f"vol{vol_num}.txt"
        ]
        
        for pattern in patterns:
            vol_path = volume_dir / pattern
            if vol_path.exists():
                volume_files.append(vol_path)
                break
    
    if not volume_files:
        logger.warning(f"No volume files found in {volume_dir} for range {volume_range}")
        return {"error": "No volume files found"}
    
    logger.info(f"Found {len(volume_files)} volume files")
    
    # Initialize shared budget tracker
    budget = BudgetTracker(total_budget=llm_budget)
    
    # Process each volume
    results = []
    for i, vol_path in enumerate(volume_files):
        logger.info(f"Processing volume {i+1}/{len(volume_files)}: {vol_path.name}")
        
        # Generate output path
        output_path = output_dir / f"{vol_path.stem}_predicted.json"
        
        try:
            result = process_volume(
                volume_path=vol_path,
                output_path=output_path,
                llm_budget=llm_budget,
                confidence_threshold=confidence_threshold,
                skip_llm=skip_llm,
                budget=budget,
                force=force
            )
            results.append(result)
            
            logger.info(f"Budget remaining: ${budget.budget_remaining:.2f}")
            
        except Exception as e:
            logger.error(f"Failed to process {vol_path.name}: {e}")
            continue
    
    # Generate batch summary
    total_cases = sum(len(r.cases) for r in results)
    total_llm_calls = sum(r.llm_calls for r in results)
    total_llm_cost = sum(r.llm_cost for r in results)
    total_corrections = sum(len(r.corrections) for r in results)
    
    summary = {
        "volumes_processed": len(results),
        "total_cases": total_cases,
        "total_llm_calls": total_llm_calls,
        "total_llm_cost": total_llm_cost,
        "total_ocr_corrections": total_corrections,
        "budget_remaining": budget.budget_remaining,
        "volume_results": [
            {
                "volume": r.volume_name,
                "cases": len(r.cases),
                "llm_calls": r.llm_calls,
                "llm_cost": r.llm_cost,
                "diagnostics_severity": r.diagnostics.get("worst_severity", "N/A") if r.diagnostics else "N/A"
            }
            for r in results
        ]
    }
    
    logger.info("Batch processing complete")
    print_batch_summary(summary)

    # Write batch summary log
    write_batch_summary_log(summary, output_dir)

    return summary


def write_summary_log(result: PipelineResult, budget: BudgetTracker, log_path: Path, 
                     diagnostic_report: DiagnosticReport = None) -> None:
    """Write a human-readable summary log to a text file."""
    from datetime import datetime

    lines = []
    lines.append("=" * 80)
    lines.append(f"DETECTION PIPELINE LOG — {result.volume_name}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 80)
    lines.append("")

    # Overall stats
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"Total cases detected:  {len(result.cases)}")
    lines.append(f"Boundaries detected:   {result.metadata.get('boundaries_detected', 'N/A')}")
    lines.append(f"High confidence:       {result.confidence_summary.get('high_confidence', 'N/A')}")
    lines.append(f"Low confidence:        {result.confidence_summary.get('low_confidence', 'N/A')}")
    lines.append(f"Confidence threshold:  {result.confidence_summary.get('threshold', 'N/A')}")
    lines.append(f"OCR corrections:       {len(result.corrections)}")
    lines.append(f"LLM calls:             {result.llm_calls}")
    lines.append(f"LLM cost:              ${result.llm_cost:.4f}")
    lines.append(f"Budget remaining:      ${budget.budget_remaining:.4f}")
    lines.append("")

    # Per-label annotation counts
    label_counts = {}
    for case in result.cases:
        for ann in case.get("annotations", []):
            label = ann.get("label", "unknown")
            label_counts[label] = label_counts.get(label, 0) + 1

    lines.append("ANNOTATION COUNTS BY LABEL")
    lines.append("-" * 40)
    for label in sorted(label_counts.keys()):
        lines.append(f"  {label:<20s} {label_counts[label]:>4d}")
    lines.append(f"  {'TOTAL':<20s} {sum(label_counts.values()):>4d}")
    lines.append("")

    # OCR corrections breakdown
    if result.corrections:
        lines.append("OCR CORRECTIONS")
        lines.append("-" * 40)
        corr_by_rule = {}
        for c in result.corrections:
            corr_by_rule[c.rule] = corr_by_rule.get(c.rule, 0) + 1
        for rule in sorted(corr_by_rule.keys()):
            lines.append(f"  {rule:<30s} {corr_by_rule[rule]:>4d}")
        lines.append("")

    # Diagnostics section
    if diagnostic_report:
        lines.append("DIAGNOSTICS")
        lines.append("-" * 40)
        lines.append(f"  Overall: {diagnostic_report.worst_severity.upper()}")
        lines.append("")
        for check in diagnostic_report.checks:
            severity_marker = {"ok": "  ", "warning": "! ", "critical": "!!"}
            marker = severity_marker.get(check.severity, "  ")
            lines.append(f"  {marker}{check.name}")
            lines.append(f"      {check.message}")
        lines.append("")

        if diagnostic_report.near_misses:
            lines.append("  NEAR-MISS PATTERN MATCHES")
            lines.append("  " + "-" * 36)
            for nm in diagnostic_report.near_misses:
                lines.append(f"    Line {nm['line_num']:>6d}  [{nm['pattern']:<12s}]  {nm['text']}")
            lines.append("")

    # Per-case details
    lines.append("PER-CASE DETAILS")
    lines.append("-" * 40)

    for case in result.cases:
        case_id = case.get("case_id", "unknown")
        score = case.get("confidence_score", 0.0)
        flags = case.get("confidence_flags", [])
        annotations = case.get("annotations", [])

        # Collect labels present
        labels_present = sorted(set(ann.get("label", "") for ann in annotations))

        # Get key fields for quick scan
        case_num = ""
        date_text = ""
        division = ""
        ponente = ""
        for ann in annotations:
            label = ann.get("label", "")
            text = ann.get("text", "")
            if label == "case_number" and not case_num:
                case_num = text[:60]
            elif label == "date" and not date_text:
                date_text = text[:30]
            elif label == "division" and not division:
                division = text
            elif label == "ponente" and not ponente:
                ponente = text

        lines.append(f"  {case_id}")
        lines.append(f"    Confidence:  {score:.3f}")
        lines.append(f"    Case #:      {case_num}")
        lines.append(f"    Date:        {date_text}")
        lines.append(f"    Division:    {division}")
        lines.append(f"    Ponente:     {ponente}")
        lines.append(f"    Labels ({len(annotations)}): {', '.join(labels_present)}")
        if flags:
            for flag in flags:
                lines.append(f"    [!] {flag}")
        lines.append("")

    lines.append("=" * 80)
    lines.append("END OF LOG")
    lines.append("=" * 80)

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        logger.info(f"Summary log written to {log_path}")
    except Exception as e:
        logger.error(f"Failed to write summary log: {e}")


def write_batch_summary_log(summary: Dict[str, Any], output_dir: Path) -> None:
    """Write a human-readable batch summary log."""
    from datetime import datetime

    log_path = output_dir / "batch_summary.log"
    lines = []
    lines.append("=" * 80)
    lines.append("BATCH DETECTION PIPELINE LOG")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Volumes processed:     {summary['volumes_processed']}")
    lines.append(f"Total cases:           {summary['total_cases']}")
    lines.append(f"Total LLM calls:       {summary['total_llm_calls']}")
    lines.append(f"Total LLM cost:        ${summary['total_llm_cost']:.4f}")
    lines.append(f"Total OCR corrections:  {summary['total_ocr_corrections']}")
    lines.append(f"Budget remaining:      ${summary['budget_remaining']:.4f}")
    lines.append("")
    lines.append("PER-VOLUME RESULTS")
    lines.append("-" * 40)
    for vol in summary['volume_results']:
        diag_status = vol.get('diagnostics_severity', 'N/A')
        lines.append(f"  {vol['volume']:<30s} {vol['cases']:>3d} cases, "
                     f"{vol['llm_calls']:>2d} LLM calls, ${vol['llm_cost']:.4f}, "
                     f"diag: {diag_status}")
    lines.append("")
    lines.append("=" * 80)

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        logger.info(f"Batch summary log written to {log_path}")
    except Exception as e:
        logger.error(f"Failed to write batch summary log: {e}")


def print_summary(result: PipelineResult, budget: BudgetTracker) -> None:
    """Print processing summary to stdout."""
    print("\n" + "=" * 80)
    print("PIPELINE PROCESSING SUMMARY")
    print("=" * 80)
    print(f"Volume: {result.volume_name}")
    print(f"Total cases: {len(result.cases)}")
    print(f"High confidence: {result.confidence_summary['high_confidence']}")
    print(f"Low confidence: {result.confidence_summary['low_confidence']}")
    print(f"OCR corrections: {len(result.corrections)}")
    print(f"LLM calls: {result.llm_calls}")
    print(f"LLM cost: ${result.llm_cost:.4f}")
    print(f"Budget remaining: ${budget.budget_remaining:.4f}")
    
    # Show diagnostics warnings/criticals only
    if result.diagnostics and result.diagnostics["worst_severity"] != "ok":
        print(f"\n  DIAGNOSTICS: {result.diagnostics['worst_severity'].upper()}")
        for check in result.diagnostics["checks"]:
            if check["severity"] != "ok":
                marker = "!" if check["severity"] == "warning" else "!!"
                print(f"    {marker} {check['message']}")
        nm_count = result.diagnostics.get("near_miss_count", 0)
        if nm_count > 0:
            print(f"    {nm_count} near-miss pattern matches (see .log for details)")
    
    print("=" * 80)


def print_batch_summary(summary: Dict[str, Any]) -> None:
    """Print batch processing summary to stdout."""
    print("\n" + "=" * 80)
    print("BATCH PROCESSING SUMMARY")
    print("=" * 80)
    print(f"Volumes processed: {summary['volumes_processed']}")
    print(f"Total cases: {summary['total_cases']}")
    print(f"Total LLM calls: {summary['total_llm_calls']}")
    print(f"Total LLM cost: ${summary['total_llm_cost']:.4f}")
    print(f"Total OCR corrections: {summary['total_ocr_corrections']}")
    print(f"Budget remaining: ${summary['budget_remaining']:.4f}")
    print("\nVolume details:")
    for vol in summary['volume_results']:
        print(f"  - {vol['volume']}: {vol['cases']} cases, "
              f"{vol['llm_calls']} LLM calls, ${vol['llm_cost']:.4f}")
    print("=" * 80)


if __name__ == "__main__":
    """Test the pipeline with Volume 226."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test pipeline with a single volume")
    parser.add_argument("volume_path", type=Path, help="Path to volume text file")
    parser.add_argument("-o", "--output", type=Path, help="Output JSON path")
    parser.add_argument("--budget", type=float, default=5.0, help="LLM budget in USD")
    parser.add_argument("--threshold", type=float, default=0.7, 
                       help="Confidence threshold for LLM fallback")
    parser.add_argument("--skip-llm", action="store_true",
                       help="Skip LLM fallback entirely")
    parser.add_argument("--force", action="store_true",
                       help="Force reprocessing even if manifest says up to date")

    args = parser.parse_args()

    # Set default output path if not provided
    if not args.output:
        args.output = args.volume_path.with_suffix(".predicted.json")

    try:
        result = process_volume(
            volume_path=args.volume_path,
            output_path=args.output,
            llm_budget=args.budget,
            confidence_threshold=args.threshold,
            skip_llm=args.skip_llm,
            force=args.force
        )
        print(f"\nPipeline completed successfully!")
        print(f"Output written to: {args.output}")
    except Exception as e:
        print(f"Pipeline failed: {e}")
        sys.exit(1)
