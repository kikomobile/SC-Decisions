"""Highlight/Selection System + Label Assignment"""
import tkinter as tk
from tkinter import messagebox
from typing import Optional, Callable

from gui.constants import LABELS, LABEL_MAP, GROUPED_LABELS
from gui.models import Annotation, Case, VolumeData, AnnotationStore
from gui.volume_loader import VolumeLoader
from gui import dialogs


class HighlightManager:
    """Manages the creation and display of annotation highlights."""

    def __init__(self, text_panel, loader: VolumeLoader, store: AnnotationStore, 
                 volume_data: VolumeData, root: tk.Tk, on_change: Callable = None):
        self.text_panel = text_panel
        self.loader = loader
        self.store = store
        self.volume_data = volume_data
        self.root = root
        self.on_change = on_change
        self._tag_counter = 0  # for unique tag names
        self._setup_tag_colors()

    def _setup_tag_colors(self):
        """Pre-configure a Tkinter tag for each label's color.
        Tag name pattern: "label_{key}" with background=color.
        """
        for label_def in LABELS:
            self.text_panel.configure_tag(
                f"label_{label_def.key}",
                background=label_def.color
            )
        
        # Bold separator tags for case boundaries
        import tkinter.font as tkfont
        bold_font = tkfont.Font(family="Consolas", size=10, weight="bold")
        self.text_panel.configure_tag(
            "case_separator_start",
            background="#FFD700",
            foreground="#8B6914",
            font=bold_font,
            spacing1=8,
            spacing3=4
        )
        self.text_panel.configure_tag(
            "case_separator_end",
            background="#FFD700",
            foreground="#8B6914",
            font=bold_font,
            spacing1=4,
            spacing3=8
        )
        # Separators render below label highlights
        self.text_panel.text.tag_lower("case_separator_start")
        self.text_panel.text.tag_lower("case_separator_end")

    def create_annotation(self, label_key: str) -> Optional[Annotation]:
        """Create an annotation from the current selection or cursor position.

        Steps:
        1. Look up the LabelDef for label_key
        2. If selection_type == "selection":
           a. Get selection from text_panel.get_selection()
           b. If no selection, show warning messagebox and return None
           c. Get selected text via text_panel.text.get(start, end)
        3. If selection_type == "cursor":
           a. Get cursor line via text_panel.get_current_line()
           b. Set start = f"{line}.0", end = f"{line}.end"
           c. Get line text
        4. Convert Tk indices to char offsets via loader.tk_index_to_char()
        5. Derive line numbers via loader.char_to_line()
        6. Derive page numbers via loader.get_page()
        7. Determine group value:
           - If label_key not in GROUPED_LABELS → group = None
           - If label_key == "case_number" → handle via _assign_case_number_group()
           - If label_key == "parties" → handle via _assign_parties_group()
        8. Create Annotation object
        9. Find the active case at this position (or create one for start_of_case)
        10. Add annotation to case
        11. Apply visual highlight tag
        12. Return the annotation
        """
        # 1. Look up the LabelDef
        label_def = LABEL_MAP.get(label_key)
        if not label_def:
            messagebox.showerror("Error", f"Unknown label key: {label_key}")
            return None

        # 2-3. Get selection or cursor position
        if label_def.selection_type == "selection":
            selection = self.text_panel.get_selection()
            if not selection:
                messagebox.showwarning(
                    "No Selection",
                    f"Please select text before assigning '{label_def.display_name}' label."
                )
                return None
            start_tk, end_tk = selection
            text = self.text_panel.text.get(start_tk, end_tk)
        else:  # cursor type
            line = self.text_panel.get_current_line()
            start_tk = f"{line}.0"
            end_tk = f"{line}.end"
            text = self.text_panel.text.get(start_tk, end_tk)

        # 4. Convert Tk indices to char offsets
        start_char = self.loader.tk_index_to_char(start_tk)
        end_char = self.loader.tk_index_to_char(end_tk)

        # 5. Derive line numbers
        start_line = self.loader.char_to_line(start_char)
        end_line = self.loader.char_to_line(end_char - 1)  # end_char is exclusive

        # 6. Derive page numbers
        start_page = self.loader.get_page(start_line)
        end_page = self.loader.get_page(end_line)

        # 7. Determine group value
        group = None
        if label_key in GROUPED_LABELS:
            # Find or create case for this position
            case = self._find_or_create_case(label_key, start_line)
            if not case:
                return None
            
            if label_key == "case_number":
                group = self._assign_case_number_group(case)
                if group is None:  # User cancelled
                    return None
            elif label_key == "parties":
                group = self._assign_parties_group(case)
                if group is None:  # User cancelled
                    return None
        else:
            # For non-grouped labels, find existing case
            case = self._find_or_create_case(label_key, start_line)
            if not case:
                return None

        # 8. Create Annotation object
        annotation = Annotation(
            label=label_key,
            text=text,
            group=group,
            start_char=start_char,
            end_char=end_char,
            start_line=start_line,
            end_line=end_line,
            start_page=start_page,
            end_page=end_page
        )

        # 9-10. Add annotation to case (already found/created above)
        case.add_annotation(annotation)

        # 11. Apply visual highlight tag
        self._apply_highlight(annotation)

        # 12. Trigger change callback
        if self.on_change:
            self.on_change()
        
        # Refresh case separators
        self.refresh_separators()

        return annotation

    def _find_or_create_case(self, label_key: str, line: int) -> Optional[Case]:
        """Find the case that contains this line, or create one if label is start_of_case.

        Logic:
        - If label_key == "start_of_case":
          - Check no existing case already starts at this line
          - Create new Case with generated case_id
          - Add to volume_data
          - Return the new case
        - If label_key == "end_of_case":
          - Find the nearest preceding case that has a start_of_case but no end_of_case
          - If found, return it. If not, show warning and return None.
        - For all other labels:
          - Find the case at this line via volume_data.get_case_at_line(line)
          - If no case found, show warning: "No case at this position. Mark Start of Case first."
          - Return the case or None
        """
        if label_key == "start_of_case":
            # Check if a case already starts at this line
            for case in self.volume_data.cases:
                if case.get_start_line() == line:
                    messagebox.showwarning(
                        "Case Already Exists",
                        f"A case already starts at line {line}. Cannot create another start here."
                    )
                    return None
            
            # Create new case
            case_id = self.volume_data.generate_case_id()
            case = Case(case_id=case_id)
            self.volume_data.add_case(case)
            return case
        
        elif label_key == "end_of_case":
            # Find nearest preceding case without an end
            for case in reversed(self.volume_data.cases):
                if case.get_start_line() is not None and case.get_end_line() is None:
                    # This case has a start but no end
                    if line >= case.get_start_line():
                        return case
            
            messagebox.showwarning(
                "No Open Case",
                "No case without an end marker found. Mark Start of Case first."
            )
            return None
        
        else:
            # For other labels, find existing case at this line
            case = self.volume_data.get_case_at_line(line)
            if not case:
                messagebox.showwarning(
                    "No Case Found",
                    f"No case at line {line}. Please mark Start of Case first."
                )
            return case

    def _assign_case_number_group(self, case: Case) -> Optional[int]:
        """Determine group index for a new case_number annotation.
        - If case has 0 existing case_numbers → return 0
        - If case has 1+ existing case_numbers → prompt user:
          "Add as consolidated case number? (Group N)"
          - If yes → return case.next_group_index()
          - If no → return None (signal to caller to abort)
        """
        existing_case_numbers = case.get_annotations_by_label("case_number")
        if len(existing_case_numbers) == 0:
            return 0
        
        # Ask user if this should be a consolidated case number
        next_group = case.next_group_index()
        response = dialogs.ask_consolidated(self.root, next_group)
        return next_group if response else None

    def _assign_parties_group(self, case: Case) -> Optional[int]:
        """Determine group index for a new parties annotation.
        - If case is not consolidated (0-1 case_numbers) → return 0
        - If case is consolidated → prompt user:
          "Which case number does this parties block belong to?"
          Show existing case_numbers with their group indices as options.
          Return the selected group index.
        """
        if not case.is_consolidated:
            return 0
        
        # Get existing case numbers with their group indices and text
        case_numbers = []
        for annotation in case.get_annotations_by_label("case_number"):
            case_numbers.append((annotation.group, annotation.text))
        
        # Show dialog to select which case number this parties block belongs to
        selected_group = dialogs.ask_party_group(self.root, case_numbers)
        return selected_group

    def remove_annotation(self, case: Case, annotation_index: int) -> None:
        """Remove an annotation from a case and remove its highlight tag.
        1. Get the annotation at annotation_index
        2. Remove the Tkinter tag for this annotation
        3. Call case.remove_annotation(annotation_index)
        """
        if 0 <= annotation_index < len(case.annotations):
            annotation = case.annotations[annotation_index]
            
            # Remove highlight tag
            start_tk = self.loader.char_to_tk_index(annotation.start_char)
            end_tk = self.loader.char_to_tk_index(annotation.end_char)
            self.text_panel.remove_tag(f"label_{annotation.label}", start_tk, end_tk)
            
            # Remove from case
            case.remove_annotation(annotation_index)
            
            # Trigger change callback
            if self.on_change:
                self.on_change()
            
            # Refresh case separators
            self.refresh_separators()

    def apply_all_highlights(self) -> None:
        """Re-apply all highlight tags for the current volume.
        Called after loading a volume that already has annotations.
        Iterate all cases → all annotations → apply tag.
        """
        for case in self.volume_data.cases:
            for annotation in case.annotations:
                self._apply_highlight(annotation)
        
        # Apply case separators for complete cases
        self.refresh_separators()

    def _apply_highlight(self, annotation: Annotation) -> None:
        """Apply a highlight tag for a single annotation.
        Convert char offsets to Tk indices, apply tag with label's color.
        """
        start_tk = self.loader.char_to_tk_index(annotation.start_char)
        end_tk = self.loader.char_to_tk_index(annotation.end_char)
        self.text_panel.apply_tag(f"label_{annotation.label}", start_tk, end_tk)

    def refresh_separators(self) -> None:
        """Remove all separator tags, then re-apply for all cases.
        Apply case_separator_start to any start_of_case line.
        Apply case_separator_end to any end_of_case line.
        """
        # Remove all existing separator tags
        self.text_panel.remove_tag("case_separator_start")
        self.text_panel.remove_tag("case_separator_end")
        
        # Apply separators for all cases
        for case in self.volume_data.cases:
            start_annotations = case.get_annotations_by_label("start_of_case")
            end_annotations = case.get_annotations_by_label("end_of_case")

            if start_annotations:
                start_ann = start_annotations[0]
                start_line = start_ann.start_line
                start_tk = f"{start_line}.0"
                end_tk = f"{start_line}.end"
                self.text_panel.apply_tag("case_separator_start", start_tk, end_tk)

            if end_annotations:
                end_ann = end_annotations[0]
                end_line = end_ann.start_line
                start_tk = f"{end_line}.0"
                end_tk = f"{end_line}.end"
                self.text_panel.apply_tag("case_separator_end", start_tk, end_tk)
