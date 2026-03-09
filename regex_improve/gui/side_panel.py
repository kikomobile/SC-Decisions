"""Side Panel — Annotation List + Case Navigator"""
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable, List
from gui.constants import LABELS, LABEL_MAP
from gui.models import Case, VolumeData


class SidePanel(tk.Frame):
    """Right panel containing case navigator, annotation list, and label buttons."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, width=300, **kwargs)
        self.pack_propagate(False)  # Maintain fixed width

        # Callbacks (set by app.py after construction)
        self.on_navigate: Optional[Callable[[int], None]] = None  # called with case index
        self.on_label_click: Optional[Callable[[str], None]] = None  # called with label key
        self.on_delete: Optional[Callable[[], None]] = None
        self.on_annotation_click: Optional[Callable[[int], None]] = None  # click item in list

        # State
        self._current_case_index: int = -1  # no case selected
        self._total_cases: int = 0
        self._current_case: Optional[Case] = None

        self._create_case_navigator()
        self._create_annotation_list()
        self._create_label_buttons()

    def _create_case_navigator(self):
        """Create the case navigation section at the top.

        Layout:
        ┌───────────────────────────┐
        │  Case Navigator           │
        │  [◄]  Case 0/0  [►]      │
        │  Status: (none)           │
        │  Notes: [text entry]      │
        └───────────────────────────┘

        - self.nav_frame: LabelFrame with title "Case Navigator"
        - self.prev_btn: Button "◄" — calls self._navigate(-1)
        - self.next_btn: Button "►" — calls self._navigate(+1)
        - self.case_label: Label showing "Case N/M"
        - self.status_label: Label showing case status
        - self.notes_entry: Entry widget for case notes
        """
        self.nav_frame = tk.LabelFrame(self, text="Case Navigator", padx=10, pady=10)
        self.nav_frame.pack(fill=tk.X, padx=5, pady=(5, 10))

        # Navigation buttons and case label
        nav_buttons_frame = tk.Frame(self.nav_frame)
        nav_buttons_frame.pack(fill=tk.X, pady=(0, 10))

        self.prev_btn = tk.Button(
            nav_buttons_frame, text="◄", width=3,
            command=lambda: self._navigate(-1)
        )
        self.prev_btn.pack(side=tk.LEFT)

        self.case_label = tk.Label(
            nav_buttons_frame, text="No cases", font=("Arial", 10, "bold")
        )
        self.case_label.pack(side=tk.LEFT, expand=True, padx=10)

        self.next_btn = tk.Button(
            nav_buttons_frame, text="►", width=3,
            command=lambda: self._navigate(1)
        )
        self.next_btn.pack(side=tk.RIGHT)

        # Status label
        status_frame = tk.Frame(self.nav_frame)
        status_frame.pack(fill=tk.X, pady=(0, 5))
        tk.Label(status_frame, text="Status:", width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.status_label = tk.Label(status_frame, text="(none)", anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Notes entry
        notes_frame = tk.Frame(self.nav_frame)
        notes_frame.pack(fill=tk.X, pady=(0, 5))
        tk.Label(notes_frame, text="Notes:", width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.notes_entry = tk.Entry(notes_frame)
        self.notes_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.notes_entry.bind("<KeyRelease>", self._on_notes_changed)

        # Disable buttons initially
        self.prev_btn.config(state=tk.DISABLED)
        self.next_btn.config(state=tk.DISABLED)

    def _create_annotation_list(self):
        """Create the scrollable annotation list.

        Layout:
        ┌───────────────────────────┐
        │  Annotations              │
        │  ┌───────────────────────┐│
        │  │ ☑ [case_number] G.R.  ││
        │  │ ☑ [date] November... ││
        │  │ ☐ [division] FIRST.. ││
        │  │ ...                   ││
        │  └───────────────────────┘│
        │  [Delete Selected]        │
        └───────────────────────────┘

        Use a ttk.Treeview with columns: checkbox, label, text (truncated).
        Or simpler: a tk.Listbox with Checkbutton widgets.

        Simpler approach (preferred): Use a ttk.Treeview with checkbutton column.
        Columns: "#0" (tree), "label", "text", "group"
        Each row represents one annotation.
        - Clicking a row scrolls the main text to that annotation's position
        - Selection (via checkbuttons or Treeview selection) enables Delete

        self.annotation_tree: ttk.Treeview
        self.delete_btn: Button "Delete Selected"
        """
        # Create frame for annotations section
        ann_frame = tk.LabelFrame(self, text="Annotations", padx=10, pady=10)
        ann_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 10))

        # Create Treeview with scrollbar
        tree_frame = tk.Frame(ann_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Create scrollbar
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Create Treeview
        self.annotation_tree = ttk.Treeview(
            tree_frame,
            columns=("label", "text", "group"),
            show="tree headings",
            height=10,
            yscrollcommand=scrollbar.set
        )
        scrollbar.config(command=self.annotation_tree.yview)

        # Configure columns
        self.annotation_tree.column("#0", width=30, stretch=False)  # Index column
        self.annotation_tree.column("label", width=100, stretch=False)
        self.annotation_tree.column("text", width=150)
        self.annotation_tree.column("group", width=50, stretch=False)

        # Configure headings
        self.annotation_tree.heading("#0", text="#")
        self.annotation_tree.heading("label", text="Label")
        self.annotation_tree.heading("text", text="Text")
        self.annotation_tree.heading("group", text="Group")

        self.annotation_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bind click event
        self.annotation_tree.bind("<ButtonRelease-1>", self._on_annotation_click)

        # Create Delete Selected button
        self.delete_btn = tk.Button(
            ann_frame,
            text="Delete Selected",
            command=self._on_delete_selected,
            state=tk.DISABLED
        )
        self.delete_btn.pack()

    def _create_label_buttons(self):
        """Create the label assignment buttons.

        Layout:
        ┌───────────────────────────┐
        │  Labels                   │
        │  [1] Start Case           │
        │  [2] Case Number          │
        │  [3] Date                 │
        │  ...                      │
        │  [X] End Case             │
        └───────────────────────────┘

        One button per label in LABELS. Button text = label.button_text.
        Button background tinted with label.color.
        Clicking calls self.on_label_click(label.key).
        """
        # Create frame for labels section
        labels_frame = tk.LabelFrame(self, text="Labels", padx=10, pady=10)
        labels_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        # Create buttons in a grid (2 columns)
        for i, label_def in enumerate(LABELS):
            row = i // 2
            col = i % 2
            
            # Create button with tinted background
            btn = tk.Button(
                labels_frame,
                text=label_def.button_text,
                command=lambda k=label_def.key: self._on_label_button_click(k),
                bg=label_def.color,
                activebackground=label_def.color,
                relief=tk.RAISED,
                padx=5,
                pady=2,
                width=12
            )
            btn.grid(row=row, column=col, padx=2, pady=2, sticky=tk.W+tk.E)
        
        # Configure grid columns to expand
        labels_frame.grid_columnconfigure(0, weight=1)
        labels_frame.grid_columnconfigure(1, weight=1)

    def update_case_display(self, case: Optional[Case], index: int, total: int):
        """Update the case navigator and annotation list for the given case.

        Args:
            case: The currently viewed Case, or None
            index: 0-based index of this case in the volume (display as 1-based)
            total: total number of cases in the volume

        Updates:
        1. Case label: "Case {index+1}/{total}" or "No cases" if total==0
        2. Status label: case.status or "(none)"
        3. Notes entry: case.notes or ""
        4. Annotation list: clear and repopulate with case.annotations
           Each row: label display_name, text (truncated to ~30 chars), group (if not None)
        5. Enable/disable ◄/► buttons based on index bounds
        """
        self._current_case_index = index
        self._total_cases = total
        self._current_case = case

        # Update case label
        if total == 0:
            self.case_label.config(text="No cases")
        else:
            self.case_label.config(text=f"Case {index + 1}/{total}")

        # Update status label
        if case:
            self.status_label.config(text=case.status)
            self.notes_entry.delete(0, tk.END)
            self.notes_entry.insert(0, case.notes)
        else:
            self.status_label.config(text="(none)")
            self.notes_entry.delete(0, tk.END)

        # Update navigation buttons
        self.prev_btn.config(state=tk.NORMAL if index > 0 else tk.DISABLED)
        self.next_btn.config(state=tk.NORMAL if index < total - 1 else tk.DISABLED)

        # Update annotation list
        self._update_annotation_list(case)

        # Update delete button state
        self.delete_btn.config(
            state=tk.NORMAL if case and case.annotations else tk.DISABLED
        )

    def _update_annotation_list(self, case: Optional[Case]):
        """Update the annotation treeview with case annotations."""
        # Clear existing items
        for item in self.annotation_tree.get_children():
            self.annotation_tree.delete(item)
        
        if not case or not case.annotations:
            return
        
        # Add each annotation to the treeview
        for i, annotation in enumerate(case.annotations):
            label_def = LABEL_MAP.get(annotation.label)
            label_name = label_def.display_name if label_def else annotation.label
            
            # Truncate text for display
            text_preview = annotation.text
            if len(text_preview) > 30:
                text_preview = text_preview[:27] + "..."
            
            # Format group display
            group_display = str(annotation.group) if annotation.group is not None else ""
            
            # Insert item with index as text in first column
            item_id = self.annotation_tree.insert(
                "", "end",
                text=str(i),  # Store annotation index in first column
                values=(label_name, text_preview, group_display),
                tags=(str(i),)  # Also store annotation index as tag
            )

    def _navigate(self, direction: int):
        """Navigate to previous (-1) or next (+1) case.
        Update self._current_case_index and call self.on_navigate callback.
        """
        new_index = self._current_case_index + direction
        if 0 <= new_index < self._total_cases:
            if self.on_navigate:
                self.on_navigate(new_index)

    def _on_notes_changed(self, event):
        """Handle notes entry changes."""
        if self._current_case and self.notes_entry:
            self._current_case.notes = self.notes_entry.get()

    def _on_label_button_click(self, label_key: str):
        """Handle label button clicks."""
        if self.on_label_click:
            self.on_label_click(label_key)

    def _on_annotation_click(self, event):
        """Handle annotation list clicks."""
        # Get selected item
        selection = self.annotation_tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        
        # Get annotation index from the item text
        try:
            item_text = self.annotation_tree.item(item_id, "text")
            annotation_index = int(item_text)
            if self.on_annotation_click:
                self.on_annotation_click(annotation_index)
        except (ValueError, TypeError):
            pass

    def _on_delete_selected(self):
        """Handle Delete Selected button click."""
        if self.on_delete:
            self.on_delete()

    def get_selected_annotation_indices(self) -> list[int]:
        """Return indices of selected annotations in the treeview."""
        indices = []
        for item_id in self.annotation_tree.selection():
            try:
                # Get the text from the first column (#0)
                item_text = self.annotation_tree.item(item_id, "text")
                index = int(item_text)
                indices.append(index)
            except (ValueError, TypeError):
                pass
        return indices
