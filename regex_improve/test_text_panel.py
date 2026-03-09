#!/usr/bin/env python3
"""Test TextPanel with Volume_121.txt (80k lines)"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.volume_loader import VolumeLoader
from gui.text_panel import TextPanel
import tkinter as tk
from pathlib import Path
import time

def test_performance():
    """Test TextPanel performance with Volume_121.txt"""
    
    # Load the volume
    loader = VolumeLoader()
    volume_path = Path(__file__).parent / "samples" / "Volume_121.txt"
    
    print(f"Loading {volume_path.name}...")
    start_load = time.time()
    text = loader.load(volume_path)
    load_time = time.time() - start_load
    print(f"✓ Loaded in {load_time:.2f} seconds")
    print(f"  Lines: {loader.total_lines:,}")
    print(f"  Pages: {len(loader.page_break_lines)}")
    print(f"  Characters: {len(text):,}")
    
    # Create Tkinter window
    root = tk.Tk()
    root.title("TextPanel Performance Test - Volume_121.txt")
    root.geometry("1200x800")
    
    # Create TextPanel
    print("\nCreating TextPanel...")
    panel = TextPanel(root)
    panel.pack(fill=tk.BOTH, expand=True)
    
    # Load text into TextPanel
    print("Loading text into TextPanel...")
    start_display = time.time()
    panel.load_text(text)
    display_time = time.time() - start_display
    print(f"✓ Text displayed in {display_time:.2f} seconds")
    
    # Configure a test tag
    panel.configure_tag("test_highlight", background="yellow")
    
    # Test scrolling performance
    print("\nTesting scrolling performance...")
    
    def test_scroll():
        print("  Scrolling to line 40,000...")
        start_scroll = time.time()
        panel.scroll_to_line(40000)
        scroll_time = time.time() - start_scroll
        print(f"  ✓ Scrolled in {scroll_time:.2f} seconds")
        
        print("  Scrolling to line 1...")
        start_scroll = time.time()
        panel.scroll_to_line(1)
        scroll_time = time.time() - start_scroll
        print(f"  ✓ Scrolled in {scroll_time:.2f} seconds")
        
        print("  Scrolling to last line...")
        start_scroll = time.time()
        panel.scroll_to_line(loader.total_lines)
        scroll_time = time.time() - start_scroll
        print(f"  ✓ Scrolled in {scroll_time:.2f} seconds")
        
        # Apply a test highlight
        print("  Applying test highlight...")
        panel.apply_tag("test_highlight", "100.0", "105.0")
        print("  ✓ Test highlight applied")
        
        print("\n✓ All tests completed successfully!")
        print("\nInstructions:")
        print("1. Try scrolling with mouse wheel, scrollbar, or arrow keys")
        print("2. Verify line numbers update smoothly")
        print("3. Try selecting text with mouse")
        print("4. Close window when done")
    
    # Schedule scroll test after window is displayed
    root.after(1000, test_scroll)
    
    # Run the GUI
    print("\nStarting GUI... (close window to exit)")
    root.mainloop()

if __name__ == "__main__":
    test_performance()

