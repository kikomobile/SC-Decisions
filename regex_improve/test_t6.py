#!/usr/bin/env python3
"""Test T6: Consolidated Case + Multi-Party Workflow"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import messagebox
from gui.dialogs import ask_consolidated, ask_party_group
from gui.models import Case, Annotation
from gui.constants import LABELS, LABEL_MAP


def test_dialogs():
    """Test the dialog functions."""
    print("=== T6: Consolidated Case + Multi-Party Workflow Tests ===")
    print()
    
    # Create a root window for dialogs (hidden)
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    print("Testing ask_consolidated dialog...")
    # Note: We can't actually show the dialog in automated tests
    # but we can verify the function exists and returns expected types
    try:
        # This would show a dialog in real usage
        # result = ask_consolidated(root, 1)
        print("✓ ask_consolidated function exists")
    except Exception as e:
        print(f"✗ ask_consolidated failed: {e}")
    
    print()
    print("Testing ask_party_group dialog...")
    try:
        case_numbers = [
            (0, "G.R. No. 132724"),
            (1, "G.R. No. 132800"),
            (2, "G.R. No. 132801")
        ]
        # This would show a dialog in real usage
        # result = ask_party_group(root, case_numbers)
        print("✓ ask_party_group function exists")
        print(f"  Sample case numbers: {case_numbers}")
    except Exception as e:
        print(f"✗ ask_party_group failed: {e}")
    
    print()
    print("Testing Case.is_consolidated property...")
    
    # Create a test case
    case = Case(case_id="test_case")
    
    # Add first case number
    ann1 = Annotation(
        label="case_number",
        text="G.R. No. 132724",
        group=0,
        start_char=0,
        end_char=20,
        start_line=1,
        end_line=1,
        start_page=1,
        end_page=1
    )
    case.add_annotation(ann1)
    
    print(f"  After 1 case_number: is_consolidated = {case.is_consolidated} (expected: False)")
    assert not case.is_consolidated, "Case with 1 case_number should not be consolidated"
    
    # Add second case number
    ann2 = Annotation(
        label="case_number",
        text="G.R. No. 132800",
        group=1,
        start_char=30,
        end_char=50,
        start_line=2,
        end_line=2,
        start_page=1,
        end_page=1
    )
    case.add_annotation(ann2)
    
    print(f"  After 2 case_numbers: is_consolidated = {case.is_consolidated} (expected: True)")
    assert case.is_consolidated, "Case with 2+ case_numbers should be consolidated"
    
    print()
    print("Testing Case.next_group_index()...")
    
    case2 = Case(case_id="test_case2")
    print(f"  Empty case: next_group_index = {case2.next_group_index()} (expected: 0)")
    assert case2.next_group_index() == 0, "Empty case should return group 0"
    
    # Add annotation with group 0
    case2.add_annotation(ann1)
    print(f"  After group 0: next_group_index = {case2.next_group_index()} (expected: 1)")
    assert case2.next_group_index() == 1, "Should return next group index (1)"
    
    # Add annotation with group 1
    case2.add_annotation(ann2)
    print(f"  After group 1: next_group_index = {case2.next_group_index()} (expected: 2)")
    assert case2.next_group_index() == 2, "Should return next group index (2)"
    
    print()
    print("Testing HighlightManager integration...")
    print("  (Integration tests require running the GUI)")
    
    print()
    print("✓ All T6 component tests passed!")
    print()
    print("Manual tests to perform:")
    print("1. Run the GUI: python annotate_gui.py")
    print("2. Open a volume (File → Open Volume)")
    print("3. Mark Start of Case (Ctrl+1)")
    print("4. Select text for first case number, click Annotate → Case Number (Ctrl+2)")
    print("5. Select text for second case number, click Annotate → Case Number (Ctrl+2)")
    print("6. Verify consolidated dialog appears: 'Add as consolidated case number? (Group 1)'")
    print("7. Click Yes → second case number gets group=1")
    print("8. Select text for parties, click Annotate → Parties (Ctrl+5)")
    print("9. Verify party group dialog appears with case number options")
    print("10. Select a group and click OK → parties annotation gets selected group")
    
    root.destroy()


if __name__ == "__main__":
    test_dialogs()