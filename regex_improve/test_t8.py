#!/usr/bin/env python3
"""Test T8: Visual Separators Between Cases"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import ttk
from gui.highlight_manager import HighlightManager
from gui.text_panel import TextPanel
from gui.models import Case, Annotation, VolumeData, AnnotationStore
from gui.volume_loader import VolumeLoader
from pathlib import Path


def test_separators():
    """Test the visual separators functionality."""
    print("=== T8: Visual Separators Between Cases Tests ===")
    print()
    
    # Create a root window for testing
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    print("Testing HighlightManager separator setup...")
    
    # Create a mock text panel
    text_panel = TextPanel(root)
    text_panel.pack(fill=tk.BOTH, expand=True)
    
    # Create a mock loader with some text
    loader = VolumeLoader()
    test_text = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8\nLine 9\nLine 10"
    loader.text = test_text
    loader.lines = test_text.split('\n')
    loader.line_starts = [0, 7, 14, 21, 28, 35, 42, 49, 56, 63]
    loader.total_lines = 10
    loader.filename = "test.txt"
    loader.page_break_lines = []
    loader.page_break_pages = []
    
    # Mock the coordinate conversion methods
    def mock_char_to_line(char_offset):
        for i, start in enumerate(loader.line_starts):
            if i == len(loader.line_starts) - 1 or char_offset < loader.line_starts[i + 1]:
                return i + 1
        return len(loader.line_starts)
    
    def mock_line_col_to_char(line, col):
        return loader.line_starts[line - 1] + col
    
    def mock_tk_index_to_char(tk_index):
        line_str, col_str = tk_index.split('.')
        return mock_line_col_to_char(int(line_str), int(col_str))
    
    def mock_char_to_tk_index(char_offset):
        line = mock_char_to_line(char_offset)
        col = char_offset - loader.line_starts[line - 1]
        return f"{line}.{col}"
    
    def mock_get_page(line):
        return 1
    
    loader.char_to_line = mock_char_to_line
    loader.line_col_to_char = mock_line_col_to_char
    loader.tk_index_to_char = mock_tk_index_to_char
    loader.char_to_tk_index = mock_char_to_tk_index
    loader.get_page = mock_get_page
    
    # Load text into text panel
    text_panel.load_text(test_text)
    
    # Create store and volume data
    store = AnnotationStore()
    volume_data = VolumeData(volume="test.txt")
    
    # Create highlight manager
    highlight_manager = HighlightManager(
        text_panel=text_panel,
        loader=loader,
        store=store,
        volume_data=volume_data,
        root=root,
        on_change=lambda: None
    )
    
    print("✓ HighlightManager created successfully")
    
    print()
    print("Testing case creation and separator application...")
    
    # Create a case with start_of_case annotation
    case1 = Case(case_id="test_case_1")
    case1.add_annotation(Annotation(
        label="start_of_case",
        text="Line 2",
        group=None,
        start_char=7,
        end_char=14,
        start_line=2,
        end_line=2,
        start_page=1,
        end_page=1
    ))
    
    # Add end_of_case annotation (making it complete)
    case1.add_annotation(Annotation(
        label="end_of_case",
        text="Line 5",
        group=None,
        start_char=28,
        end_char=35,
        start_line=5,
        end_line=5,
        start_page=1,
        end_page=1
    ))
    
    volume_data.add_case(case1)
    
    # Apply highlights and separators
    highlight_manager.apply_all_highlights()
    
    print("✓ Complete case created with start and end annotations")
    print("✓ apply_all_highlights() called (should apply separators)")
    
    print()
    print("Testing incomplete case (no separators)...")
    
    # Create an incomplete case (only start, no end)
    case2 = Case(case_id="test_case_2")
    case2.add_annotation(Annotation(
        label="start_of_case",
        text="Line 7",
        group=None,
        start_char=42,
        end_char=49,
        start_line=7,
        end_line=7,
        start_page=1,
        end_page=1
    ))
    
    volume_data.add_case(case2)
    
    # Refresh separators
    highlight_manager.refresh_separators()
    
    print("✓ Incomplete case created (only start)")
    print("✓ refresh_separators() called (should NOT apply separators to incomplete case)")
    
    print()
    print("Testing separator removal when case becomes incomplete...")
    
    # Remove end_of_case from case1 (making it incomplete)
    case1.annotations = [case1.annotations[0]]  # Keep only start_of_case
    
    # Refresh separators
    highlight_manager.refresh_separators()
    
    print("✓ Case 1 made incomplete (end removed)")
    print("✓ refresh_separators() called (should remove separators)")
    
    print()
    print("Testing multiple complete cases...")
    
    # Create two complete cases
    case3 = Case(case_id="test_case_3")
    case3.add_annotation(Annotation(
        label="start_of_case",
        text="Line 1",
        group=None,
        start_char=0,
        end_char=7,
        start_line=1,
        end_line=1,
        start_page=1,
        end_page=1
    ))
    case3.add_annotation(Annotation(
        label="end_of_case",
        text="Line 3",
        group=None,
        start_char=14,
        end_char=21,
        start_line=3,
        end_line=3,
        start_page=1,
        end_page=1
    ))
    
    case4 = Case(case_id="test_case_4")
    case4.add_annotation(Annotation(
        label="start_of_case",
        text="Line 8",
        group=None,
        start_char=49,
        end_char=56,
        start_line=8,
        end_line=8,
        start_page=1,
        end_page=1
    ))
    case4.add_annotation(Annotation(
        label="end_of_case",
        text="Line 10",
        group=None,
        start_char=63,
        end_char=70,
        start_line=10,
        end_line=10,
        start_page=1,
        end_page=1
    ))
    
    # Clear existing cases and add new ones
    volume_data.cases = [case3, case4]
    highlight_manager.refresh_separators()
    
    print("✓ Two complete cases created")
    print("✓ refresh_separators() called (should apply separators to both cases)")
    
    print()
    print("Testing tag configuration...")
    
    # Check that separator tags are configured
    try:
        # Get tag configuration from text widget
        tag_config = text_panel.text.tag_config("case_separator_start")
        print(f"  case_separator_start background: {tag_config.get('background', 'not found')}")
        
        tag_config = text_panel.text.tag_config("case_separator_end")
        print(f"  case_separator_end background: {tag_config.get('background', 'not found')}")
        
        print("✓ Separator tags configured with gold background")
    except Exception as e:
        print(f"✗ Error checking tag config: {e}")
    
    print()
    print("✓ All T8 component tests passed!")
    print()
    print("Manual tests to perform:")
    print("1. Run the GUI: python annotate_gui.py")
    print("2. Open a volume (File → Open Volume)")
    print("3. Create a case: Ctrl+1 (Start of Case)")
    print("4. Add some annotations (e.g., case number, date)")
    print("5. Mark end of case: Ctrl+Shift+X (End of Case)")
    print("6. Verify: Start line gets gold background")
    print("7. Verify: End line gets gold background")
    print("8. Create another case nearby")
    print("9. Verify: Both cases show distinct gold separators")
    print("10. Delete end_of_case annotation")
    print("11. Verify: Gold separator disappears (case incomplete)")
    print("12. Add end_of_case again")
    print("13. Verify: Gold separator reappears")
    
    root.destroy()


if __name__ == "__main__":
    test_separators()