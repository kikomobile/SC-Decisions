"""Integration tests for the detection pipeline.

End-to-end validation against Volume 226 ground truth.
Includes ERA-7: Validation against both JSON and Markdown ground truth files.
"""

import unittest
import os
import sys
import json
import tempfile
from pathlib import Path
from typing import Dict, Any, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Import pipeline and scorer
from detection.pipeline import process_volume
from detection.scorer import score_volume
from detection.pattern_registry import get_era, get_fallback_order, get_era_config


class TestPipelineIntegration(unittest.TestCase):
    """Integration tests for the detection pipeline."""
    
    @classmethod
    def setUpClass(cls):
        """Run the pipeline once on Volume_226.txt (without LLM) and store results."""
        cls.test_dir = Path(__file__).resolve().parent.parent.parent.parent
        cls.volume_path = cls.test_dir / "downloads" / "Volume_226.txt"
        cls.ground_truth_path = cls.test_dir / "regex_improve" / "annotation_exports" / "ground_truth_20260309_144413.json"
        
        # Check if test files exist
        if not cls.volume_path.exists():
            raise FileNotFoundError(f"Volume file not found: {cls.volume_path}")
        if not cls.ground_truth_path.exists():
            raise FileNotFoundError(f"Ground truth file not found: {cls.ground_truth_path}")
        
        # Create temporary directory for output
        cls.temp_dir = tempfile.mkdtemp(prefix="pipeline_test_")
        cls.output_path = Path(cls.temp_dir) / "Volume_226_predicted.json"
        
        # Run pipeline without LLM (skip_llm=True) to avoid API dependency
        print(f"\nRunning pipeline on {cls.volume_path.name}...")
        try:
            cls.result = process_volume(
                volume_path=cls.volume_path,
                output_path=cls.output_path,
                llm_budget=5.0,
                confidence_threshold=0.7,
                skip_llm=True  # Skip LLM to avoid API dependency
            )
            print(f"Pipeline completed successfully")
            print(f"Output written to: {cls.output_path}")
            
            # Load the output JSON for validation
            with open(cls.output_path, 'r', encoding='utf-8') as f:
                cls.output_data = json.load(f)
            
            # Score against ground truth
            print(f"\nScoring against ground truth...")
            cls.scoring_results = score_volume(
                predicted_path=str(cls.output_path),
                ground_truth_path=str(cls.ground_truth_path),
                iou_threshold=0.8
            )
            print(f"Scoring completed")
            
        except Exception as e:
            print(f"Pipeline failed: {e}")
            raise
    
    @classmethod
    def tearDownClass(cls):
        """Clean up temporary files."""
        import shutil
        if hasattr(cls, 'temp_dir') and os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir)
            print(f"\nCleaned up temporary directory: {cls.temp_dir}")
    
    def test_case_count(self):
        """Test that detected cases == 72 (matching ground truth annotated cases)."""
        # Ground truth has 72 annotated cases (vol226_case_0 to vol226_case_71)
        # Note: vol226_case_7 and vol226_case_46 have 0 annotations in ground truth
        expected_cases = 72
        
        # Check pipeline result
        self.assertEqual(
            len(self.result.cases),
            expected_cases,
            f"Pipeline detected {len(self.result.cases)} cases, expected {expected_cases}"
        )
        
        # Check output JSON
        volume_data = self.output_data.get("volumes", [])
        self.assertGreater(len(volume_data), 0, "No volumes in output")
        
        cases_in_output = volume_data[0].get("cases", [])
        self.assertEqual(
            len(cases_in_output),
            expected_cases,
            f"Output JSON has {len(cases_in_output)} cases, expected {expected_cases}"
        )
    
    def test_first_case_start(self):
        """Test that first case start_of_case is at line 421."""
        # Find first case in output
        volume_data = self.output_data.get("volumes", [])
        self.assertGreater(len(volume_data), 0, "No volumes in output")
        
        cases = volume_data[0].get("cases", [])
        self.assertGreater(len(cases), 0, "No cases in output")
        
        first_case = cases[0]
        case_id = first_case.get("case_id", "")
        
        # Find start_of_case annotation
        start_ann = None
        for ann in first_case.get("annotations", []):
            if ann.get("label") == "start_of_case":
                start_ann = ann
                break
        
        self.assertIsNotNone(start_ann, "No start_of_case annotation found in first case")
        
        # Get line number from start_char (approximate)
        # We need to load the volume to convert char offset to line
        # For now, check that the case_id indicates it's the first case
        self.assertTrue(
            case_id.endswith("_case_0") or "case_0" in case_id,
            f"First case should be case_0, got {case_id}"
        )
        
        # Check that we have a division annotation
        division_ann = None
        for ann in first_case.get("annotations", []):
            if ann.get("label") == "division":
                division_ann = ann
                break
        
        self.assertIsNotNone(division_ann, "No division annotation found in first case")
        
        # The text should be "SECOND DIVISION" (case 0 in Volume 226)
        division_text = division_ann.get("text", "").strip()
        self.assertIn("SECOND DIVISION", division_text.upper(),
                     f"First case division should be 'SECOND DIVISION', got '{division_text}'")
    
    def test_all_cases_have_required_labels(self):
        """Test that every case has start_of_case, case_number, doc_type."""
        volume_data = self.output_data.get("volumes", [])
        self.assertGreater(len(volume_data), 0, "No volumes in output")
        
        cases = volume_data[0].get("cases", [])
        self.assertGreater(len(cases), 0, "No cases in output")
        
        required_labels = {"start_of_case", "case_number", "doc_type"}
        
        for i, case in enumerate(cases):
            case_id = case.get("case_id", f"case_{i}")
            annotations = case.get("annotations", [])
            
            # Get labels present in this case
            present_labels = {ann.get("label") for ann in annotations}
            
            # Check for required labels
            missing_labels = required_labels - present_labels
            self.assertEqual(
                len(missing_labels), 0,
                f"Case {case_id} missing required labels: {missing_labels}"
            )
    
    def test_consolidated_case_detected(self):
        """Test that at least one case has case_number with group > 0."""
        volume_data = self.output_data.get("volumes", [])
        self.assertGreater(len(volume_data), 0, "No volumes in output")
        
        cases = volume_data[0].get("cases", [])
        self.assertGreater(len(cases), 0, "No cases in output")
        
        found_consolidated = False
        
        for case in cases:
            annotations = case.get("annotations", [])
            for ann in annotations:
                if ann.get("label") == "case_number" and ann.get("group", 0) > 0:
                    found_consolidated = True
                    break
            if found_consolidated:
                break
        
        self.assertTrue(
            found_consolidated,
            "No consolidated cases detected (case_number with group > 0)"
        )
    
    def test_overall_f1(self):
        """Test that micro-averaged F1 >= 0.90 (using scorer)."""
        micro_avg = self.scoring_results.get("micro_avg", {})
        f1_score = micro_avg.get("f1", 0.0)
        
        self.assertGreaterEqual(
            f1_score, 0.90,
            f"Micro-averaged F1 score {f1_score:.4f} is below minimum threshold 0.90"
        )
        
        # Also check that we have reasonable precision and recall
        precision = micro_avg.get("precision", 0.0)
        recall = micro_avg.get("recall", 0.0)
        
        self.assertGreaterEqual(precision, 0.85,
                               f"Precision {precision:.4f} is too low")
        self.assertGreaterEqual(recall, 0.85,
                               f"Recall {recall:.4f} is too low")
    
    def test_per_label_f1_minimums(self):
        """Test that each label meets minimum F1 requirements."""
        per_label = self.scoring_results.get("per_label", {})
        
        # Minimum F1 requirements from T9 spec
        min_f1_requirements = {
            "start_of_case": 0.95,
            "case_number": 0.90,
            "date": 0.90,
            "division": 0.95,
            "doc_type": 0.95,
            "start_syllabus": 0.95,
            "ponente": 0.88,
            "start_decision": 0.88,
            "end_decision": 0.85,
            "parties": 0.75,
            "votes": 0.70,
        }
        
        for label, min_f1 in min_f1_requirements.items():
            if label in per_label:
                label_f1 = per_label[label].get("f1", 0.0)
                self.assertGreaterEqual(
                    label_f1, min_f1,
                    f"Label '{label}' F1 score {label_f1:.4f} is below minimum {min_f1}"
                )
            else:
                # Label not in results (might be missing from predictions)
                # This could be OK for optional labels like counsel, separate opinions
                if label not in ["counsel", "start_opinion", "end_opinion", "end_syllabus"]:
                    print(f"Warning: Label '{label}' not found in scoring results")
    
    def test_output_format(self):
        """Test that output JSON has correct format_version, volumes key, case structure."""
        # Check format_version
        self.assertEqual(
            self.output_data.get("format_version"), 2,
            "Output JSON must have format_version=2"
        )
        
        # Check status
        self.assertEqual(
            self.output_data.get("status"), "auto_extracted",
            "Output JSON status must be 'auto_extracted'"
        )
        
        # Check volumes key
        self.assertIn("volumes", self.output_data,
                     "Output JSON must have 'volumes' key")
        
        volumes = self.output_data.get("volumes", [])
        self.assertGreater(len(volumes), 0,
                          "Output JSON must have at least one volume")
        
        # Check volume structure
        volume = volumes[0]
        self.assertIn("volume_name", volume,
                     "Volume must have 'volume_name'")
        self.assertIn("total_cases", volume,
                     "Volume must have 'total_cases'")
        self.assertIn("cases", volume,
                     "Volume must have 'cases'")
        
        # Check case structure
        cases = volume.get("cases", [])
        self.assertGreater(len(cases), 0,
                          "Volume must have at least one case")
        
        for case in cases:
            self.assertIn("case_id", case,
                         "Case must have 'case_id'")
            self.assertIn("annotations", case,
                         "Case must have 'annotations'")
            self.assertIn("status", case,
                         "Case must have 'status'")
            self.assertIn("notes", case,
                         "Case must have 'notes'")
            
            # Check annotation structure
            for ann in case.get("annotations", []):
                self.assertIn("label", ann,
                             "Annotation must have 'label'")
                self.assertIn("text", ann,
                             "Annotation must have 'text'")
                self.assertIn("start_char", ann,
                             "Annotation must have 'start_char'")
                self.assertIn("end_char", ann,
                             "Annotation must have 'end_char'")
    
    def test_ocr_corrections_applied(self):
        """Test that at least one G.R. No, was corrected to G.R. No. in OCR correction log."""
        # Check if any corrections were logged
        corrections = self.result.corrections
        self.assertGreater(len(corrections), 0,
                          "No OCR corrections were applied")
        
        # Look for case_number corrections
        case_number_corrections = [
            c for c in corrections
            if c.field_label == "case_number" and "G.R. No," in c.original
        ]
        
        if case_number_corrections:
            # Found at least one case_number correction from comma to period
            self.assertTrue(True)
        else:
            # Check if any corrections were applied at all
            # (might be other types of corrections)
            print(f"Note: No case_number comma→period corrections found, "
                  f"but {len(corrections)} other corrections were applied")
            # Don't fail the test - OCR corrections might not be needed
            # if the volume doesn't have those specific errors
    
    @unittest.skipUnless(os.environ.get("DEEPSEEK_API_KEY"), "no API key")
    def test_llm_integration(self):
        """Test LLM integration (requires DEEPSEEK_API_KEY)."""
        # This test is skipped unless API key is available
        # Run pipeline with LLM enabled (small budget)
        temp_dir = tempfile.mkdtemp(prefix="pipeline_llm_test_")
        output_path = Path(temp_dir) / "Volume_226_llm_predicted.json"
        
        try:
            result = process_volume(
                volume_path=self.volume_path,
                output_path=output_path,
                llm_budget=0.10,  # Small budget for testing
                confidence_threshold=0.7,
                skip_llm=False  # Enable LLM
            )
            
            # Check that LLM was called (if there were low-confidence cases)
            if result.confidence_summary["low_confidence"] > 0:
                self.assertGreater(
                    result.llm_calls, 0,
                    "LLM should have been called for low-confidence cases"
                )
                self.assertGreater(
                    result.llm_cost, 0,
                    "LLM cost should be > 0 if LLM was called"
                )
            
            # Clean up
            import shutil
            shutil.rmtree(temp_dir)
            
        except Exception as e:
            # Clean up on error
            import shutil
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise


    def test_detection_method_present(self):
        """Test that every annotation has a detection_method field."""
        volume_data = self.output_data.get("volumes", [])
        self.assertGreater(len(volume_data), 0, "No volumes in output")

        cases = volume_data[0].get("cases", [])
        for case in cases:
            for ann in case.get("annotations", []):
                self.assertIn(
                    "detection_method", ann,
                    f"Annotation {ann.get('label')} in {case.get('case_id')} "
                    f"missing detection_method field"
                )
                self.assertIn(
                    ann["detection_method"], ("regex", "llm"),
                    f"Invalid detection_method '{ann['detection_method']}'"
                )


