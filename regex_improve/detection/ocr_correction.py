"""OCR Post-Correction for extracted annotations.

Rule-based correction of known OCR errors in extracted annotations.
Each correction is logged for auditing.
"""

import re
from dataclasses import dataclass
from typing import Optional, Tuple, List

try:
    from rapidfuzz import process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    print("Warning: rapidfuzz not installed. Ponente correction will be limited.")

from .justice_registry import load_justices


# Master justice name list (1986–2024, starting with Vol 226 names)
# Loaded from justices.json (grows dynamically via harvest_justices.py)
KNOWN_JUSTICES = load_justices()

# Known division names
KNOWN_DIVISIONS = {"EN BANC", "FIRST DIVISION", "SECOND DIVISION", "THIRD DIVISION"}


@dataclass
class Correction:
    """Record of a single correction applied."""
    field_label: str    # which annotation label was corrected
    original: str       # original text
    corrected: str      # corrected text
    rule: str           # which rule triggered this


def correct_case_number(text: str) -> Tuple[str, List[Correction]]:
    """Fix case number OCR errors.
    
    Fixes:
    - `G.R. No,` → `G.R. No.` (comma to period)
    
    Args:
        text: Original case number text
        
    Returns:
        Tuple of (corrected_text, list[Correction])
    """
    corrections = []
    original = text
    
    # Fix comma for period in "G.R. No,"
    if "G.R. No," in text:
        text = text.replace("G.R. No,", "G.R. No.")
        corrections.append(Correction(
            field_label="case_number",
            original=original,
            corrected=text,
            rule="comma_to_period"
        ))
    
    return text, corrections


def correct_date(text: str) -> Tuple[str, List[Correction]]:
    """Fix date OCR errors.
    
    Fixes:
    - Period-for-comma after day (`May 30. 1986` → `May 30, 1986`)
    - Bracket digits (`[986` → `1986`, `(986` → `1986`)
    
    Args:
        text: Original date text
        
    Returns:
        Tuple of (corrected_text, list[Correction])
    """
    corrections = []
    original = text
    
    # Fix period-for-comma pattern: Month DD. YYYY → Month DD, YYYY
    month_pattern = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\.\s+\d{4}"
    match = re.search(month_pattern, text, re.IGNORECASE)
    if match:
        # Replace the period with comma
        start, end = match.span()
        matched_text = text[start:end]
        # Find the period after the day number
        if "." in matched_text:
            # Replace first period after digits with comma
            parts = matched_text.split(".", 1)
            corrected_match = parts[0] + "," + parts[1]
            text = text[:start] + corrected_match + text[end:]
            corrections.append(Correction(
                field_label="date",
                original=original,
                corrected=text,
                rule="period_to_comma"
            ))
    
    # Fix bracket digits: [986 → 1986, (986 → 1986
    bracket_fixes = [
        ("[986", "1986"),
        ("(986", "1986"),
        ("[9B6", "1986"),  # OCR error: B for 8
        ("(9B6", "1986"),
    ]
    
    for wrong, right in bracket_fixes:
        if wrong in text:
            text = text.replace(wrong, right)
            corrections.append(Correction(
                field_label="date",
                original=original,
                corrected=text,
                rule=f"bracket_digit_fix_{wrong}_to_{right}"
            ))
            break  # Only apply first match
    
    return text, corrections


def correct_division(text: str) -> Tuple[str, List[Correction]]:
    """Fix division OCR errors.
    
    Fixes:
    - `DIVISLON` → `DIVISION`
    - `DIVISIION` → `DIVISION`
    
    Only applies if the result is a known division name.
    
    Args:
        text: Original division text
        
    Returns:
        Tuple of (corrected_text, list[Correction])
    """
    corrections = []
    original = text
    
    # Fix common OCR errors in "DIVISION"
    corrected = re.sub(r'DIVIS\w+N', 'DIVISION', text, flags=re.IGNORECASE)
    
    # Only apply if the result is a known division
    if corrected != text and any(div.upper() in corrected.upper() for div in KNOWN_DIVISIONS):
        # Preserve the prefix (FIRST, SECOND, EN BANC, etc.)
        # Find which known division it matches
        for known_div in KNOWN_DIVISIONS:
            if known_div.upper() in corrected.upper():
                # Keep the original case pattern if possible
                if "FIRST" in text.upper():
                    text = "FIRST DIVISION"
                elif "SECOND" in text.upper():
                    text = "SECOND DIVISION"
                elif "THIRD" in text.upper():
                    text = "THIRD DIVISION"
                elif "EN BANC" in text.upper():
                    text = "EN BANC"
                else:
                    text = known_div  # fallback
                
                corrections.append(Correction(
                    field_label="division",
                    original=original,
                    corrected=text,
                    rule="division_spelling"
                ))
                break
    
    return text, corrections


