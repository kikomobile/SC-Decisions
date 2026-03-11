import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Optional
from datetime import datetime
from gui.constants import SAMPLES_DIR, ANNOTATION_FILE, LABELS, LABEL_MAP
from gui.volume_loader import VolumeLoader
from gui.text_panel import TextPanel
from gui.highlight_manager import HighlightManager
from gui.file_io import FileIO, load_predictions
from gui.models import AnnotationStore, VolumeData, Case
from gui.side_panel import SidePanel
from gui.exporters import JsonExporter, MarkdownExporter
from gui.evaluation import RegexMethod, EvaluationRunner
from gui.status_bar import StatusBar
from gui.correction_tracker import CorrectionTracker


class AnnotationApp:
    """Main application class. Creates the Tk root and orchestrates all components."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SC Decisions — Case Annotation Tool")
        self.root.geometry("1400x800")
        self.root.minsize(900, 600)

        # State
        self.current_file: Optional[Path] = None  # currently loaded volume path
        self.loader: Optional[VolumeLoader] = None  # volume loader instance
        self.text_panel: Optional[TextPanel] = None  # text panel instance
        self.store: AnnotationStore = AnnotationStore()  # annotation data store
        self.file_io: Optional[FileIO] = None  # file I/O handler
        self.highlight_manager: Optional[HighlightManager] = None  # highlight manager
        self.volume_data: Optional[VolumeData] = None  # volume-specific annotation data
        self._current_case: Optional[Case] = None  # current case being viewed
        self.correction_tracker: CorrectionTracker = CorrectionTracker()

        # Build UI
        self._create_menu_bar()
        self._create_layout()
        
        # Bind keyboard shortcuts
        self._bind_shortcuts()
        
        # Set up window close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        
        # Store menu references for state management
        self._menu_references = {
            "annotate": None,
            "export": None,
            "test": None
        }
        self._update_menu_state()

    def _create_menu_bar(self):
        """Create the menu bar with File, Annotate, Export, Test, Help menus.

        File menu:
          - Open Volume... (Ctrl+O) — opens file picker filtered to *.txt in SAMPLES_DIR
          - Save (Ctrl+S) — saves annotations (wired in T10)
          - Separator
          - Exit

        Annotate menu:
          - (placeholder items — wired in T9)
          - Mark Start of Case (Ctrl+1)
          - ... (one entry per label from LABELS)
          - Delete Selected Annotation (Delete key)

        Export menu:
          - Export as JSON
          - Export as Markdown

        Test menu:
          - Run Evaluation → Regex

        Help menu:
          - Keyboard Shortcuts — shows a dialog listing all shortcuts
          - About
        """
        menubar = tk.Menu(self.root, tearoff=0)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Volume... (Ctrl+O)", command=self.open_volume)
        file_menu.add_command(label="Import Predictions...", command=self.import_predictions)
        file_menu.add_command(label="Export Corrections...", command=self.export_corrections)
        file_menu.add_command(label="Save (Ctrl+S)", command=self._save_annotations)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        # Annotate menu
        annotate_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Annotate", menu=annotate_menu)
        
        # Add placeholder items for each label
        for label_def in LABELS:
            annotate_menu.add_command(
                label=f"{label_def.display_name} ({label_def.shortcut_display})",
                command=lambda k=label_def.key: self._assign_label(k)
            )
        
        annotate_menu.add_separator()
        annotate_menu.add_command(label="Delete Selected Annotation (Delete)", command=self._delete_selected)

        # Export menu
        export_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Export", menu=export_menu)
        export_menu.add_command(label="Export as JSON", command=self._export_json)
        export_menu.add_command(label="Export as Markdown", command=self._export_markdown)

        # Test menu
        test_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Test", menu=test_menu)
        test_menu.add_command(label="Run Evaluation → Regex", command=self._run_evaluation)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Keyboard Shortcuts", command=self._show_keyboard_shortcuts)
        help_menu.add_command(label="About", command=self._show_about)

    def _create_layout(self):
        """Create the three-panel layout using a PanedWindow.

        Layout:
        ┌────────────────────────────────┬───────────────────┐
        │   main_frame (expandable)      │ right_frame       │
        │   (will hold TextPanel in T4)  │ (fixed ~300px)    │
        │                                │ (SidePanel in T7) │
        ├────────────────────────────────┴───────────────────┤
        │   status_frame (will hold StatusBar in T13)        │
        └───────────────────────────────────────────────────-─┘

        Use tk.PanedWindow(orient=tk.HORIZONTAL) for the main/right split.
        The status bar frame is packed at the bottom with fill=X.
        The paned window fills the remaining space.
        """
        # Create status bar at the bottom
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Create paned window for main content
        self.paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Create TextPanel in main frame
        self.text_panel = TextPanel(self.paned)
        self.paned.add(self.text_panel)

        # Create SidePanel in right frame
        self.side_panel = SidePanel(self.paned)
        self.paned.add(self.side_panel)

        # Set initial sash position (main frame gets most space)
        self.paned.sash_place(0, 1100, 0)  # Position sash at 1100px from left

        # Set up side panel callbacks
        self._setup_side_panel_callbacks()

    def open_volume(self):
        """File → Open Volume handler.
        1. Show file picker (initialdir=SAMPLES_DIR, filetypes=[("Text files", "*.txt")])
        2. If user selects a file, store path in self.current_file
        3. Update window title to include filename
        4. Load text using VolumeLoader and display in TextPanel
        5. Load annotations from file
        6. Create highlight manager and apply existing highlights
        """
        # Get samples directory path
        samples_path = Path(__file__).parent.parent / SAMPLES_DIR
        
        # Show file picker
        file_path = filedialog.askopenfilename(
            initialdir=str(samples_path),
            title="Select Volume File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if file_path:
            try:
                self.current_file = Path(file_path)
                
                # Update window title
                self.root.title(f"SC Decisions — Case Annotation Tool — {self.current_file.name}")
                
                # Load volume using VolumeLoader
                self.loader = VolumeLoader()
                text = self.loader.load(self.current_file)
                
                # Display text in TextPanel
                self.text_panel.load_text(text)
                
                # Apply page marker styling
                self._apply_page_marker_styling()
                
                # Load annotations from file
                self.file_io = FileIO(Path(ANNOTATION_FILE))
                self.store = self.file_io.load()
                
                # Get or create volume data for this file
                self.volume_data = self.store.ensure_volume(self.current_file.name)
                
                # Create highlight manager
                self.highlight_manager = HighlightManager(
                    text_panel=self.text_panel,
                    loader=self.loader,
                    store=self.store,
                    volume_data=self.volume_data,
                    root=self.root,
                    on_change=self._on_annotation_change
                )
                
                # Apply existing highlights
                self.highlight_manager.apply_all_highlights()
                
                # Update status bar
                self.status_bar.update_file(self.current_file.name)
                self._update_status_bar_position()
                self._update_status_bar_cases()
                
                # Update side panel display
                self._update_side_panel_display()
                
                # Bind cursor movement to update side panel and status bar
                self.text_panel.text.bind("<ButtonRelease-1>", lambda e: self._on_cursor_move())
                self.text_panel.text.bind("<KeyRelease>", lambda e: self._on_cursor_move())
                
                # Set focus to text panel
                self.text_panel.text.focus_set()
                
                # Update menu state
                self._update_menu_state()
                
            except Exception as e:
                messagebox.showerror(
                    "Error Loading Volume",
                    f"Failed to load {file_path}:\n\n{str(e)}"
                )
                # Reset state on error
                self.current_file = None
                self.loader = None
                self.file_io = None
                self.highlight_manager = None
                self.volume_data = None
                self._update_menu_state()

    def import_predictions(self):
        """File > Import Predictions handler.
        Load a pipeline predicted.json and merge into the current volume's annotations.
        Requires a volume to be open first (need the VolumeLoader for line number computation).
        """
        if not self.loader or not self.current_file:
            messagebox.showwarning(
                "No Volume Open",
                "Open a volume file first, then import predictions for that volume."
            )
            return

        file_path = filedialog.askopenfilename(
            title="Import Predictions",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if not file_path:
            return

        try:
            pred_store = load_predictions(Path(file_path), self.loader)

            # Find the volume data matching the currently open volume
            volume_name = self.current_file.name
            pred_volume = pred_store.get_volume(volume_name)

            if pred_volume is None:
                # Try without .txt extension match
                available = list(pred_store.volumes.keys())
                messagebox.showwarning(
                    "Volume Not Found",
                    f"No predictions found for '{volume_name}' in the imported file.\n\n"
                    f"Available volumes: {', '.join(available) if available else 'none'}"
                )
                return

            # Confirm before replacing
            existing_cases = len(self.volume_data.cases) if self.volume_data else 0
            incoming_cases = len(pred_volume.cases)

            result = messagebox.askyesno(
                "Import Predictions",
                f"Import {incoming_cases} predicted cases for {volume_name}?\n\n"
                f"This will REPLACE the current {existing_cases} cases for this volume.\n"
                f"(Other volumes in annotations.json are not affected.)"
            )

            if not result:
                return

            # Replace volume data in the store
            self.store.volumes[volume_name] = pred_volume
            self.volume_data = pred_volume

            # Snapshot baseline for correction tracking
            self.correction_tracker.set_baseline(
                pred_volume, file_path, self.loader.text
            )

            # Clear existing highlights from text widget
            for tag in self.text_panel.text.tag_names():
                if tag.startswith("highlight_"):
                    self.text_panel.text.tag_remove(tag, "1.0", "end")
            
            # Recreate highlight manager with new data
            self.highlight_manager = HighlightManager(
                text_panel=self.text_panel,
                loader=self.loader,
                store=self.store,
                volume_data=self.volume_data,
                root=self.root,
                on_change=self._on_annotation_change
            )

            # Apply highlights for imported annotations
            self.highlight_manager.apply_all_highlights()

            # Save to annotations.json
            if self.file_io:
                self.file_io.save(self.store)

            # Update side panel and status bar
            self._update_side_panel_display()
            self._update_status_bar_cases()

            messagebox.showinfo(
                "Import Complete",
                f"Imported {incoming_cases} cases for {volume_name}.\n"
                f"Annotations saved to annotations.json."
            )

        except Exception as e:
            messagebox.showerror(
                "Import Error",
                f"Failed to import predictions:\n\n{str(e)}"
            )

    def export_corrections(self):
        """File > Export Corrections handler.
        Compute diff between baseline predictions and current annotations,
        then write a structured JSON file for Claude/Claude Code analysis.
        """
        if not self.correction_tracker.has_baseline():
            messagebox.showwarning(
                "No Baseline",
                "Import predictions first, then make corrections, then export."
            )
            return

        if not self.volume_data:
            messagebox.showwarning(
                "No Volume",
                "No volume data loaded."
            )
            return

        # Compute diff
        log = self.correction_tracker.compute_diff(self.volume_data)

        if log.summary.get("total_corrections", 0) == 0:
            messagebox.showinfo(
                "No Corrections",
                "No corrections detected. Predictions match current annotations."
            )
            return

        # Default output directory
        corrections_dir = Path(__file__).parent.parent / "corrections"
        vol_stem = Path(log.volume_name).stem
        default_name = f"{vol_stem}_corrections.json"

        file_path = filedialog.asksaveasfilename(
            initialdir=str(corrections_dir),
            initialfile=default_name,
            title="Export Corrections",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if not file_path:
            return

        try:
            out_path = Path(file_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)

            # Build corrections list grouped by case_id
            corrections_out = []
            for c in log.corrections:
                corrections_out.append({
                    "case_id": c.case_id,
                    "type": c.correction_type,
                    "label": c.label,
                    "original": c.original,
                    "corrected": c.corrected,
                    "context": c.context_text
                })

            total_corr = log.summary["total_corrections"]
            cases_corr = log.summary["cases_with_corrections"]
            total_cases = cases_corr + log.summary["cases_perfect"]

            analysis_prompt = (
                f"The following is a correction log from human review of automated "
                f"extraction results for Philippine Supreme Court case {log.volume_name}. "
                f"The detection pipeline used regex-based extraction with OCR correction. "
                f"A human reviewer corrected {total_corr} annotations across "
                f"{cases_corr} cases (out of {total_cases} total). "
                f"Analyze these corrections to identify: "
                f"(1) systematic patterns in what the pipeline gets wrong, "
                f"(2) specific regex patterns or FSM transitions that need updating, "
                f"(3) labels that would benefit most from improved extraction logic. "
                f"Focus on actionable suggestions referencing the pipeline source files "
                f"in regex_improve/detection/."
            )

            export_data = {
                "format": "correction_log",
                "version": 1,
                "volume_name": log.volume_name,
                "source_predictions": log.source_file,
                "summary": {
                    "total_predicted_annotations": log.total_predicted,
                    "total_corrections": total_corr,
                    "cases_reviewed": total_cases,
                    "cases_with_corrections": cases_corr,
                    "cases_perfect": log.summary["cases_perfect"],
                    "by_type": log.summary.get("by_type", {}),
                    "by_label": log.summary.get("by_label", {})
                },
                "corrections": corrections_out,
                "analysis_prompt": analysis_prompt
            }

            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

            messagebox.showinfo(
                "Export Complete",
                f"Exported {total_corr} corrections to:\n{out_path}"
            )

        except Exception as e:
            messagebox.showerror(
                "Export Error",
                f"Failed to export corrections:\n\n{str(e)}"
            )

    def _apply_page_marker_styling(self):
        """Apply gray styling to page marker lines."""
        if not self.loader:
            return
        
        # Configure page marker tag
        self.text_panel.configure_tag(
            "page_marker",
            foreground="#999999"  # Gray color
            # Note: We don't change font to italic as it might affect performance with 80k+ lines
            # Simple color change is sufficient for visual distinction
        )
        
        # Apply tag to all page marker lines
        for line_idx in self.loader.page_break_lines:
            line_num = line_idx + 1  # Convert to 1-based
            start_index = f"{line_num}.0"
            end_index = f"{line_num}.end"
            self.text_panel.apply_tag("page_marker", start_index, end_index)

    def _on_cursor_move(self):
        """Handle cursor movement events."""
        self._update_side_panel_display()
        self._update_status_bar_position()

    def _update_status_bar_position(self):
        """Update the position display in the status bar."""
        if not self.loader or not self.text_panel:
            return
        
        current_line = self.text_panel.get_current_line()
        if current_line > 0:
            page = self.loader.get_page(current_line)
            self.status_bar.update_position(current_line, page)

    def _update_status_bar_cases(self):
        """Update the case count display in the status bar."""
        if not self.volume_data:
            self.status_bar.update_cases(0, 0)
            return
        
        total_cases = len(self.volume_data.cases)
        complete_cases = 0
        
        for case in self.volume_data.cases:
            if case.get_start_line() and case.get_end_line():
                complete_cases += 1
        
        self.status_bar.update_cases(total_cases, complete_cases)

    def _setup_side_panel_callbacks(self):
        """Set up callbacks for the side panel."""
        self.side_panel.on_navigate = self._navigate_to_case
        self.side_panel.on_label_click = self._assign_label
        self.side_panel.on_delete = self._delete_selected_annotations
        self.side_panel.on_annotation_click = self._scroll_to_annotation

    def _navigate_to_case(self, case_index: int):
        """Navigate to the specified case."""
        if not self.volume_data or case_index < 0 or case_index >= len(self.volume_data.cases):
            return
        
        case = self.volume_data.cases[case_index]
        start_line = case.get_start_line()
        if start_line:
            self.text_panel.scroll_to_line(start_line)
        
        # Directly update with the target case (cursor hasn't moved yet)
        self._current_case = case
        self.side_panel.update_case_display(case, case_index, len(self.volume_data.cases))

    def _scroll_to_annotation(self, annotation_index: int):
        """Scroll to the specified annotation in the current case."""
        if not self._current_case or annotation_index < 0 or annotation_index >= len(self._current_case.annotations):
            return
        
        annotation = self._current_case.annotations[annotation_index]
        self.text_panel.scroll_to_line(annotation.start_line)

    def _delete_selected_annotations(self):
        """Delete selected annotations from the current case."""
        if not self._current_case or not self.highlight_manager:
            return
        
        # Get selected annotation indices from side panel
        selected_indices = self.side_panel.get_selected_annotation_indices()
        if not selected_indices:
            return
        
        # Sort in reverse order to avoid index shifting issues
        for index in sorted(selected_indices, reverse=True):
            if 0 <= index < len(self._current_case.annotations):
                self.highlight_manager.remove_annotation(self._current_case, index)
        
        # Update side panel display
        self._update_side_panel_display()

    def _update_side_panel_display(self):
        """Update the side panel display with current case information."""
        if not self.volume_data:
            self.side_panel.update_case_display(None, -1, 0)
            return
        
        total_cases = len(self.volume_data.cases)
        
        # Find current case index based on cursor position
        current_line = self.text_panel.get_current_line()
        current_case_index = -1
        current_case = None
        
        for i, case in enumerate(self.volume_data.cases):
            start_line = case.get_start_line()
            end_line = case.get_end_line()
            if start_line and start_line <= current_line:
                if end_line is None or current_line <= end_line:
                    current_case_index = i
                    current_case = case
                    break
        
        # Store current case for later use
        self._current_case = current_case
        
        # Update side panel
        self.side_panel.update_case_display(current_case, current_case_index, total_cases)

    def _on_annotation_change(self):
        """Called when annotations change (add/remove)."""
        if self.file_io and self.store:
            try:
                self.file_io.save(self.store)
            except Exception as e:
                messagebox.showerror("Save Error", f"Failed to save annotations: {e}")
        
        # Update side panel display
        self._update_side_panel_display()
        
        # Update status bar cases
        self._update_status_bar_cases()

    def _save_annotations(self):
        """Save annotations."""
        if not self.file_io or not self.store:
            messagebox.showwarning("No Annotations", "No annotations to save.")
            return
        
        try:
            self.file_io.save(self.store)
            messagebox.showinfo("Saved", "Annotations saved successfully.")
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save annotations: {e}")

    def _assign_label(self, label_key: str):
        """Assign a label to the current selection."""
        if not self.highlight_manager:
            messagebox.showwarning(
                "No Volume Loaded",
                "Please open a volume file first."
            )
            return
        
        # Create annotation using highlight manager
        # Visual feedback is provided by the highlight itself
        # Side panel updates will be added in T7
        self.highlight_manager.create_annotation(label_key)

    def _delete_selected(self):
        """Delete selected annotation."""
        # TODO: Implement deletion with side panel selection (T7)
        # For now, show placeholder message
        messagebox.showinfo(
            "Delete Annotation",
            "Delete functionality requires side panel selection (T7).\n\n"
            "In T7, you'll be able to select annotations in the side panel "
            "and delete them using this menu item."
        )

    def _export_json(self):
        """Export annotations as JSON."""
        self._export_with_exporter(JsonExporter())

    def _export_markdown(self):
        """Export annotations as Markdown."""
        self._export_with_exporter(MarkdownExporter())

    def _export_with_exporter(self, exporter):
        """Common export logic for any exporter."""
        if not self.store or not self.store.volumes:
            messagebox.showwarning("No Annotations", "No annotations to export.")
            return
        
        # Create default filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"ground_truth_{timestamp}.{exporter.file_extension}"
        
        # Get annotation_exports directory
        exports_dir = Path(__file__).parent.parent / "annotation_exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        default_path = exports_dir / default_name
        
        # Show save dialog
        file_path = filedialog.asksaveasfilename(
            initialdir=str(exports_dir),
            initialfile=default_name,
            title=f"Export as {exporter.name}",
            filetypes=[(f"{exporter.name} files", f"*.{exporter.file_extension}"), ("All files", "*.*")]
        )
        
        if not file_path:
            return  # User cancelled
        
        output_path = Path(file_path)
        
        try:
            # Prepare loaders dict for exporters that need raw text access
            loaders = {}
            if self.loader and self.current_file:
                loaders[self.current_file.name] = self.loader
            
            # Export
            exporter.export(self.store, output_path, loaders)
            
            messagebox.showinfo(
                "Export Successful",
                f"Annotations exported to:\n{output_path}\n\n"
                f"Format: {exporter.name}\n"
                f"Size: {output_path.stat().st_size:,} bytes"
            )
            
        except Exception as e:
            messagebox.showerror(
                "Export Failed",
                f"Failed to export annotations:\n\n{str(e)}"
            )

    def _run_evaluation(self):
        """Run evaluation using regex extraction method."""
        # Check if we have a loaded volume and annotations
        if not self.loader or not self.current_file:
            messagebox.showwarning(
                "No Volume Loaded",
                "Please open a volume file first."
            )
            return
        
        if not self.store or not self.store.volumes:
            messagebox.showwarning(
                "No Annotations",
                "No annotations found. Please create some annotations first."
            )
            return
        
        # Check if we have complete cases
        complete_cases = 0
        for volume_data in self.store.volumes.values():
            for case in volume_data.cases:
                if case.get_start_line() and case.get_end_line():
                    complete_cases += 1
        
        if complete_cases == 0:
            messagebox.showwarning(
                "No Complete Cases",
                "No complete cases found (cases with both start and end boundaries).\n"
                "Please mark both Start of Case and End of Case for at least one case."
            )
            return
        
        try:
            # Create regex method
            regex_path = Path(__file__).parent.parent / "improved_regex.py"
            method = RegexMethod(regex_path)
            
            # Create evaluation runner
            loaders = {self.current_file.name: self.loader}
            runner = EvaluationRunner(self.store, loaders)
            
            # Run evaluation
            result = runner.run(method)
            
            # Show results in a new window
            self._show_evaluation_results(result)
            
        except Exception as e:
            messagebox.showerror(
                "Evaluation Error",
                f"Failed to run evaluation:\n\n{str(e)}"
            )

    def _show_evaluation_results(self, result):
        """Show evaluation results in a Toplevel window."""
        # Create results window
        results_window = tk.Toplevel(self.root)
        results_window.title(f"Evaluation Results — {result.method_name}")
        results_window.geometry("800x600")
        results_window.minsize(600, 400)
        
        # Create paned window for summary and details
        paned = tk.PanedWindow(results_window, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)
        
        # Summary section (top)
        summary_frame = tk.Frame(paned)
        paned.add(summary_frame)
        
        # Summary label
        tk.Label(summary_frame, text="Summary", font=("Arial", 12, "bold")).pack(anchor=tk.W, padx=10, pady=5)
        
        # Summary table
        summary_text = tk.Text(summary_frame, height=10, wrap=tk.NONE)
        summary_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        summary_text.insert("1.0", result.summary_table())
        summary_text.config(state=tk.DISABLED)
        
        # Add scrollbar for summary
        summary_scrollbar = tk.Scrollbar(summary_frame, command=summary_text.yview)
        summary_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        summary_text.config(yscrollcommand=summary_scrollbar.set)
        
        # Details section (bottom)
        details_frame = tk.Frame(paned)
        paned.add(details_frame)
        
        # Details label
        tk.Label(details_frame, text="Per-Case Details", font=("Arial", 12, "bold")).pack(anchor=tk.W, padx=10, pady=5)
        
        # Create notebook for case details
        notebook = ttk.Notebook(details_frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Add a tab for each case
        for case_score in result.cases:
            case_frame = tk.Frame(notebook)
            notebook.add(case_frame, text=case_score.case_id)
            
            # Create text widget for case details
            case_text = tk.Text(case_frame, wrap=tk.WORD)
            case_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            
            # Add case details
            details = f"Case: {case_score.case_id}\n\n"
            for field_score in case_score.fields:
                details += f"{field_score.label}:\n"
                details += f"  Expected: {field_score.expected_text}\n"
                if field_score.actual_text:
                    details += f"  Actual: {field_score.actual_text}\n"
                else:
                    details += f"  Actual: (not detected)\n"
                details += f"  Exact match: {field_score.exact_match}\n"
                details += f"  Overlap: {field_score.overlap}\n"
                details += f"  Detected: {field_score.detected}\n"
                if field_score.expected_group is not None:
                    details += f"  Expected group: {field_score.expected_group}\n"
                if field_score.actual_group is not None:
                    details += f"  Actual group: {field_score.actual_group}\n"
                details += "\n"
            
            case_text.insert("1.0", details)
            case_text.config(state=tk.DISABLED)
            
            # Add scrollbar
            scrollbar = tk.Scrollbar(case_frame, command=case_text.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            case_text.config(yscrollcommand=scrollbar.set)
        
        # Add export button
        export_frame = tk.Frame(results_window)
        export_frame.pack(fill=tk.X, padx=10, pady=5)
        
        def export_results():
            """Export results as JSON."""
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_name = f"evaluation_{result.method_name}_{timestamp}.json"
            
            # Get evaluation_exports directory
            exports_dir = Path(__file__).parent.parent / "evaluation_exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            default_path = exports_dir / default_name
            
            # Show save dialog
            file_path = filedialog.asksaveasfilename(
                initialdir=str(exports_dir),
                initialfile=default_name,
                title="Export Evaluation Results",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )
            
            if not file_path:
                return  # User cancelled
            
            output_path = Path(file_path)
            
            try:
                # Convert result to dict and save as JSON
                import json
                result_dict = {
                    "method_name": result.method_name,
                    "timestamp": timestamp,
                    "summary": {
                        "precision": result.precision(),
                        "recall": result.recall(),
                        "f1": result.f1()
                    },
                    "cases": [
                        {
                            "case_id": case.case_id,
                            "fields": [
                                {
                                    "label": field.label,
                                    "expected_text": field.expected_text,
                                    "actual_text": field.actual_text,
                                    "exact_match": field.exact_match,
                                    "overlap": field.overlap,
                                    "detected": field.detected,
                                    "expected_group": field.expected_group,
                                    "actual_group": field.actual_group
                                }
                                for field in case.fields
                            ]
                        }
                        for case in result.cases
                    ]
                }
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(result_dict, f, indent=2, ensure_ascii=False)
                
                messagebox.showinfo(
                    "Export Successful",
                    f"Evaluation results exported to:\n{output_path}"
                )
                
            except Exception as e:
                messagebox.showerror(
                    "Export Failed",
                    f"Failed to export evaluation results:\n\n{str(e)}"
                )
        
        tk.Button(export_frame, text="Export Results as JSON", command=export_results).pack(side=tk.RIGHT)
        
        # Set sash position
        paned.sash_place(0, 0, 250)  # Summary section height ~250px

    def _show_keyboard_shortcuts(self):
        """Show keyboard shortcuts dialog."""
        shortcuts_text = "Keyboard Shortcuts:\n\n"
        for label_def in LABELS:
            shortcuts_text += f"{label_def.shortcut_display}: {label_def.display_name}\n"
        
        shortcuts_text += "\nOther shortcuts:\n"
        shortcuts_text += "Ctrl+O: Open Volume\n"
        shortcuts_text += "Ctrl+S: Save Annotations\n"
        shortcuts_text += "Delete: Delete Selected Annotation\n"
        
        messagebox.showinfo("Keyboard Shortcuts", shortcuts_text)

    def _show_about(self):
        """Show about dialog."""
        about_text = (
            "SC Decisions — Case Annotation Tool\n"
            "Version 1.0\n\n"
            "A tool for annotating Supreme Court decision documents.\n"
            "Created as part of the SC-Decisions project.\n\n"
            "Tasks implemented:\n"
            "• T1: Project Scaffolding + Constants + Data Model\n"
            "• T2: Volume Loader + Page Index Builder\n"
            "• T3: Main Window Skeleton + Menu Bar\n"
            "• T4: Text Panel with Line Numbers + Scrolling\n"
            "• T5: Highlight/Selection System + Label Assignment\n"
        )
        messagebox.showinfo("About", about_text)

    def _bind_shortcuts(self):
        """Bind keyboard shortcuts for all labels.
        For each label in LABELS:
            self.root.bind(label.tk_binding, lambda e, k=label.key: self.assign_label(k))

        Also bind:
        - Delete key → delete selected annotations
        - Ctrl+S → save
        - Ctrl+Z → undo last annotation (nice to have, can be deferred)

        Platform note (Windows):
        - Ctrl+Shift+letter bindings: Tkinter on Windows may generate the
          keysym as uppercase (e.g., 'D' not 'd'). Bind BOTH cases:
            self.root.bind("<Control-Shift-Key-D>", handler)
            self.root.bind("<Control-Shift-Key-d>", handler)
        - Ctrl+number bindings should work as-is.
        - Return "break" from handlers to prevent default Tkinter behavior
          (e.g., prevent Ctrl+Shift+V from also pasting)
        """
        # Bind all label shortcuts
        for label_def in LABELS:
            # Create handler for this label
            def handler(event, key=label_def.key):
                self._assign_label(key)
                return "break"  # Prevent default behavior
            
            # Bind the primary binding
            self.root.bind(label_def.tk_binding, handler)
            
            # For Ctrl+Shift+letter bindings on Windows, also bind lowercase version
            if label_def.tk_binding.startswith("<Control-Shift-Key-"):
                # Extract the letter from the binding (e.g., "D" from "<Control-Shift-Key-D>")
                letter = label_def.tk_binding[-2]  # Second to last character before '>'
                if letter.isupper():
                    # Also bind lowercase version
                    lowercase_binding = label_def.tk_binding[:-2] + letter.lower() + ">"
                    self.root.bind(lowercase_binding, handler)
        
        # Bind Delete key for annotation deletion
        def delete_handler(event):
            self._delete_selected_annotations()
            return "break"
        self.root.bind("<Delete>", delete_handler)
        self.root.bind("<Key-Delete>", delete_handler)
        
        # Bind Ctrl+S for save
        def save_handler(event):
            self._save_annotations()
            return "break"
        self.root.bind("<Control-Key-s>", save_handler)
        self.root.bind("<Control-Key-S>", save_handler)
        
        # Bind Ctrl+O for open volume
        def open_handler(event):
            self.open_volume()
            return "break"
        self.root.bind("<Control-Key-o>", open_handler)
        self.root.bind("<Control-Key-O>", open_handler)

    def _on_window_close(self):
        """Handle window close event."""
        # Save annotations before closing
        if self.file_io and self.store:
            try:
                self.file_io.save(self.store)
            except Exception as e:
                messagebox.showerror("Save Error", f"Failed to save annotations: {e}")
        
        # Destroy the window
        self.root.destroy()

    def _update_menu_state(self):
        """Update menu state based on whether a volume is loaded."""
        # Get the menu bar
        menubar = self.root.nametowidget(self.root.cget("menu"))
        
        # Find menu indices (File=0, Annotate=1, Export=2, Test=3, Help=4)
        # This is a bit hacky but works for our simple menu structure
        try:
            # Disable/Enable Annotate menu (index 1)
            annotate_menu = menubar.entrycget(1, "menu")
            if annotate_menu:
                annotate_state = "normal" if self.loader else "disabled"
                menubar.entryconfigure(1, state=annotate_state)
            
            # Disable/Enable Export menu (index 2)
            export_menu = menubar.entrycget(2, "menu")
            if export_menu:
                export_state = "normal" if self.loader else "disabled"
                menubar.entryconfigure(2, state=export_state)
            
            # Disable/Enable Test menu (index 3)
            test_menu = menubar.entrycget(3, "menu")
            if test_menu:
                test_state = "normal" if self.loader else "disabled"
                menubar.entryconfigure(3, state=test_state)
        except Exception:
            # If menu structure changes, this might fail - ignore
            pass

    def run(self):
        """Start the Tkinter main loop."""
        self.root.mainloop()


if __name__ == "__main__":
    # Test the app directly
    app = AnnotationApp()
    app.run()