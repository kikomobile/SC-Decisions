import tkinter as tk
from tkinter import font as tkfont
from typing import Optional, Tuple


class TextPanel(tk.Frame):
    """Main text display with line number gutter and synchronized scrolling."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # Create a monospace font for both text and gutter
        try:
            self.text_font = tkfont.Font(family="Consolas", size=10)
        except tk.TclError:
            # Fallback if Consolas is unavailable
            self.text_font = tkfont.Font(family="Courier New", size=10)

        # Create widgets
        self._create_widgets()
        self._setup_layout()
        self._bind_events()

    def _create_widgets(self):
        """Create the text widget, gutter canvas, and scrollbar."""
        # Gutter canvas for line numbers
        self.gutter = tk.Canvas(self, width=60, bg="#f5f5f5", highlightthickness=0)
        
        # Text widget - keep state=NORMAL to allow selection, but bind keys to prevent editing
        self.text = tk.Text(
            self,
            wrap=tk.NONE,  # No word wrap for line number accuracy
            font=self.text_font,
            bg="white",
            relief=tk.FLAT,
            borderwidth=0,
            padx=5,
            pady=5,
            undo=True,
            maxundo=-1
        )
        
        # Vertical scrollbar
        self.scrollbar = tk.Scrollbar(self, orient=tk.VERTICAL)
        
        # Configure scrollbar commands
        self.scrollbar.config(command=self._on_scrollbar)
        self.text.config(yscrollcommand=self._on_text_scroll)
        
        # Bind keys to prevent editing while allowing selection
        self._bind_edit_prevention()

    def _setup_layout(self):
        """Arrange widgets using grid layout."""
        self.gutter.grid(row=0, column=0, sticky="ns")
        self.text.grid(row=0, column=1, sticky="nsew")
        self.scrollbar.grid(row=0, column=2, sticky="ns")
        
        # Configure grid weights
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

    def _bind_events(self):
        """Bind events for scrolling and resizing."""
        # Bind mouse wheel events for scrolling
        self.text.bind("<MouseWheel>", self._on_mousewheel)
        self.text.bind("<Button-4>", self._on_mousewheel)  # Linux scroll up
        self.text.bind("<Button-5>", self._on_mousewheel)  # Linux scroll down
        
        # Bind configure event for resizing
        self.text.bind("<Configure>", self._on_configure)
        
        # Bind key events to trigger gutter redraw
        self.text.bind("<KeyRelease>", lambda e: self._redraw_line_numbers())
        self.text.bind("<ButtonRelease-1>", lambda e: self._redraw_line_numbers())
        
        # Bind edit prevention
        self._bind_edit_prevention()

    def _bind_edit_prevention(self):
        """Bind keys to prevent editing while allowing selection."""
        def prevent_edit(event):
            # Allow navigation keys (arrows, page up/down, home, end)
            navigation_keys = {
                'Up', 'Down', 'Left', 'Right',
                'Prior', 'Next', 'Home', 'End',
            }
            if event.keysym in navigation_keys:
                return

            # Allow modifier keys alone (Ctrl, Shift, Alt)
            modifier_keys = {
                'Control_L', 'Control_R', 'Shift_L', 'Shift_R',
                'Alt_L', 'Alt_R', 'Meta_L', 'Meta_R',
            }
            if event.keysym in modifier_keys:
                return

            # Allow ALL Ctrl key combinations to propagate
            # (shortcuts are bound on root and need these events)
            if event.state & 0x0004:  # Control key is pressed
                return

            # Block everything else (plain typing, Alt combos, etc.)
            return "break"

        self.text.bind("<Key>", prevent_edit)

        # Also block paste/cut via virtual events and mouse buttons
        self.text.bind("<<Paste>>", lambda e: "break")
        self.text.bind("<<Cut>>", lambda e: "break")
        self.text.bind("<Button-2>", lambda e: "break")  # middle-click paste (Linux)
        self.text.bind("<Button-3>", lambda e: "break")  # right-click paste (some systems)

    def load_text(self, text: str) -> None:
        """Load volume text into the widget.
        
        1. Ensure text widget is in NORMAL state (for selection)
        2. Delete all existing content
        3. Insert full text in one call: self.text.insert('1.0', text)
        4. Scroll to top
        5. Trigger gutter redraw
        """
        # Ensure text widget is in NORMAL state (allows selection)
        self.text.config(state=tk.NORMAL)
        
        # Clear existing content
        self.text.delete("1.0", tk.END)
        
        # Insert new text
        self.text.insert("1.0", text)
        
        # Scroll to top
        self.text.see("1.0")
        
        # Redraw line numbers
        self._redraw_line_numbers()

    def get_selection(self) -> Optional[Tuple[str, str]]:
        """Get current text selection as (start_index, end_index) Tk index strings.
        
        Returns None if no selection exists.
        Use: self.text.tag_ranges(tk.SEL)
        """
        try:
            sel_ranges = self.text.tag_ranges(tk.SEL)
            if sel_ranges:
                return (str(sel_ranges[0]), str(sel_ranges[1]))
        except tk.TclError:
            pass
        return None

    def get_cursor_position(self) -> str:
        """Get current cursor position as Tk index string.
        
        Return self.text.index(tk.INSERT)
        """
        return self.text.index(tk.INSERT)

    def get_current_line(self) -> int:
        """Get 1-based line number at cursor.
        
        Parse self.text.index(tk.INSERT) to extract line number.
        """
        cursor_index = self.text.index(tk.INSERT)
        line_str, _ = cursor_index.split(".")
        return int(line_str)

    def apply_tag(self, tag_name: str, start: str, end: str) -> None:
        """Apply a named tag to a text range.
        
        Tag configurations (colors) should be pre-created via configure_tag().
        """
        self.text.tag_add(tag_name, start, end)

    def remove_tag(self, tag_name: str, start: str = None, end: str = None) -> None:
        """Remove a named tag. If start/end are None, remove from entire text."""
        if start is None or end is None:
            self.text.tag_remove(tag_name, "1.0", tk.END)
        else:
            self.text.tag_remove(tag_name, start, end)

    def configure_tag(self, tag_name: str, **kwargs) -> None:
        """Configure a tag's visual properties (background, foreground, etc.).
        
        Delegates to self.text.tag_configure(tag_name, **kwargs).
        """
        self.text.tag_configure(tag_name, **kwargs)

    def scroll_to_line(self, line: int) -> None:
        """Scroll to make the given line visible and roughly centered.
        
        Use self.text.see(f"{line}.0") then adjust to center.
        """
        # First make sure the line is visible
        self.text.see(f"{line}.0")
        
        # Try to center it by scrolling a bit more
        # Get visible lines
        first_visible = self.text.index("@0,0")
        last_visible = self.text.index(f"@0,{self.text.winfo_height()}")
        
        first_line = int(first_visible.split(".")[0])
        last_line = int(last_visible.split(".")[0])
        
        visible_lines = last_line - first_line
        
        # If line is near the top or bottom, adjust
        if line < first_line + visible_lines // 4:
            # Line is in top quarter, scroll up a bit
            target_line = max(1, line - visible_lines // 4)
            self.text.see(f"{target_line}.0")
        elif line > last_line - visible_lines // 4:
            # Line is in bottom quarter, scroll down a bit
            target_line = line + visible_lines // 4
            self.text.see(f"{target_line}.0")

    def _on_scrollbar(self, *args) -> None:
        """Called when user drags scrollbar. Move text and redraw gutter."""
        self.text.yview(*args)
        self._redraw_line_numbers()

    def _on_text_scroll(self, first, last) -> None:
        """Called when text widget scrolls. Update scrollbar and redraw gutter."""
        self.scrollbar.set(first, last)
        self._redraw_line_numbers()

    def _on_mousewheel(self, event) -> None:
        """Handle mouse wheel scrolling."""
        if event.num == 4 or event.delta > 0:  # Scroll up
            self.text.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:  # Scroll down
            self.text.yview_scroll(1, "units")
        self._redraw_line_numbers()
        return "break"  # Prevent default behavior

    def _on_configure(self, event) -> None:
        """Called on widget resize. Redraw gutter."""
        self._redraw_line_numbers()

    def _redraw_line_numbers(self) -> None:
        """Redraw only the visible line numbers in the gutter Canvas.
        
        Algorithm:
        1. Clear the canvas: self.gutter.delete("all")
        2. Get first visible line: self.text.index("@0,0") → parse line number
        3. Get last visible line: self.text.index(f"@0,{self.text.winfo_height()}") → parse line number
        4. For each visible line number:
           a. Get its y-coordinate: self.text.dlineinfo(f"{line}.0") returns (x, y, w, h, baseline)
              — if dlineinfo returns None, the line is not visible; skip
           b. Draw text on canvas: self.gutter.create_text(width-5, y, anchor="ne",
              text=str(line), font=self.text_font, fill="#606060")
        5. This method must be fast — it runs on every scroll event.
        """
        # Clear the canvas
        self.gutter.delete("all")
        
        # Get visible line range
        try:
            first_visible = self.text.index("@0,0")
            last_visible = self.text.index(f"@0,{self.text.winfo_height()}")
        except tk.TclError:
            # Widget not yet fully initialized
            return
        
        # Parse line numbers
        try:
            first_line = int(first_visible.split(".")[0])
            last_line = int(last_visible.split(".")[0])
        except (ValueError, IndexError):
            return
        
        # Add some padding lines for smooth scrolling
        first_line = max(1, first_line - 2)
        last_line = last_line + 2
        
        # Get gutter width
        gutter_width = self.gutter.winfo_width()
        if gutter_width <= 0:
            gutter_width = 60  # Default width
        
        # Draw line numbers for visible lines
        for line in range(first_line, last_line + 1):
            # Get line position info
            line_info = self.text.dlineinfo(f"{line}.0")
            if line_info is None:
                # Line not currently visible
                continue
            
            # line_info is (x, y, width, height, baseline)
            y_pos = line_info[1]  # y-coordinate
            
            # Draw line number
            self.gutter.create_text(
                gutter_width - 5,  # Right-aligned with 5px padding
                y_pos,
                anchor="ne",  # Northeast anchor (right-aligned, top at y)
                text=str(line),
                font=self.text_font,
                fill="#606060"  # Medium gray
            )
        
        # Draw a subtle separator line
        self.gutter.create_line(
            gutter_width - 1, 0, gutter_width - 1, self.gutter.winfo_height(),
            fill="#cccccc"
        )


if __name__ == "__main__":
    """Simple test to verify TextPanel works."""
    root = tk.Tk()
    root.title("TextPanel Test")
    root.geometry("800x600")
    
    panel = TextPanel(root)
    panel.pack(fill=tk.BOTH, expand=True)
    
    # Load some test text
    test_text = "\n".join([f"Line {i}: This is test text for line {i}" for i in range(1, 101)])
    panel.load_text(test_text)
    
    # Configure a test tag
    panel.configure_tag("test_highlight", background="yellow")
    panel.apply_tag("test_highlight", "10.0", "15.0")
    
    root.mainloop()