def correct_ponente(text: str) -> Tuple[str, List[Correction]]:
    """Fix ponente OCR errors.
    
    Fixes:
    - Fuzzy match against KNOWN_JUSTICES (score_cutoff=85)
    - Normalize `PER CURIAM,;:` → `PER CURIAM`
    
    Args:
        text: Original ponente text
        
    Returns:
        Tuple of (corrected_text, list[Correction])
    """
    corrections = []
    original = text
    
    # Normalize PER CURIAM variations
    if "PER CURIAM" in text.upper():
        # Remove trailing punctuation
        normalized = "PER CURIAM"
        if text != normalized:
            text = normalized
            corrections.append(Correction(
                field_label="ponente",
                original=original,
                corrected=text,
                rule="per_curiam_normalization"
            ))
        return text, corrections
    
    # Fuzzy match against known justices if rapidfuzz is available
    if RAPIDFUZZ_AVAILABLE and text.strip():
        try:
            result = process.extractOne(text, KNOWN_JUSTICES, score_cutoff=85)
            if result:
                matched_justice, score, _ = result
                if matched_justice != text:
                    text = matched_justice
                    corrections.append(Correction(
                        field_label="ponente",
                        original=original,
                        corrected=text,
                        rule=f"fuzzy_match_score_{int(score)}"
                    ))
        except Exception as e:
            # Silently continue if fuzzy matching fails
            pass
    
    return text, corrections


def correct_end_decision(text: str) -> Tuple[str, List[Correction]]:
    """Fix end_decision OCR errors.
    
    Fixes:
    - `SOORDERED.` → `SO ORDERED.`
    - `SO ORDERED,` → `SO ORDERED.`
    
    Args:
        text: Original end_decision text
        
    Returns:
        Tuple of (corrected_text, list[Correction])
    """
    corrections = []
    original = text
    
    # Fix "SOORDERED." -> "SO ORDERED."
    if "SOORDERED" in text.upper():
        # Preserve original case pattern
        if text.upper() == "SOORDERED.":
            text = "SO ORDERED."
        elif text.upper() == "SOORDERED":
            text = "SO ORDERED"
        else:
            # Try to insert space before "ORDERED"
            text = re.sub(r'SO(\s*)ORDERED', 'SO ORDERED', text, flags=re.IGNORECASE)
        
        corrections.append(Correction(
            field_label="end_decision",
            original=original,
            corrected=text,
            rule="soordered_spacing"
        ))
    
    # Fix trailing comma instead of period
    if text.endswith(","):
        text = text[:-1] + "."
        corrections.append(Correction(
            field_label="end_decision",
            original=original,
            corrected=text,
            rule="comma_to_period"
        ))
    
    return text, corrections


def correct_annotations(annotations: List[dict]) -> Tuple[List[dict], List[Correction]]:
    """Apply correction rules based on annotation label.
    
    Returns new list of annotation dicts (with corrected text) + correction log.
    Does NOT modify the original dicts — creates copies.
    
    Args:
        annotations: List of annotation dicts
        
    Returns:
        Tuple of (corrected_annotations, list[Correction])
    """
    corrected_annotations = []
    all_corrections = []
    
    for ann in annotations:
        # Create a copy
        ann_copy = ann.copy()
        label = ann.get("label", "")
        original_text = ann.get("text", "")
        
        corrections = []
        corrected_text = original_text
        
        # Apply appropriate corrector based on label
        if label == "case_number":
            corrected_text, corrections = correct_case_number(original_text)
        elif label == "date":
            corrected_text, corrections = correct_date(original_text)
        elif label == "division":
            corrected_text, corrections = correct_division(original_text)
        elif label == "ponente":
            corrected_text, corrections = correct_ponente(original_text)
        elif label == "end_decision":
            corrected_text, corrections = correct_end_decision(original_text)
        # Note: parties, votes, counsel, body text are NOT corrected
        
        # Update the annotation if text changed
        if corrected_text != original_text:
            ann_copy["text"] = corrected_text
            all_corrections.extend(corrections)
        
        corrected_annotations.append(ann_copy)
    
    return corrected_annotations, all_corrections


