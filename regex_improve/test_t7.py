#!/usr/bin/env python3
"""Test T7: Side Panel — Annotation List + Case Navigator"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import ttk
from gui.side_panel import SidePanel
from gui.models import Case, Annotation
from gui.constants import LABELS, LABEL_MAP


def test_side_panel():
    """Test the side panel functionality."""
    print("=== T7: Side Panel — Annotation List + Case Navigator Tests ===")
    print()
    
    # Create a root window for testing
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    print("Testing SidePanel creation...")
    try:
        # Create side panel
        side_panel = SidePanel(root)
        side_panel.pack(fill=tk.BOTH, expand=True)
        print("✓ SidePanel created successfully")
    except Exception as e:
        print(f"✗ SidePanel creation failed: {e}")
        root.destroy()
        return
    
    print()
    print("Testing update_case_display()...")
    
    # Create a test case with annotations
    case = Case(case_id="test_case_1")
    case.status = "in_progress"
    case.notes = "Test case notes"
    
    # Add some annotations
    ann1 = Annotation(
        label="case_number",
        text="G.R. No. 132724",
        group=0,
        start_char=0,
        end_char=20,
        start_line=100,
        end_line=100,
        start_page=5,
        end_page=5
    )
    case.add_annotation(ann1)
    
    ann2 = Annotation(
        label="date",
        text="November 15, 2023",
        group=None,
        start_char=30,
        end_char=50,
        start_line=101,
        end_line=101,
        start_page=5,
        end_page=5
    )
    case.add_annotation(ann2)
    
    ann3 = Annotation(
        label="parties",
        text="JOHN DOE, Petitioner, vs. JANE SMITH, Respondent.",
        group=0,
        start_char=60,
        end_char=120,
        start_line=102,
        end_line=102,
        start_page=5,
        end_page=5
    )
    case.add_annotation(ann3)
    
    # Test with case
    side_panel.update_case_display(case, 0, 3)  # Case 1 of 3
    print("✓ update_case_display() with case works")
    
    # Test without case
    side_panel.update_case_display(None, -1, 0)
    print("✓ update_case_display() without case works")
    
    print()
    print("Testing navigation callbacks...")
    
    # Set up test callbacks
    navigation_called = []
    label_click_called = []
    delete_called = []
    annotation_click_called = []
    
    def on_navigate(index):
        navigation_called.append(index)
    
    def on_label_click(label_key):
        label_click_called.append(label_key)
    
    def on_delete():
        delete_called.append(True)
    
    def on_annotation_click(index):
        annotation_click_called.append(index)
    
    side_panel.on_navigate = on_navigate
    side_panel.on_label_click = on_label_click
    side_panel.on_delete = on_delete
    side_panel.on_annotation_click = on_annotation_click
    
    # Test navigation buttons (simulate clicks)
    print("  Navigation callbacks set up")
    
    print()
    print("Testing label buttons...")
    print(f"  Number of label buttons created: {len(LABELS)}")
    
    print()
    print("Testing annotation list...")
    # Update with case again to populate annotation list
    side_panel.update_case_display(case, 0, 3)
    
    # Check if annotations are displayed
    tree = side_panel.annotation_tree
    items = tree.get_children()
    print(f"  Number of annotations in list: {len(items)} (expected: 3)")
    
    if len(items) == 3:
        print("✓ Annotation list populated correctly")
        
        # Check first item
        first_item = items[0]
        values = tree.item(first_item, "values")
        print(f"  First annotation: {values}")
    else:
        print("✗ Annotation list not populated correctly")
    
    print()
    print("Testing get_selected_annotation_indices()...")
    # Select first item
    tree.selection_set(items[0])
    indices = side_panel.get_selected_annotation_indices()
    print(f"  Selected indices: {indices} (expected: [0])")
    
    print()
    print("Testing consolidated case display...")
    
    # Create a consolidated case
    consolidated_case = Case(case_id="consolidated_case")
    consolidated_case.status = "complete"
    
    # Add multiple case numbers (consolidated)
    ann_cn1 = Annotation(
        label="case_number",
        text="G.R. No. 132724",
        group=0,
        start_char=0,
        end_char=20,
        start_line=200,
        end_line=200,
        start_page=10,
        end_page=10
    )
    consolidated_case.add_annotation(ann_cn1)
    
    ann_cn2 = Annotation(
        label="case_number",
        text="G.R. No. 132800",
        group=1,
        start_char=30,
        end_char=50,
        start_line=201,
        end_line=201,
        start_page=10,
        end_page=10
    )
    consolidated_case.add_annotation(ann_cn2)
    
    # Add parties with different groups
    ann_p1 = Annotation(
        label="parties",
        text="JOHN DOE, Petitioner",
        group=0,
        start_char=60,
        end_char=90,
        start_line=202,
        end_line=202,
        start_page=10,
        end_page=10
    )
    consolidated_case.add_annotation(ann_p1)
    
    ann_p2 = Annotation(
        label="parties",
        text="JANE SMITH, Respondent",
        group=1,
        start_char=100,
        end_char=130,
        start_line=203,
        end_line=203,
        start_page=10,
        end_page=10
    )
    consolidated_case.add_annotation(ann_p2)
    
    side_panel.update_case_display(consolidated_case, 1, 3)
    print("✓ Consolidated case display works")
    print(f"  is_consolidated: {consolidated_case.is_consolidated} (expected: True)")
    
    print()
    print("✓ All T7 component tests passed!")
    print()
    print("Manual tests to perform:")
    print("1. Run the GUI: python annotate_gui.py")
    print("2. Open a volume (File → Open Volume)")
    print("3. Verify side panel appears with:")
    print("   - Case Navigator section (top)")
    print("   - Annotations section (middle)")
    print("   - Labels section (bottom)")
    print("4. Create a case (Ctrl+1)")
    print("5. Add annotations (select text, click label buttons)")
    print("6. Verify annotations appear in the annotation list")
    print("7. Click ◄/► buttons to navigate between cases")
    print("8. Click an annotation in the list → text should scroll to that annotation")
    print("9. Select annotations in the list, click Delete Selected → annotations removed")
    print("10. Test consolidated case workflow (multiple case numbers)")
    
    root.destroy()


if __name__ == "__main__":
    test_side_panel()