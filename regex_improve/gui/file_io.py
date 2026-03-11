"""File I/O for annotations.json with atomic writes."""
import json
import os
import tempfile
from pathlib import Path
from typing import Optional
from gui.models import Annotation, AnnotationStore, Case, VolumeData


class FileIO:
    """Handles loading and saving annotations.json with atomic writes."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> AnnotationStore:
        """Load annotations from file.
        - If file doesn't exist, return empty AnnotationStore
        - If file exists, read JSON and deserialize:
          - Check for "format_version" key
          - If format_version == 2 → use AnnotationStore.from_dict()
          - If no format_version (old format) → show warning, return empty store
            (old format migration is out of scope — user can re-annotate)
        """
        if not self.path.exists():
            return AnnotationStore()
        
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Check if data is a dict (new format) vs list (old CLI format)
            if not isinstance(data, dict):
                print("Warning: annotations.json has old format (not a dict). Starting fresh.")
                return AnnotationStore()
            
            # Check format version
            format_version = data.get("format_version")
            if format_version == 2:
                return AnnotationStore.from_dict(data)
            else:
                # Old format or missing version
                print(f"Warning: annotations.json has unsupported format version: {format_version}")
                print("Starting with empty annotation store.")
                return AnnotationStore()
                
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # Corrupted file
            print(f"Error loading annotations.json: {e}")
            print("Starting with empty annotation store.")
            return AnnotationStore()

    def save(self, store: AnnotationStore) -> None:
        """Save annotations to file using atomic write.
        1. Serialize store to dict via store.to_dict()
        2. Write JSON to a temp file in the same directory
           (use tempfile.NamedTemporaryFile with delete=False, dir=self.path.parent)
        3. os.replace(temp_path, self.path) — atomic on all platforms
        4. This ensures no data corruption if the process crashes mid-write
        """
        # Create directory if it doesn't exist
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        # Serialize to dict
        data = store.to_dict()
        
        # Write to temp file
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=self.path.parent,
                delete=False,
                suffix='.tmp'
            ) as tmp:
                json.dump(data, tmp, indent=2, ensure_ascii=False)
                tmp_path = Path(tmp.name)
            
            # Atomic replace
            os.replace(tmp_path, self.path)
            
        except Exception as e:
            # Clean up temp file if it exists
            if 'tmp_path' in locals() and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except:
                    pass
            raise e


def load_predictions(path: Path, loader) -> AnnotationStore:
    """Load a pipeline predicted.json and convert to GUI AnnotationStore format.

    Args:
        path: Path to the predicted.json file
        loader: VolumeLoader instance (already loaded with the volume text)
               Used to compute start_line/end_line from char offsets.

    Returns:
        AnnotationStore with converted predictions
    """
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    store = AnnotationStore()

    # Handle pipeline format: volumes is a list
    volumes_raw = data.get("volumes", [])

    if isinstance(volumes_raw, list):
        # Pipeline format: list of volume dicts
        for vol_dict in volumes_raw:
            vol_name = vol_dict.get("volume_name", "")
            # Ensure .txt extension
            if not vol_name.endswith(".txt"):
                vol_name = vol_name + ".txt"

            volume_data = VolumeData(volume=vol_name)

            for case_dict in vol_dict.get("cases", []):
                case_id = case_dict.get("case_id", "unknown")
                status = case_dict.get("status", "in_progress")
                # Map "auto_extracted" to "in_progress" for GUI review
                if status == "auto_extracted":
                    status = "in_progress"
                notes = case_dict.get("notes", "")

                case = Case(case_id=case_id, status=status, notes=notes)

                for ann_dict in case_dict.get("annotations", []):
                    start_char = ann_dict.get("start_char", 0)
                    end_char = ann_dict.get("end_char", 0)

                    # Compute start_line/end_line from char offsets using loader
                    start_line = 1
                    end_line = 1
                    start_page = ann_dict.get("start_page") or 0
                    end_page = ann_dict.get("end_page") or 0

                    if loader and hasattr(loader, 'char_to_line'):
                        try:
                            start_line = loader.char_to_line(start_char)
                            end_line = loader.char_to_line(max(start_char, end_char - 1))
                        except (ValueError, IndexError):
                            pass
                        try:
                            if start_page == 0:
                                start_page = loader.get_page(start_char)
                            if end_page == 0:
                                end_page = loader.get_page(max(start_char, end_char - 1))
                        except (ValueError, IndexError):
                            pass

                    annotation = Annotation(
                        label=ann_dict.get("label", ""),
                        text=ann_dict.get("text", ""),
                        group=ann_dict.get("group"),
                        start_char=start_char,
                        end_char=end_char,
                        start_line=start_line,
                        end_line=end_line,
                        start_page=start_page,
                        end_page=end_page
                    )
                    case.annotations.append(annotation)

                volume_data.cases.append(case)

            store.volumes[vol_name] = volume_data

    elif isinstance(volumes_raw, dict):
        # Already in GUI format, use normal loading
        return AnnotationStore.from_dict(data)

    return store