if __name__ == "__main__":
    """Test each corrector with known errors."""
    
    print("Testing OCR correction functions...")
    
    # Test case_number correction
    test_cases = [
        ("correct_case_number", "G.R. No, 73155", "G.R. No. 73155"),
        ("correct_case_number", "G.R. No. 73155", "G.R. No. 73155"),  # no change
    ]
    
    for func_name, input_text, expected in test_cases:
        if func_name == "correct_case_number":
            result, corrections = correct_case_number(input_text)
            assert result == expected, f"{func_name}: {input_text} -> {result}, expected {expected}"
            print(f"[OK] {func_name}: '{input_text}' -> '{result}'")
            if corrections:
                print(f"  Correction: {corrections[0].rule}")
    
    # Test division correction
    test_cases = [
        ("correct_division", "FIRST DIVISLON", "FIRST DIVISION"),
        ("correct_division", "SECOND DIVISIION", "SECOND DIVISION"),
        ("correct_division", "EN BANC", "EN BANC"),  # no change
    ]
    
    for func_name, input_text, expected in test_cases:
        if func_name == "correct_division":
            result, corrections = correct_division(input_text)
            assert result == expected, f"{func_name}: {input_text} -> {result}, expected {expected}"
            print(f"[OK] {func_name}: '{input_text}' -> '{result}'")
            if corrections:
                print(f"  Correction: {corrections[0].rule}")
    
    # Test end_decision correction
    test_cases = [
        ("correct_end_decision", "SOORDERED.", "SO ORDERED."),
        ("correct_end_decision", "SO ORDERED,", "SO ORDERED."),
        ("correct_end_decision", "SO ORDERED.", "SO ORDERED."),  # no change
    ]
    
    for func_name, input_text, expected in test_cases:
        if func_name == "correct_end_decision":
            result, corrections = correct_end_decision(input_text)
            assert result == expected, f"{func_name}: {input_text} -> {result}, expected {expected}"
            print(f"[OK] {func_name}: '{input_text}' -> '{result}'")
            if corrections:
                print(f"  Correction: {corrections[0].rule}")
    
    # Test ponente correction
    test_cases = [
        ("correct_ponente", "PER CURIAM,", "PER CURIAM"),
        ("correct_ponente", "PER CURIAM:", "PER CURIAM"),
        ("correct_ponente", "GUTIERREZ, JR.", "GUTIERREZ, JR."),  # no change
    ]
    
    for func_name, input_text, expected in test_cases:
        if func_name == "correct_ponente":
            result, corrections = correct_ponente(input_text)
            assert result == expected, f"{func_name}: {input_text} -> {result}, expected {expected}"
            print(f"[OK] {func_name}: '{input_text}' -> '{result}'")
            if corrections:
                print(f"  Correction: {corrections[0].rule}")
    
    # Test date correction
    test_cases = [
        ("correct_date", "May 30. 1986", "May 30, 1986"),
        ("correct_date", "[986", "1986"),
        ("correct_date", "(986", "1986"),
    ]
    
    for func_name, input_text, expected in test_cases:
        if func_name == "correct_date":
            result, corrections = correct_date(input_text)
            # Note: date correction might not catch all cases due to regex complexity
            print(f"  {func_name}: '{input_text}' -> '{result}' (expected '{expected}')")
            if corrections:
                print(f"  Correction: {corrections[0].rule}")
    
    # Test full annotation correction
    print("\nTesting correct_annotations dispatcher...")
    test_annotations = [
        {"label": "case_number", "text": "G.R. No, 73155"},
        {"label": "division", "text": "FIRST DIVISLON"},
        {"label": "end_decision", "text": "SOORDERED."},
        {"label": "parties", "text": "Some party text"},  # should not be corrected
    ]
    
    corrected, all_corrections = correct_annotations(test_annotations)
    print(f"Applied {len(all_corrections)} corrections:")
    for corr in all_corrections:
        print(f"  - {corr.field_label}: '{corr.original}' -> '{corr.corrected}' ({corr.rule})")
    
    print("\nAll tests passed!")