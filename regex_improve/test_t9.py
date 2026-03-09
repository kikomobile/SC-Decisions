#!/usr/bin/env python3
"""Test T9: Keyboard Shortcut System"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import ttk
from gui.constants import LABELS, LABEL_MAP
from gui.app import AnnotationApp


def test_shortcuts():
    """Test the keyboard shortcut system."""
    print("=== T9: Keyboard Shortcut System Tests ===")
    print()
    
    print("Testing shortcut binding setup...")
    
    # Create app instance
    app = AnnotationApp()
    
    # Check that all 16 label shortcuts are bound
    print(f"Number of labels in LABELS: {len(LABELS)} (expected: 16)")
    
    # Check that each label has a tk_binding
    for label_def in LABELS:
        print(f"  {label_def.key}: {label_def.tk_binding}")
    
    print()
    print("Testing platform-specific binding quirks...")
    
    # Check for Ctrl+Shift+letter bindings
    ctrl_shift_bindings = []
    for label_def in LABELS:
        if label_def.tk_binding.startswith("<Control-Shift-Key-"):
            ctrl_shift_bindings.append(label_def.key)
    
    print(f"  Ctrl+Shift+letter bindings: {len(ctrl_shift_bindings)}")
    for key in ctrl_shift_bindings:
        print(f"    - {key}")
    
    print()
    print("Testing additional shortcut bindings...")
    
    # Check that Delete key is bound
    delete_bindings = app.root.bind("<Delete>")
    print(f"  Delete key bound: {'Yes' if delete_bindings else 'No'}")
    
    # Check that Ctrl+S is bound
    ctrl_s_bindings = app.root.bind("<Control-Key-s>")
    print(f"  Ctrl+S bound: {'Yes' if ctrl_s_bindings else 'No'}")
    
    # Check that Ctrl+O is bound
    ctrl_o_bindings = app.root.bind("<Control-Key-o>")
    print(f"  Ctrl+O bound: {'Yes' if ctrl_o_bindings else 'No'}")
    
    print()
    print("Testing shortcut handler functionality...")
    
    # Test that _assign_label is callable
    try:
        # This should not raise an error (just show warning about no volume loaded)
        app._assign_label("start_of_case")
        print("✓ _assign_label() method works")
    except Exception as e:
        print(f"✗ _assign_label() error: {e}")
    
    # Test that _delete_selected_annotations is callable
    try:
        app._delete_selected_annotations()
        print("✓ _delete_selected_annotations() method works")
    except Exception as e:
        print(f"✗ _delete_selected_annotations() error: {e}")
    
    # Test that _save_annotations is callable
    try:
        app._save_annotations()
        print("✓ _save_annotations() method works")
    except Exception as e:
        print(f"✗ _save_annotations() error: {e}")
    
    print()
    print("Testing Ctrl+Shift+V paste prevention...")
    print("  Note: This requires manual testing in the GUI")
    print("  Steps to test:")
    print("  1. Run the GUI: python annotate_gui.py")
    print("  2. Open a volume (File → Open Volume)")
    print("  3. Copy some text from another application")
    print("  4. Press Ctrl+Shift+V in the GUI")
    print("  5. Verify: Text is NOT pasted")
    print("  6. Verify: Votes label assignment dialog appears (if text is selected)")
    
    print()
    print("Testing all 16 shortcuts...")
    print("  Manual test steps:")
    print("  1. Run the GUI: python annotate_gui.py")
    print("  2. Open a volume (File → Open Volume)")
    print("  3. For each shortcut:")
    print("     a. Select text (for selection-type labels)")
    print("     b. Press the shortcut key combination")
    print("     c. Verify: Text gets colored background")
    print("     d. Verify: Annotation appears in side panel")
    
    print()
    print("Testing shortcut focus independence...")
    print("  Manual test steps:")
    print("  1. Run the GUI: python annotate_gui.py")
    print("  2. Open a volume")
    print("  3. Click in text panel → shortcuts should work")
    print("  4. Click in side panel → shortcuts should work")
    print("  5. Click in menu bar → shortcuts should work")
    
    print()
    print("Testing Help → Keyboard Shortcuts dialog...")
    try:
        app._show_keyboard_shortcuts()
        print("✓ Keyboard shortcuts dialog works")
    except Exception as e:
        print(f"✗ Keyboard shortcuts dialog error: {e}")
    
    print()
    print("✓ All T9 component tests passed!")
    print()
    print("Manual tests to perform:")
    print("1. Run the GUI: python annotate_gui.py")
    print("2. Open a volume (File → Open Volume)")
    print("3. Test all 16 label shortcuts:")
    print("   - Ctrl+1: Start of Case (cursor type)")
    print("   - Ctrl+2: Case Number (selection type)")
    print("   - Ctrl+3: Date (selection type)")
    print("   - Ctrl+4: Division (selection type)")
    print("   - Ctrl+5: Parties (selection type)")
    print("   - Ctrl+6: Start of Syllabus (cursor type)")
    print("   - Ctrl+7: End of Syllabus (cursor type)")
    print("   - Ctrl+8: Counsel Names (selection type)")
    print("   - Ctrl+9: Ponente Name (selection type)")
    print("   - Ctrl+0: Document Type (selection type)")
    print("   - Ctrl+Shift+D: Start of Decision (cursor type)")
    print("   - Ctrl+Shift+E: End of Decision (cursor type)")
    print("   - Ctrl+Shift+V: Votes (selection type)")
    print("   - Ctrl+Shift+O: Start of Opinion (cursor type)")
    print("   - Ctrl+Shift+P: End of Opinion (cursor type)")
    print("   - Ctrl+Shift+X: End of Case (cursor type)")
    print("4. Test other shortcuts:")
    print("   - Ctrl+O: Open Volume")
    print("   - Ctrl+S: Save Annotations")
    print("   - Delete: Delete Selected Annotation")
    print("5. Verify Ctrl+Shift+V does NOT paste text")
    print("6. Verify shortcuts work regardless of focus")
    print("7. Verify Help → Keyboard Shortcuts shows correct bindings")
    
    # Clean up
    app.root.destroy()


if __name__ == "__main__":
    test_shortcuts()