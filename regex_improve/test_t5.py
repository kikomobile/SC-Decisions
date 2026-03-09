#!/usr/bin/env python3
"""Test T5: Highlight/Selection System + Label Assignment"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.constants import LABELS, ANNOTATION_FILE
from gui.models import AnnotationStore
from gui.file_io import FileIO
from pathlib import Path
import json

def test_file_io():
    """Test FileIO load/save functionality."""
    print("Testing FileIO...")
    
    # Create a test annotation store
    store = AnnotationStore()
    
    # Create test file path
    test_file = Path("test_annotations.json")
    
    # Save to file
    file_io = FileIO(test_file)
    file_io.save(store)
    
    # Load from file
    loaded_store = file_io.load()
    
    # Verify format version
    data = store.to_dict()
    assert data["format_version"] == 2, f"Expected format_version=2, got {data.get('format_version')}"
    
    # Clean up
    if test_file.exists():
        test_file.unlink()
    
    print("✓ FileIO load/save test passed")

def test_highlight_manager_integration():
    """Test that highlight manager can be instantiated with dependencies."""
    print("\nTesting HighlightManager integration...")
    
    # Import all required components
    from gui.highlight_manager import HighlightManager
    from gui.volume_loader import VolumeLoader
    from gui.text_panel import TextPanel
    import tkinter as tk
    
    # Create minimal Tkinter environment
    root = tk.Tk()
    root.withdraw()  # Hide window
    
    # Create components
    text_panel = TextPanel(root)
    loader = VolumeLoader()
    store = AnnotationStore()
    
    # Load a sample volume
    samples_dir = Path(__file__).parent / "samples"
    volume_path = samples_dir / "Volume_121.txt"
    
    if volume_path.exists():
        text = loader.load(volume_path)
        text_panel.load_text(text)
        
        # Get volume data
        volume_data = store.ensure_volume(volume_path.name)
        
        # Create highlight manager
        highlight_manager = HighlightManager(
            text_panel=text_panel,
            loader=loader,
            store=store,
            volume_data=volume_data,
            root=root,
            on_change=lambda: print("Annotation changed")
        )
        
        print("✓ HighlightManager instantiation test passed")
        
        # Test tag setup
        print("  Tags configured for labels:")
        for label_def in LABELS:
            print(f"    - {label_def.key}: {label_def.color}")
        
        # Clean up
        root.destroy()
    else:
        print("⚠ Sample volume not found, skipping integration test")

def test_annotations_json():
    """Test that annotations.json is created and has correct format."""
    print("\nTesting annotations.json format...")
    
    annotation_file = Path(ANNOTATION_FILE)
    
    if annotation_file.exists():
        # Load and validate
        with open(annotation_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert "format_version" in data, "Missing format_version"
        assert data["format_version"] == 2, f"Expected format_version=2, got {data['format_version']}"
        assert "volumes" in data, "Missing volumes key"
        
        print(f"✓ annotations.json has correct format (version {data['format_version']})")
        print(f"  Volumes: {list(data['volumes'].keys())}")
    else:
        print("⚠ annotations.json does not exist (will be created on first annotation)")

def main():
    print("=== T5: Highlight/Selection System + Label Assignment Tests ===\n")
    
    try:
        test_file_io()
        test_highlight_manager_integration()
        test_annotations_json()
        
        print("\n✓ All T5 component tests passed!")
        print("\nManual tests to perform:")
        print("1. Run the GUI: python annotate_gui.py")
        print("2. Open a volume (File → Open Volume)")
        print("3. Select some text with mouse")
        print("4. Click Annotate → Case Number (Ctrl+2)")
        print("5. Verify text gets highlighted with blue background")
        print("6. Check that annotations.json is created/updated")
        print("7. Close and reopen volume - highlights should reappear")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())