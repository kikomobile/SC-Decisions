#!/usr/bin/env python3
"""SC Decisions — Case Annotation GUI"""
import sys
import os

# Ensure gui/ package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import AnnotationApp

def main():
    app = AnnotationApp()
    app.run()

if __name__ == "__main__":
    main()
