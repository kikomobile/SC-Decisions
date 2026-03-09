"""Pluggable export system for annotations."""
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
import json
from typing import Dict, Optional, List, Tuple

from gui.models import AnnotationStore, Case, Annotation, VolumeData
from gui.volume_loader import VolumeLoader
from gui.constants import LABELS, LABEL_MAP


class BaseExporter(ABC):
    """Abstract base class for annotation exporters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable exporter name."""
        ...

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """File extension without dot, e.g. 'json', 'md'."""
        ...

    @abstractmethod
    def export(self, store: AnnotationStore, output_path: Path,
               loaders: Dict[str, VolumeLoader] = None) -> None:
        """Export annotations to the given path.
        Args:
            store: the full annotation store
            output_path: path to write the export file
            loaders: optional dict of {volume_filename: VolumeLoader} for raw text access
        """
        ...


class JsonExporter(BaseExporter):
    """Exports annotations as JSON (identical to annotations.json format)."""

    @property
    def name(self) -> str:
        return "JSON"

    @property
    def file_extension(self) -> str:
        return "json"

    def export(self, store: AnnotationStore, output_path: Path,
               loaders: Dict[str, VolumeLoader] = None) -> None:
        """Write store.to_dict() as formatted JSON."""
        # Create directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Serialize to dict
        data = store.to_dict()
        
        # Write JSON with pretty formatting
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


