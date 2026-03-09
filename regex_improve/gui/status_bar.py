import tkinter as tk


class StatusBar(tk.Frame):
    """Bottom status bar showing current file, cursor position, and case count."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # Three labels, left-aligned with separators
        self.file_label = tk.Label(self, text="No file loaded", anchor=tk.W,
                                   relief=tk.SUNKEN, padx=5)
        self.position_label = tk.Label(self, text="Line 0", anchor=tk.W,
                                       relief=tk.SUNKEN, padx=5)
        self.case_label = tk.Label(self, text="0 cases", anchor=tk.W,
                                   relief=tk.SUNKEN, padx=5)

        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.position_label.pack(side=tk.LEFT, fill=tk.X)
        self.case_label.pack(side=tk.LEFT, fill=tk.X)

    def update_file(self, filename: str):
        """Update the filename display."""
        self.file_label.config(text=filename)

    def update_position(self, line: int, page: int = 0):
        """Update the cursor position display.
        Shows: 'Line 12,051 | Page 251'
        """
        line_str = f"Line {line:,}"
        if page > 0:
            line_str += f" | Page {page}"
        self.position_label.config(text=line_str)

    def update_cases(self, annotated: int, total_complete: int):
        """Update the case count display.
        Shows: '16 cases (12 complete)'
        """
        self.case_label.config(text=f"{annotated} cases ({total_complete} complete)")