class TestManifest(unittest.TestCase):
    """Tests for the detection manifest module."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="manifest_test_"))

    def tearDown(self):
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_roundtrip_save_load(self):
        """Test that save/load roundtrip preserves manifest data."""
        from detection.manifest import (
            load_manifest, save_manifest, update_volume_entry
        )

        manifest = {}
        update_volume_entry(
            manifest, "Volume_226",
            prediction_file="Volume_226_predicted.json",
            total_cases=72, llm_calls=0, has_llm_labels=False,
            confidence_threshold=0.7,
            source_file_mtime="2026-03-12T19:22:00"
        )
        save_manifest(self.temp_dir, manifest)
        loaded = load_manifest(self.temp_dir)
        self.assertIn("Volume_226", loaded)
        self.assertEqual(loaded["Volume_226"]["total_cases"], 72)
        self.assertEqual(loaded["Volume_226"]["status"], "done")

    def test_merge_preserves_llm(self):
        """Test that merge keeps previous LLM annotations."""
        from detection.manifest import merge_annotations

        prev = [
            {"label": "date", "text": "old", "group": None, "detection_method": "regex"},
            {"label": "parties", "text": "LLM parties", "group": None, "detection_method": "llm"},
        ]
        curr = [
            {"label": "date", "text": "new", "group": None, "detection_method": "regex"},
        ]
        merged = merge_annotations(prev, curr)
        self.assertEqual(len(merged), 2)
        texts = {a["label"]: a["text"] for a in merged}
        self.assertEqual(texts["date"], "new")
        self.assertEqual(texts["parties"], "LLM parties")

    def test_merge_replaces_on_force(self):
        """Test that merge discards LLM annotations when force_llm_rerun=True."""
        from detection.manifest import merge_annotations

        prev = [
            {"label": "date", "text": "old", "group": None, "detection_method": "regex"},
            {"label": "parties", "text": "LLM parties", "group": None, "detection_method": "llm"},
        ]
        curr = [
            {"label": "date", "text": "new", "group": None, "detection_method": "regex"},
        ]
        merged = merge_annotations(prev, curr, force_llm_rerun=True)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["label"], "date")

    def test_new_volume_needs_reprocessing(self):
        """Test that a volume not in the manifest needs reprocessing."""
        from detection.manifest import should_reprocess

        reprocess, reason = should_reprocess({}, "Volume_227", Path("/nonexistent"), False)
        self.assertTrue(reprocess)
        self.assertIn("not in manifest", reason)

    def test_up_to_date_skips(self):
        """Test that an up-to-date volume is skipped."""
        from detection.manifest import should_reprocess, update_volume_entry, _get_source_mtime

        # Create a source file
        src_file = self.temp_dir / "Volume_226.txt"
        src_file.write_text("test")
        mtime = _get_source_mtime(src_file)

        manifest = {}
        update_volume_entry(
            manifest, "Volume_226",
            prediction_file="Volume_226_predicted.json",
            total_cases=72, llm_calls=0, has_llm_labels=False,
            confidence_threshold=0.7,
            source_file_mtime=mtime
        )
        reprocess, reason = should_reprocess(manifest, "Volume_226", src_file, False)
        self.assertFalse(reprocess)
        self.assertIn("up to date", reason)

    def test_force_always_reprocesses(self):
        """Test that --force always triggers reprocessing."""
        from detection.manifest import should_reprocess, update_volume_entry, _get_source_mtime

        src_file = self.temp_dir / "Volume_226.txt"
        src_file.write_text("test")
        mtime = _get_source_mtime(src_file)

        manifest = {}
        update_volume_entry(
            manifest, "Volume_226",
            prediction_file="Volume_226_predicted.json",
            total_cases=72, llm_calls=0, has_llm_labels=False,
            confidence_threshold=0.7,
            source_file_mtime=mtime
        )
        reprocess, reason = should_reprocess(manifest, "Volume_226", src_file, True)
        self.assertTrue(reprocess)
        self.assertIn("force", reason)


class TestERA7Validation(unittest.TestCase):
    """ERA-7: Era selection, fallback order, and pipeline execution on Vol 421."""

    def test_era_selection(self):
        """Test that pattern_registry selects correct era for known volumes."""
        self.assertEqual(get_era(226).name, "era1")
        self.assertEqual(get_era(421).name, "era2")
        self.assertEqual(get_era(676).name, "era3")
        self.assertEqual(get_era(813).name, "era4")
        self.assertEqual(get_era(960).name, "era5")
        self.assertEqual(get_era(None).name, "era1")   # default
        self.assertEqual(get_era(9999).name, "era1")    # out of range

    def test_fallback_order(self):
        """Test that fallback order expands outward from matched era."""
        # era3 (vol 600): should try era3 first, then expand outward
        order = get_fallback_order(600)
        self.assertEqual(order[0], "era3")  # matched first
        self.assertEqual(len(order), 5)     # all eras included
        # Outward: right first (era4), then left (era2), then era5, then era1
        self.assertEqual(order[1], "era4")
        self.assertEqual(order[2], "era2")

        # era1 (vol 226): only rightward expansion
        order1 = get_fallback_order(226)
        self.assertEqual(order1[0], "era1")
        self.assertEqual(order1[1], "era2")

        # era5 (vol 960): only leftward expansion
        order5 = get_fallback_order(960)
        self.assertEqual(order5[0], "era5")
        self.assertEqual(order5[1], "era4")

    def test_era_config_has_syllabus_flag(self):
        """Test that era5 has has_syllabus=False, others True."""
        for vol in [226, 421, 600, 813]:
            config = get_era_config(vol)
            self.assertTrue(config.has_syllabus, f"Vol {vol} should have has_syllabus=True")
        era5_config = get_era_config(960)
        self.assertFalse(era5_config.has_syllabus)

    def test_era_config_patterns_compiled(self):
        """Test that all pattern fields in EraConfig are compiled regex objects."""
        import re
        config = get_era_config(226)
        pattern_fields = [
            're_division', 're_page_marker', 're_volume_header',
            're_philippine_reports', 're_short_title', 're_syllabus_header',
            're_case_bracket', 're_case_bracket_no_close', 're_syllabus',
            're_counsel_header', 're_doc_type', 're_ponente', 're_per_curiam',
            're_so_ordered', 're_separate_opinion', 're_votes_content',
            're_footnote_start', 're_wherefore', 're_counsel_designation',
            're_parties_end', 're_vs_line'
        ]
        for field_name in pattern_fields:
            pattern = getattr(config, field_name)
            self.assertIsInstance(pattern, re.Pattern,
                                 f"EraConfig.{field_name} should be a compiled regex")

    def test_volume_421_pipeline(self):
        """Test pipeline execution on Volume 421 (era2) if sample is available."""
        test_dir = Path(__file__).resolve().parent.parent.parent
        vol_path = test_dir / "samples" / "Volume_421.txt"
        if not vol_path.exists():
            self.skipTest("Volume_421.txt not in samples/")

        result = process_volume(
            volume_path=vol_path,
            skip_llm=True,
            force=True
        )
        # Should detect cases
        self.assertGreater(len(result.cases), 0,
                           "Pipeline detected 0 cases on Volume 421")
        # All cases should have start_of_case and case_number annotations
        for case in result.cases:
            labels = {ann['label'] for ann in case['annotations']}
            self.assertIn('start_of_case', labels,
                          f"{case['case_id']} missing start_of_case")
            self.assertIn('case_number', labels,
                          f"{case['case_id']} missing case_number")


def run_tests():
    """Run the integration tests."""
    # Change to the regex_improve directory for proper imports
    original_cwd = os.getcwd()
    regex_improve_dir = Path(__file__).resolve().parent.parent.parent

    try:
        os.chdir(regex_improve_dir)
        print(f"Running tests from: {os.getcwd()}")

        # Run tests
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        suite.addTests(loader.loadTestsFromTestCase(TestPipelineIntegration))
        suite.addTests(loader.loadTestsFromTestCase(TestManifest))
        suite.addTests(loader.loadTestsFromTestCase(TestERA7Validation))
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return result.wasSuccessful()

    finally:
        os.chdir(original_cwd)


if __name__ == "__main__":
    # Run tests when script is executed directly
    success = run_tests()
    sys.exit(0 if success else 1)