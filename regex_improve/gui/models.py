from dataclasses import dataclass, field
from typing import Optional, List, Dict
import json
from pathlib import Path

@dataclass
class Annotation:
    """A single annotated span or cursor position."""
    label: str              # key from constants.LABELS, e.g. "case_number"
    text: str               # selected text (for "selection" type) or full line text (for "cursor" type)
    group: Optional[int]    # 0, 1, 2... for case_number/parties; None for all others
    start_char: int         # 0-based character offset from start of file
    end_char: int           # 0-based character offset (exclusive)
    start_line: int         # 1-based line number
    end_line: int           # 1-based line number
    start_page: int         # page number derived from nearest preceding page marker
    end_page: int           # page number

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "label": self.label,
            "text": self.text,
            "group": self.group,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_page": self.start_page,
            "end_page": self.end_page
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Annotation':
        """Create Annotation from dict."""
        # Handle missing group key gracefully
        group = d.get("group")
        return cls(
            label=d["label"],
            text=d["text"],
            group=group,
            start_char=d["start_char"],
            end_char=d["end_char"],
            start_line=d["start_line"],
            end_line=d["end_line"],
            start_page=d["start_page"],
            end_page=d["end_page"]
        )


@dataclass
class Case:
    """A single case (possibly consolidated) with its annotations."""
    case_id: str                         # "vol421_case_0"
    annotations: List[Annotation] = field(default_factory=list)
    status: str = "in_progress"          # "in_progress" | "complete" | "exported"
    notes: str = ""

    @property
    def is_consolidated(self) -> bool:
        """True if more than one case_number annotation exists."""
        return len(self.get_annotations_by_label("case_number")) > 1

    def add_annotation(self, annotation: Annotation) -> None:
        """Append annotation to the list."""
        self.annotations.append(annotation)

    def remove_annotation(self, index: int) -> None:
        """Remove annotation at the given index."""
        if 0 <= index < len(self.annotations):
            del self.annotations[index]

    def get_annotations_by_label(self, label: str) -> List[Annotation]:
        """Return all annotations matching the given label key."""
        return [a for a in self.annotations if a.label == label]

    def get_start_line(self) -> Optional[int]:
        """Return line number of the start_of_case annotation, or None."""
        starts = self.get_annotations_by_label("start_of_case")
        return starts[0].start_line if starts else None

    def get_end_line(self) -> Optional[int]:
        """Return line number of the end_of_case annotation, or None."""
        ends = self.get_annotations_by_label("end_of_case")
        return ends[0].start_line if ends else None

    def next_group_index(self) -> int:
        """Return the next available group index (max existing group + 1, or 0)."""
        groups = [a.group for a in self.annotations
                  if a.group is not None]
        return max(groups) + 1 if groups else 0

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "case_id": self.case_id,
            "annotations": [a.to_dict() for a in self.annotations],
            "status": self.status,
            "notes": self.notes
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Case':
        """Create Case from dict."""
        case = cls(
            case_id=d["case_id"],
            status=d.get("status", "in_progress"),
            notes=d.get("notes", "")
        )
        for ann_dict in d.get("annotations", []):
            case.annotations.append(Annotation.from_dict(ann_dict))
        return case


@dataclass
class VolumeData:
    """All annotation data for one volume file."""
    volume: str                          # filename, e.g. "Volume_421.txt"
    cases: List[Case] = field(default_factory=list)

    def add_case(self, case: Case) -> None:
        """Append a case, keeping cases sorted by start_line."""
        self.cases.append(case)
        self.cases.sort(key=lambda c: c.get_start_line() or 0)

    def remove_case(self, case_id: str) -> None:
        """Remove a case by its case_id."""
        self.cases = [c for c in self.cases if c.case_id != case_id]

    def get_case_at_line(self, line: int) -> Optional[Case]:
        """Return the case whose start_line <= line <= end_line, or None."""
        for case in self.cases:
            sl = case.get_start_line()
            el = case.get_end_line()
            if sl is not None and sl <= line:
                if el is None or line <= el:
                    return case
        return None

    def get_case_by_id(self, case_id: str) -> Optional[Case]:
        """Return the case with the given ID, or None."""
        for case in self.cases:
            if case.case_id == case_id:
                return case
        return None

    def generate_case_id(self) -> str:
        """Generate the next case_id like 'vol421_case_5'."""
        # Extract volume number from filename
        import re
        m = re.search(r'(\d+)', self.volume)
        vol_num = m.group(1) if m else "0"
        existing = len(self.cases)
        return f"vol{vol_num}_case_{existing}"

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "volume": self.volume,
            "cases": [c.to_dict() for c in self.cases]
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'VolumeData':
        """Create VolumeData from dict."""
        volume_data = cls(volume=d["volume"])
        for case_dict in d.get("cases", []):
            volume_data.cases.append(Case.from_dict(case_dict))
        return volume_data


class AnnotationStore:
    """Top-level container: manages all volumes' annotation data."""

    def __init__(self):
        self.volumes: Dict[str, VolumeData] = {}  # filename -> VolumeData

    def get_volume(self, filename: str) -> Optional[VolumeData]:
        """Return VolumeData for the given filename, or None."""
        return self.volumes.get(filename)

    def ensure_volume(self, filename: str) -> VolumeData:
        """Return existing VolumeData or create a new empty one."""
        if filename not in self.volumes:
            self.volumes[filename] = VolumeData(volume=filename)
        return self.volumes[filename]

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict. Structure:
        {
            "format_version": 2,
            "volumes": {
                "Volume_421.txt": { "volume": "...", "cases": [...] },
                ...
            }
        }
        """
        return {
            "format_version": 2,
            "volumes": {
                name: vol.to_dict() for name, vol in self.volumes.items()
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'AnnotationStore':
        """Deserialize from dict. Must handle format_version=2 structure."""
        store = cls()
        volumes_data = data.get("volumes", {})
        for name, vol_dict in volumes_data.items():
            store.volumes[name] = VolumeData.from_dict(vol_dict)
        return store