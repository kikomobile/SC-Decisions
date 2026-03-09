#!/usr/bin/env python3
"""Test script for T13: Status Bar + Polish"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import AnnotationApp
from gui.status_bar import StatusBar
import tkinter as tk

def test_status_bar():
    """Test the StatusBar class"""
    print("Testing StatusBar class...")
    
    root = tk.Tk()
    root.withdraw()  # Hide the window
    
    status_bar = StatusBar(root)
    
    # Test update_file
    status_bar.update_file("test_volume.txt")
    print("✓ update_file method works")
    
    # Test update_position
    status_bar.update_position(123, 5)
    print("✓ update_position method works")
    
    # Test update_cases
    status_bar.update_cases(10, 3)
    print("✓ update_cases method works")
    
    root.destroy()
    print("StatusBar tests passed!\n")

def test_app_creation():
    """Test that the app can be created"""
    print("Testing AnnotationApp creation...")
    
    app = AnnotationApp()
    
    # Check that status bar was created
    assert hasattr(app, 'status_bar'), "App should have status_bar attribute"
    assert isinstance(app.status_bar, StatusBar), "status_bar should be a StatusBar instance"
    
    # Check that menu state update method exists
    assert hasattr(app, '_update_menu_state'), "App should have _update_menu_state method"
    
    # Check that window close handler exists
    assert hasattr(app, '_on_window_close'), "App should have _on_window_close method"
    
    print("✓ App created successfully")
    print("✓ Status bar initialized")
    print("✓ Menu state management methods exist")
    print("✓ Window close handler exists")
    
    # Clean up
    app.root.destroy()
    print("AnnotationApp tests passed!\n")

def test_menu_state():
    """Test menu state management"""
    print("Testing menu state management...")
    
    app = AnnotationApp()
    
    # Initially, no volume is loaded, so menus should be disabled
    # (Note: _update_menu_state is called in __init__)
    
    # Simulate loading a volume
    app.loader = "mock_loader"  # Just a placeholder to indicate volume is loaded
    
    # Update menu state
    app._update_menu_state()
    
    print("✓ _update_menu_state method works")
    
    app.root.destroy()
    print("Menu state tests passed!\n")

def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing T13: Status Bar + Polish")
    print("=" * 60)
    
    try:
        test_status_bar()
        test_app_creation()
        test_menu_state()
        
        print("=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())