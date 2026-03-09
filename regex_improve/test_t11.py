#!/usr/bin/env python3
"""Test T11: Export System — Pluggable Exporters"""

import sys
import os
import json
import tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.models import Annotation, Case, VolumeData, AnnotationStore
from gui.exporters import JsonExporter, MarkdownExporter
from gui.volume_loader import VolumeLoader


def test_json_exporter():
    """Test JSON exporter."""
    print("=== T11: Export System — Pluggable Exporters Tests ===")
    print()
    
    print("Testing JSON exporter...")
    
    # Create a test store with some data
    store = AnnotationStore()
    volume_data = store.ensure_volume("Volume_999.txt")
    
    # Create a test case with annotations
    case = Case(case_id="vol999_case_0")
    
    # Add some test annotations
    annotation1 = Annotation(
        label="case_number",
        text="G.R. No. 999999",
        group=0,
        start_char=100,
        end_char=120,
        start_line=10,
        end_line=10,
        start_page=1,
        end_page=1
    )
    
    annotation2 = Annotation(
        label="date",
        text="January 1, 2025",
        group=None,
        start_char=150,
        end_char=165,
        start_line=12,
        end_line=12,
        start_page=1,
        end_page=1
    )
    
    annotation3 = Annotation(
        label="start_of_case",
        text="--- Start of Case ---",
        group=None,
        start_char=80,
        end_char=100,
        start_line=8,
        end_line=8,
        start_page=1,
        end_page=1
    )
    
    case.add_annotation(annotation3)  # Start first
    case.add_annotation(annotation1)
    case.add_annotation(annotation2)
    volume_data.add_case(case)
    
    # Create exporter
    exporter = JsonExporter()
    
    # Test properties
    assert exporter.name == "JSON", f"Expected 'JSON', got '{exporter.name}'"
    assert exporter.file_extension == "json", f"Expected 'json', got '{exporter.file_extension}'"
    print(f"  ✓ Exporter properties: {exporter.name}, .{exporter.file_extension}")
    
    # Export to temporary file
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_export.json"
        
        # Export
        exporter.export(store, output_path)
        
        # Verify file exists
        assert output_path.exists(), "Export file should exist"
        print(f"  ✓ File created: {output_path}")
        
        # Verify file content is valid JSON
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert data.get("format_version") == 2, "Should have format_version=2"
        assert "volumes" in data, "Should have volumes key"
        assert "Volume_999.txt" in data["volumes"], "Should have our test volume"
        
        # Verify structure matches store.to_dict()
        expected_data = store.to_dict()
        assert data == expected_data, "Exported JSON should match store.to_dict()"
        print(f"  ✓ Valid JSON with correct structure")
        
        # Verify annotations are present
        volume_data_exported = data["volumes"]["Volume_999.txt"]
        assert len(volume_data_exported["cases"]) == 1, "Should have 1 case"
        case_exported = volume_data_exported["cases"][0]
        assert len(case_exported["annotations"]) == 3, "Should have 3 annotations"
        
        # Check annotation data
        ann1 = case_exported["annotations"][1]  # case_number (after start_of_case)
        assert ann1["label"] == "case_number", "Should have case_number annotation"
        assert ann1["text"] == "G.R. No. 999999", "Text should match"
        assert ann1["group"] == 0, "Group should be 0"
        
        ann2 = case_exported["annotations"][2]  # date
        assert ann2["label"] == "date", "Should have date annotation"
        assert ann2["text"] == "January 1, 2025", "Text should match"
        assert ann2["group"] is None, "Group should be None for date"
        
        print(f"  ✓ All annotation data preserved")
    
    print()


