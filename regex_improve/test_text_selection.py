#!/usr/bin/env python3
"""Test TextPanel text selection functionality"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.text_panel import TextPanel
import tkinter as tk
from pathlib import Path

def test_text_selection():
    """Test that text selection works in TextPanel."""
    
    # Create Tkinter window
    root = tk.Tk()
    root.title("TextPanel Text Selection Test")
    root.geometry("800x600")
    
    # Create TextPanel
    panel = TextPanel(root)
    panel.pack(fill=tk.BOTH, expand=True)
    
    # Load some test text
    test_text = "\n".join([f"Line {i}: This is test text for line {i}" for i in range(1, 101)])
    panel.load_text(test_text)
    
    # Configure a test tag
    panel.configure_tag("test_highlight", background="yellow")
    panel.apply_tag("test_highlight", "10.0", "15.0")
    
    # Test selection functionality
    def test_selection():
        print("Testing text selection functionality...")
        
        # Test 1: Get initial selection (should be None)
        selection = panel.get_selection()
        print(f"1. Initial selection: {selection}")
        
        # Test 2: Programmatically select some text
        panel.text.tag_add(tk.SEL, "20.0", "25.0")
        panel.text.mark_set(tk.INSERT, "25.0")
        
        # Give Tkinter time to update
        root.after(100, lambda: check_selection())
    
    def check_selection():
        # Test 3: Get selection after programmatic selection
        selection = panel.get_selection()
        print(f"2. After programmatic selection: {selection}")
        
        if selection:
            start, end = selection
            print(f"   Start: {start}, End: {end}")
            
            # Get selected text
            selected_text = panel.text.get(start, end)
            print(f"   Selected text: {repr(selected_text[:50])}...")
        
        # Test 4: Get cursor position
        cursor = panel.get_cursor_position()
        print(f"3. Cursor position: {cursor}")
        
        # Test 5: Get current line
        line = panel.get_current_line()
        print(f"4. Current line: {line}")
        
        print("\n✓ Text selection tests completed!")
        print("\nManual tests to perform:")
        print("1. Try selecting text with mouse (click and drag)")
        print("2. Verify selection highlight appears")
        print("3. Try using Shift+arrow keys to extend selection")
        print("4. Try Ctrl+A to select all")
        print("5. Try typing - should NOT modify text")
        print("6. Close window when done")
    
    # Schedule selection test
    root.after(500, test_selection)
    
    # Run the GUI
    print("Starting TextPanel Text Selection Test...")
    root.mainloop()

if __name__ == "__main__":
    test_text_selection()