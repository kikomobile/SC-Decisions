"""Dialog windows for consolidated case and multi-party workflows."""
import tkinter as tk
from tkinter import simpledialog, messagebox
from typing import Optional, List, Tuple


def ask_consolidated(parent: tk.Tk, group_index: int) -> bool:
    """Show a Yes/No dialog: 'Add as consolidated case number? (Group {group_index})'
    Returns True if user clicks Yes, False otherwise.
    Use messagebox.askyesno().
    """
    return messagebox.askyesno(
        "Consolidated Case Number",
        f"Add as consolidated case number? (Group {group_index})",
        parent=parent
    )


def ask_party_group(parent: tk.Tk, case_numbers: List[Tuple[int, str]]) -> Optional[int]:
    """Show a dialog asking which case number this parties block belongs to.

    Args:
        case_numbers: list of (group_index, case_number_text) tuples
                      e.g. [(0, "G.R. No. 132724"), (1, "G.R. No. 132800")]

    Shows a dialog with radio buttons, one per case number:
        "Which case number does this parties block belong to?"
        ○ [Group 0] G.R. No. 132724
        ○ [Group 1] G.R. No. 132800
        [OK] [Cancel]

    Returns the selected group index, or None if cancelled.

    Implementation: Create a tk.Toplevel with radio buttons and OK/Cancel buttons.
    Use a tk.IntVar for the selection.
    """
    if not case_numbers:
        return None
    
    # Create dialog window
    dialog = tk.Toplevel(parent)
    dialog.title("Select Case Number")
    dialog.transient(parent)  # Make dialog modal relative to parent
    dialog.grab_set()  # Make dialog modal
    
    # Center dialog on parent
    dialog.geometry("+%d+%d" % (
        parent.winfo_rootx() + 50,
        parent.winfo_rooty() + 50
    ))
    
    # Create instruction label
    tk.Label(
        dialog,
        text="Which case number does this parties block belong to?",
        padx=20, pady=10
    ).pack(pady=(20, 10))
    
    # Create frame for radio buttons
    radio_frame = tk.Frame(dialog, padx=20)
    radio_frame.pack(fill=tk.BOTH, expand=True)
    
    # Variable to store selection
    selected_group = tk.IntVar(value=case_numbers[0][0])
    
    # Create radio buttons
    for group_index, case_text in case_numbers:
        # Truncate long case text for display
        display_text = case_text
        if len(display_text) > 60:
            display_text = display_text[:57] + "..."
        
        rb = tk.Radiobutton(
            radio_frame,
            text=f"[Group {group_index}] {display_text}",
            variable=selected_group,
            value=group_index,
            anchor=tk.W,
            padx=10,
            pady=2
        )
        rb.pack(fill=tk.X)
    
    # Create button frame
    button_frame = tk.Frame(dialog, pady=10)
    button_frame.pack()
    
    result = None
    
    def on_ok():
        nonlocal result
        result = selected_group.get()
        dialog.destroy()
    
    def on_cancel():
        nonlocal result
        result = None
        dialog.destroy()
    
    # Create OK and Cancel buttons
    tk.Button(button_frame, text="OK", width=10, command=on_ok).pack(side=tk.LEFT, padx=5)
    tk.Button(button_frame, text="Cancel", width=10, command=on_cancel).pack(side=tk.LEFT, padx=5)
    
    # Make dialog modal
    dialog.wait_window(dialog)
    
    return result


def show_warning(parent: tk.Tk, title: str, message: str) -> None:
    """Show a warning dialog. Wrapper around messagebox.showwarning()."""
    messagebox.showwarning(title, message, parent=parent)