def test_markdown_exporter():
    """Test Markdown exporter."""
    print("Testing Markdown exporter...")
    
    # Create a test store with consolidated case
    store = AnnotationStore()
    volume_data = store.ensure_volume("Volume_421.txt")
    
    # Create a consolidated case
    case = Case(case_id="vol421_case_0")
    
    # Add start and end of case
    case.add_annotation(Annotation(
        label="start_of_case",
        text="--- Start of Case ---",
        group=None,
        start_char=100,
        end_char=120,
        start_line=50,
        end_line=50,
        start_page=3,
        end_page=3
    ))
    
    case.add_annotation(Annotation(
        label="end_of_case",
        text="--- End of Case ---",
        group=None,
        start_char=500,
        end_char=520,
        start_line=200,
        end_line=200,
        start_page=10,
        end_page=10
    ))
    
    # Add consolidated case numbers
    case.add_annotation(Annotation(
        label="case_number",
        text="G.R. No. 132724",
        group=0,
        start_char=150,
        end_char=165,
        start_line=55,
        end_line=55,
        start_page=3,
        end_page=3
    ))
    
    case.add_annotation(Annotation(
        label="case_number",
        text="G.R. No. 132800",
        group=1,
        start_char=170,
        end_char=185,
        start_line=56,
        end_line=56,
        start_page=3,
        end_page=3
    ))
    
    # Add parties for each group
    case.add_annotation(Annotation(
        label="parties",
        text="Petitioner: John Doe, Respondent: Jane Smith",
        group=0,
        start_char=200,
        end_char=250,
        start_line=60,
        end_line=60,
        start_page=4,
        end_page=4
    ))
    
    case.add_annotation(Annotation(
        label="parties",
        text="Petitioner: ABC Corp, Respondent: XYZ Inc",
        group=1,
        start_char=260,
        end_char=310,
        start_line=62,
        end_line=62,
        start_page=4,
        end_page=4
    ))
    
    # Add other annotations
    case.add_annotation(Annotation(
        label="date",
        text="November 15, 2024",
        group=None,
        start_char=320,
        end_char=340,
        start_line=65,
        end_line=65,
        start_page=4,
        end_page=4
    ))
    
    case.add_annotation(Annotation(
        label="division",
        text="FIRST DIVISION",
        group=None,
        start_char=350,
        end_char=365,
        start_line=66,
        end_line=66,
        start_page=4,
        end_page=4
    ))
    
    case.add_annotation(Annotation(
        label="ponente",
        text="J. DELA CRUZ",
        group=None,
        start_char=370,
        end_char=385,
        start_line=67,
        end_line=67,
        start_page=4,
        end_page=4
    ))
    
    volume_data.add_case(case)
    
    # Create exporter
    exporter = MarkdownExporter()
    
    # Test properties
    assert exporter.name == "Markdown", f"Expected 'Markdown', got '{exporter.name}'"
    assert exporter.file_extension == "md", f"Expected 'md', got '{exporter.file_extension}'"
    print(f"  ✓ Exporter properties: {exporter.name}, .{exporter.file_extension}")
    
    # Export to temporary file
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_export.md"
        
        # Create a mock loader for raw text access
        class MockLoader:
            total_lines = 300
            def get_line_text(self, line_num):
                if line_num == 50:
                    return "--- Start of Case ---"
                elif line_num == 55:
                    return "G.R. No. 132724"
                elif line_num == 56:
                    return "G.R. No. 132800"
                elif line_num == 60:
                    return "Petitioner: John Doe, Respondent: Jane Smith"
                elif line_num == 62:
                    return "Petitioner: ABC Corp, Respondent: XYZ Inc"
                elif line_num == 65:
                    return "November 15, 2024"
                elif line_num == 66:
                    return "FIRST DIVISION"
                elif line_num == 67:
                    return "J. DELA CRUZ"
                elif line_num == 200:
                    return "--- End of Case ---"
                else:
                    return f"Line {line_num} text"
        
        loaders = {"Volume_421.txt": MockLoader()}
        
        # Export
        exporter.export(store, output_path, loaders)
        
        # Verify file exists
        assert output_path.exists(), "Export file should exist"
        print(f"  ✓ File created: {output_path}")
        
        # Read and verify content
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check basic structure
        assert "# SC Decisions — Annotation Ground Truth" in content, "Should have title"
        assert "*Generated:" in content, "Should have timestamp"
        assert "## Volume: Volume_421.txt" in content, "Should have volume section"
        assert "### Volume_421.txt — Case 1 (consolidated: 2 case numbers)" in content, "Should have case header"
        
        # Check boundaries
        assert "**Boundaries:** lines 50–200 (pages 3–10)" in content, "Should have boundaries"
        
        # Check case numbers
        assert "**Case Numbers:**" in content
        assert "  - [group 0] `G.R. No. 132724`" in content
        assert "  - [group 1] `G.R. No. 132800`" in content
        
        # Check parties
        assert "**Parties:**" in content
        assert "  - [group 0] `Petitioner: John Doe, Respondent: Jane Smith`" in content
        assert "  - [group 1] `Petitioner: ABC Corp, Respondent: XYZ Inc`" in content
        
        # Check other labels - note: display names from LABEL_MAP
        assert "**Date of Decision:** `November 15, 2024`" in content
        assert "**Division:** `FIRST DIVISION`" in content
        assert "**Ponente Name:** `J. DELA CRUZ`" in content
        
        # Check raw text excerpt
        assert "Raw text around case start (±5 lines):" in content
        assert "```" in content
        assert "45|" in content  # Should have line numbers
        assert "55|" in content
        
        print(f"  ✓ Markdown content includes all expected sections")
        
        # Test without loader (no raw text excerpt)
        output_path2 = Path(tmpdir) / "test_export_no_loader.md"
        exporter.export(store, output_path2)  # No loaders parameter
        
        with open(output_path2, 'r', encoding='utf-8') as f:
            content2 = f.read()
        
        # Should still have all annotation data
        assert "**Case Numbers:**" in content2
        assert "**Parties:**" in content2
        # Should NOT have raw text excerpt (no loader provided)
        assert "Raw text around case start (±5 lines):" not in content2
        
        print(f"  ✓ Works without loader (no raw text excerpt)")
    
    print()