class MarkdownExporter(BaseExporter):
    """Exports ground truth as human/LLM-readable markdown report."""

    @property
    def name(self) -> str:
        return "Markdown"

    @property
    def file_extension(self) -> str:
        return "md"

    def export(self, store: AnnotationStore, output_path: Path,
               loaders: Dict[str, VolumeLoader] = None) -> None:
        """Generate markdown report for all annotated cases.

        For each volume in the store:
          For each case in the volume:
            Output a section like:

            ### Volume_421.txt — Case 3 (consolidated: 2 case numbers)

            **Boundaries:** lines {start_line}–{end_line} (pages {start_page}–{end_page})

            **Case Numbers:**
              - [group 0] `{text}` (line {line}, chars {start_char}-{end_char})
              - [group 1] `{text}` (line {line}, chars {start_char}-{end_char})

            **Parties:**
              - [group 0] `{text}` (lines {start_line}-{end_line})
              - [group 1] `{text}` (lines {start_line}-{end_line})

            **Date:** `{text}` (line {line}, chars {start_char}-{end_char})
            **Division:** `{text}` (line {line})
            **Ponente:** `{text}` (line {line})
            **Document Type:** `{text}` (line {line})
            **Votes:** `{text}` (lines {start_line}-{end_line})

            If loaders is provided for this volume, also output:
            ```
            Raw text around case start (±5 lines):
            {line_number}| {line_text}
            ...
            ```

        Fields that have no annotations should show "(not annotated)".
        Grouped labels (case_number, parties) show each group separately.
        Non-grouped labels show once.
        """
        # Create directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        lines = []
        lines.append("# SC Decisions — Annotation Ground Truth")
        lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        lines.append("")
        
        # Process each volume
        for volume_name, volume_data in store.volumes.items():
            if not volume_data.cases:
                continue
                
            lines.append(f"## Volume: {volume_name}")
            lines.append("")
            
            # Get loader for this volume if available
            loader = loaders.get(volume_name) if loaders else None
            
            # Process each case
            for case_idx, case in enumerate(volume_data.cases):
                self._add_case_section(lines, case, case_idx, volume_name, loader)
                lines.append("")  # Add spacing between cases
        
        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

    def _add_case_section(self, lines: List[str], case: Case, case_idx: int,
                          volume_name: str, loader: Optional[VolumeLoader]) -> None:
        """Add a case section to the markdown report."""
        # Case header
        case_number_count = len(case.get_annotations_by_label("case_number"))
        consolidated_text = f" (consolidated: {case_number_count} case numbers)" if case.is_consolidated else ""
        lines.append(f"### {volume_name} — Case {case_idx + 1}{consolidated_text}")
        lines.append("")
        
        # Boundaries
        start_line = case.get_start_line()
        end_line = case.get_end_line()
        start_page = self._get_case_page(case, "start_of_case")
        end_page = self._get_case_page(case, "end_of_case")
        
        if start_line and end_line:
            lines.append(f"**Boundaries:** lines {start_line}–{end_line} (pages {start_page}–{end_page})")
        elif start_line:
            lines.append(f"**Boundaries:** line {start_line} onward (page {start_page})")
        else:
            lines.append("**Boundaries:** (not annotated)")
        lines.append("")
        
        # Grouped labels: case_number and parties
        self._add_grouped_label_section(lines, case, "case_number", "Case Numbers")
        self._add_grouped_label_section(lines, case, "parties", "Parties")
        
        # Non-grouped labels
        for label_key in ["date", "division", "ponente", "doc_type", "votes",
                         "counsel", "start_syllabus", "end_syllabus",
                         "start_decision", "end_decision", 
                         "start_opinion", "end_opinion"]:
            self._add_single_label_section(lines, case, label_key)
        
        # Raw text excerpt if loader is available
        if loader and start_line:
            self._add_raw_text_excerpt(lines, case, loader)

    def _add_grouped_label_section(self, lines: List[str], case: Case, 
                                   label_key: str, section_title: str) -> None:
        """Add a section for grouped labels (case_number, parties)."""
        annotations = case.get_annotations_by_label(label_key)
        if not annotations:
            lines.append(f"**{section_title}:** (not annotated)")
            lines.append("")
            return
        
        lines.append(f"**{section_title}:**")
        for ann in annotations:
            group_text = f" [group {ann.group}]" if ann.group is not None else ""
            lines.append(f"  -{group_text} `{self._escape_markdown(ann.text)}` "
                        f"(line {ann.start_line}, chars {ann.start_char}-{ann.end_char})")
        lines.append("")

    def _add_single_label_section(self, lines: List[str], case: Case, label_key: str) -> None:
        """Add a section for a single (non-grouped) label."""
        label_def = LABEL_MAP.get(label_key)
        if not label_def:
            return
            
        annotations = case.get_annotations_by_label(label_key)
        if not annotations:
            lines.append(f"**{label_def.display_name}:** (not annotated)")
            return
        
        # Take the first annotation (should be only one for non-grouped labels)
        ann = annotations[0]
        lines.append(f"**{label_def.display_name}:** `{self._escape_markdown(ann.text)}` "
                    f"(line {ann.start_line}, chars {ann.start_char}-{ann.end_char})")

    def _add_raw_text_excerpt(self, lines: List[str], case: Case, loader: VolumeLoader) -> None:
        """Add raw text excerpt around case start."""
        start_line = case.get_start_line()
        if not start_line:
            return
        
        # Get ±5 lines around case start
        start_excerpt = max(1, start_line - 5)
        end_excerpt = min(loader.total_lines, start_line + 5)
        
        lines.append("")
        lines.append("```")
        lines.append(f"Raw text around case start (±5 lines):")
        
        for line_num in range(start_excerpt, end_excerpt + 1):
            line_text = loader.get_line_text(line_num)
            # Escape backticks in the text
            escaped_text = line_text.replace('`', '\\`')
            lines.append(f"{line_num:6d}| {escaped_text}")
        
        lines.append("```")
        lines.append("")

    def _get_case_page(self, case: Case, label_key: str) -> str:
        """Get page number for a case boundary annotation."""
        annotations = case.get_annotations_by_label(label_key)
        if annotations:
            return str(annotations[0].start_page)
        return "?"

    def _escape_markdown(self, text: str) -> str:
        """Escape backticks for use inside inline code spans."""
        return text.replace('`', "'")


# Registry of available exporters
EXPORTERS = {
    "json": JsonExporter(),
    "md": MarkdownExporter(),
}