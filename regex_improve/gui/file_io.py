"""File I/O for annotations.json with atomic writes."""
import json
import os
import tempfile
from pathlib import Path
from typing import Optional
from gui.models import AnnotationStore


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