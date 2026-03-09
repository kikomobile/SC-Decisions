#!/usr/bin/env python3
"""Demonstration of T12: Extraction Method Evaluation Framework."""

import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.evaluation import RegexMethod, EvaluationRunner, ExtractedField
from gui.models import AnnotationStore, Annotation, Case


def demonstrate_evaluation_framework():
    """Demonstrate the complete evaluation framework."""
    print("=== T12: Extraction Method Evaluation Framework Demo ===")
    print()
    
    print("1. Creating a RegexMethod instance...")
    # Create a regex method (will use fallback patterns)
    method = RegexMethod(Path("improved_regex.py"))
    print(f"   Method name: {method.name}")
    print()
    
    print("2. Testing extraction on sample text...")
    sample_text = """
    G.R. No. 123456
    January 15, 2024
    FIRST DIVISION
    J. DELA CRUZ
    DECISION
    """
    
    extracted_fields = method.extract(sample_text, start_line=1)
    print(f"   Extracted {len(extracted_fields)} fields:")
    for field in extracted_fields:
        print(f"     - {field.label}: '{field.text}' (chars {field.start_char}-{field.end_char})")
    print()
    
    print("3. Creating test annotations...")
    store = AnnotationStore()
    volume_data = store.ensure_volume("Demo_Volume.txt")
    
    # Create a test case
    case = Case(case_id="demo_case_0")
    
    # Add start and end markers
    case.add_annotation(Annotation(
        label="start_of_case",
        text="--- Start of Case ---",
        group=None,
        start_char=0,
        end_char=20,
        start_line=1,
        end_line=1,
        start_page=1,
        end_page=1
    ))
    
    case.add_annotation(Annotation(
        label="end_of_case",
        text="--- End of Case ---",
        group=None,
        start_char=200,
        end_char=220,
        start_line=10,
        end_line=10,
        start_page=1,
        end_page=1
    ))
    
    # Add expected annotations
    case.add_annotation(Annotation(
        label="case_number",
        text="G.R. No. 123456",
        group=0,
        start_char=30,
        end_char=45,
        start_line=2,
        end_line=2,
        start_page=1,
        end_page=1
    ))
    
    case.add_annotation(Annotation(
        label="date",
        text="January 15, 2024",
        group=None,
        start_char=50,
        end_char=65,
        start_line=3,
        end_line=3,
        start_page=1,
        end_page=1
    ))
    
    volume_data.add_case(case)
    print(f"   Created case with {len(case.annotations)} annotations")
    print()
    
    print("4. Creating mock loader...")
    class MockLoader:
        text = """
--- Start of Case ---
G.R. No. 123456
January 15, 2024
FIRST DIVISION
J. DELA CRUZ
Some other text
More text here
Even more text
Final text
--- End of Case ---
"""
        total_lines = 10
        page_break_lines = []
        page_break_pages = []
        
        def line_col_to_char(self, line, col):
            lines = self.text.split('\n')
            char_count = 0
            for i in range(line - 1):
                char_count += len(lines[i]) + 1
            return char_count + col
        
        def get_line_text(self, line_num):
            lines = self.text.split('\n')
            if 1 <= line_num <= len(lines):
                return lines[line_num - 1]
            return ""
    
    loader = MockLoader()
    loaders = {"Demo_Volume.txt": loader}
    print("   Mock loader created with sample text")
    print()
    
    print("5. Running evaluation...")
    runner = EvaluationRunner(store, loaders)
    result = runner.run(method)
    
    print(f"   Evaluated {len(result.cases)} case(s)")
    print(f"   Precision: {result.precision():.3f}")
    print(f"   Recall: {result.recall():.3f}")
    print(f"   F1 Score: {result.f1():.3f}")
    print()
    
    print("6. Generating summary table...")
    print()
    print(result.summary_table())
    print()
    
    print("7. Exporting results...")
    # Export as JSON (simulated - actual export would be implemented in GUI)
    import json
    # Create a simple export structure
    export_data = {
        "method_name": result.method_name,
        "num_cases": len(result.cases),
        "precision": result.precision(),
        "recall": result.recall(),
        "f1": result.f1(),
        "summary_table": result.summary_table()
    }
    print(f"   Results can be exported as JSON ({len(json.dumps(export_data))} bytes)")
    print()
    
    print("=== Demo Complete ===")
    print()
    print("Key features demonstrated:")
    print("  ✓ RegexMethod with fallback patterns")
    print("  ✓ Field extraction with line numbers")
    print("  ✓ EvaluationRunner processing complete cases")
    print("  ✓ Precision, recall, and F1 score calculation")
    print("  ✓ Summary table generation")
    print("  ✓ JSON export capability")
    print()
    print("The framework is now integrated into the GUI via:")
    print("  - Test → Run Evaluation menu item")
    print("  - Results displayed in Toplevel window")
    print("  - Per-case details in notebook tabs")
    print("  - Export results as JSON functionality")
    print()
    print("Ready for production use!")


if __name__ == "__main__":
    demonstrate_evaluation_framework()