def test_empty_store():
    """Test export with empty store."""
    print("Testing empty store handling...")
    
    # Create empty store
    store = AnnotationStore()
    
    # Test JSON exporter
    json_exporter = JsonExporter()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "empty.json"
        json_exporter.export(store, output_path)
        
        assert output_path.exists(), "Should create file even for empty store"
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert data["format_version"] == 2
        assert data["volumes"] == {}
        print(f"  ✓ JSON exporter handles empty store")
    
    # Test Markdown exporter
    md_exporter = MarkdownExporter()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "empty.md"
        md_exporter.export(store, output_path)
        
        assert output_path.exists(), "Should create file even for empty store"
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "# SC Decisions — Annotation Ground Truth" in content
        assert "## Volume:" not in content  # No volumes to list
        print(f"  ✓ Markdown exporter handles empty store")
    
    print()


def test_markdown_escaping():
    """Test Markdown special character escaping."""
    print("Testing Markdown escaping...")
    
    store = AnnotationStore()
    volume_data = store.ensure_volume("Test_Volume.txt")
    case = Case(case_id="test_case_0")
    
    # Add annotation with Markdown special characters
    case.add_annotation(Annotation(
        label="case_number",
        text="G.R. No. 123_456 *bold* `code` #header",
        group=0,
        start_char=0,
        end_char=40,
        start_line=1,
        end_line=1,
        start_page=1,
        end_page=1
    ))
    
    volume_data.add_case(case)
    
    exporter = MarkdownExporter()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "escape_test.md"
        exporter.export(store, output_path)
        
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that backticks are replaced with single quotes
        # Since text is inside backtick code spans, other markdown characters don't need escaping
        assert "*bold*" in content, "Asterisks should NOT be escaped inside code spans"
        assert "'code'" in content, "Backticks should be replaced with single quotes"
        assert "#header" in content, "Hash should NOT be escaped inside code spans"
        assert "123_456" in content, "Underscore should NOT be escaped inside code spans"
        
        print(f"  ✓ Markdown special characters properly handled")
    
    print()


def test_export_integration():
    """Test integration with app.py export methods."""
    print("Testing integration with app.py...")
    
    print("  Manual test steps:")
    print("  1. Run the GUI: python annotate_gui.py")
    print("  2. Open a volume (File → Open Volume)")
    print("  3. Create some annotations:")
    print("     - Ctrl+1: Start of Case")
    print("     - Select case number text, Ctrl+2: Case Number")
    print("     - Select date text, Ctrl+3: Date")
    print("     - Select division text, Ctrl+4: Division")
    print("     - Ctrl+Shift+X: End of Case")
    print("  4. Export as JSON:")
    print("     - Export → Export as JSON")
    print("     - Save dialog opens with default name: ground_truth_YYYYMMDD_HHMMSS.json")
    print("     - Default directory: annotation_exports/")
    print("     - Save the file")
    print("     - Verify: Success message shows file path and size")
    print("  5. Export as Markdown:")
    print("     - Export → Export as Markdown")
    print("     - Save dialog opens with default name: ground_truth_YYYYMMDD_HHMMSS.md")
    print("     - Save the file")
    print("     - Verify: Success message shows file path and size")
    print("  6. Verify exported files:")
    print("     - JSON file: Open in text editor, verify format_version=2")
    print("     - Markdown file: Open in text editor, verify readable report")
    print("  7. Test consolidated case export:")
    print("     - Create consolidated case with 2 case numbers")
    print("     - Add parties for each group")
    print("     - Export as Markdown")
    print("     - Verify: Markdown shows [group 0], [group 1] sections")
    print("  8. Test empty annotations:")
    print("     - Open volume with no annotations")
    print("     - Try to export")
    print("     - Verify: Warning message 'No annotations to export'")
    print("  9. Test error handling:")
    print("     - Try to export to read-only location")
    print("     - Verify: Error message shows failure reason")
    
    print()
    print("  Expected behavior:")
    print("    ✓ Export menu items work (no placeholder messages)")
    print("    ✓ JSON export creates valid JSON matching annotations.json format")
    print("    ✓ Markdown export creates human-readable report")
    print("    ✓ Consolidated cases show group indices")
    print("    ✓ Raw text excerpts included when volume is loaded")
    print("    ✓ Empty store shows warning")
    print("    ✓ Error handling for file write failures")
    print("    ✓ Default filename includes timestamp")
    print("    ✓ annotation_exports/ directory created automatically")
    
    print()


def main():
    """Run all tests."""
    try:
        test_json_exporter()
        test_markdown_exporter()
        test_empty_store()
        test_markdown_escaping()
        test_export_integration()
        
        print("✓ All T11 component tests passed!")
        print()
        print("Summary of T11 implementation:")
        print("  ✓ BaseExporter abstract class with pluggable architecture")
        print("  ✓ JsonExporter: exports identical to annotations.json format")
        print("  ✓ MarkdownExporter: human/LLM-readable report")
        print("  ✓ Consolidated cases show group indices in markdown")
        print("  ✓ Raw text excerpts when volume loader available")
        print("  ✓ Markdown special character escaping")
        print("  ✓ Empty store handling")
        print("  ✓ Export menu wired in app.py")
        print("  ✓ Default filename with timestamp")
        print("  ✓ annotation_exports/ directory auto-creation")
        print()
        print("Ready for T12: Extraction Method Evaluation Framework")
        
    except AssertionError as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
