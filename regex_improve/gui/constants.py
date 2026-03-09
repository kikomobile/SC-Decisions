from dataclasses import dataclass

@dataclass(frozen=True)
class LabelDef:
    key: str              # internal identifier, e.g. "case_number"
    display_name: str     # human-readable, e.g. "Case Number"
    shortcut_display: str # shown in UI, e.g. "Ctrl+2"
    tk_binding: str       # Tkinter event string, e.g. "<Control-Key-2>"
    color: str            # hex background color for highlights
    selection_type: str   # "cursor" (marks whole line) or "selection" (requires text selection)
    button_text: str      # label on the side panel button, e.g. "[2] Case Number"

# The full LABELS list (define in this exact order):
LABELS = [
    LabelDef(
        key="start_of_case",
        display_name="Start of Case",
        shortcut_display="Ctrl+1",
        tk_binding="<Control-Key-1>",
        color="#FFD700",
        selection_type="cursor",
        button_text="[1] Start Case"
    ),
    LabelDef(
        key="case_number",
        display_name="Case Number",
        shortcut_display="Ctrl+2",
        tk_binding="<Control-Key-2>",
        color="#87CEEB",
        selection_type="selection",
        button_text="[2] Case Number"
    ),
    LabelDef(
        key="date",
        display_name="Date of Decision",
        shortcut_display="Ctrl+3",
        tk_binding="<Control-Key-3>",
        color="#98FB98",
        selection_type="selection",
        button_text="[3] Date"
    ),
    LabelDef(
        key="division",
        display_name="Division",
        shortcut_display="Ctrl+4",
        tk_binding="<Control-Key-4>",
        color="#DDA0DD",
        selection_type="selection",
        button_text="[4] Division"
    ),
    LabelDef(
        key="parties",
        display_name="Parties",
        shortcut_display="Ctrl+5",
        tk_binding="<Control-Key-5>",
        color="#F0E68C",
        selection_type="selection",
        button_text="[5] Parties"
    ),
    LabelDef(
        key="start_syllabus",
        display_name="Start of Syllabus",
        shortcut_display="Ctrl+6",
        tk_binding="<Control-Key-6>",
        color="#FFA07A",
        selection_type="cursor",
        button_text="[6] Start Syllabus"
    ),
    LabelDef(
        key="end_syllabus",
        display_name="End of Syllabus",
        shortcut_display="Ctrl+7",
        tk_binding="<Control-Key-7>",
        color="#FFA07A",
        selection_type="cursor",
        button_text="[7] End Syllabus"
    ),
    LabelDef(
        key="counsel",
        display_name="Counsel Names",
        shortcut_display="Ctrl+8",
        tk_binding="<Control-Key-8>",
        color="#B0C4DE",
        selection_type="selection",
        button_text="[8] Counsel"
    ),
    LabelDef(
        key="ponente",
        display_name="Ponente Name",
        shortcut_display="Ctrl+9",
        tk_binding="<Control-Key-9>",
        color="#FFB6C1",
        selection_type="selection",
        button_text="[9] Ponente"
    ),
    LabelDef(
        key="doc_type",
        display_name="Document Type",
        shortcut_display="Ctrl+0",
        tk_binding="<Control-Key-0>",
        color="#E6E6FA",
        selection_type="selection",
        button_text="[0] Doc Type"
    ),
    LabelDef(
        key="start_decision",
        display_name="Start of Decision",
        shortcut_display="Ctrl+Shift+D",
        tk_binding="<Control-Shift-Key-D>",
        color="#C8FFC8",
        selection_type="cursor",
        button_text="[D] Start Decision"
    ),
    LabelDef(
        key="end_decision",
        display_name="End of Decision",
        shortcut_display="Ctrl+Shift+E",
        tk_binding="<Control-Shift-Key-E>",
        color="#C8FFC8",
        selection_type="cursor",
        button_text="[E] End Decision"
    ),
    LabelDef(
        key="votes",
        display_name="Votes",
        shortcut_display="Ctrl+Shift+V",
        tk_binding="<Control-Shift-Key-V>",
        color="#FFDAB9",
        selection_type="selection",
        button_text="[V] Votes"
    ),
    LabelDef(
        key="start_opinion",
        display_name="Start of Opinion",
        shortcut_display="Ctrl+Shift+O",
        tk_binding="<Control-Shift-Key-O>",
        color="#D8BFD8",
        selection_type="cursor",
        button_text="[O] Start Opinion"
    ),
    LabelDef(
        key="end_opinion",
        display_name="End of Opinion",
        shortcut_display="Ctrl+Shift+P",
        tk_binding="<Control-Shift-Key-P>",
        color="#D8BFD8",
        selection_type="cursor",
        button_text="[P] End Opinion"
    ),
    LabelDef(
        key="end_of_case",
        display_name="End of Case",
        shortcut_display="Ctrl+Shift+X",
        tk_binding="<Control-Shift-Key-X>",
        color="#FFD700",
        selection_type="cursor",
        button_text="[X] End Case"
    ),
]

# Convenience constants
LABEL_MAP = {label.key: label for label in LABELS}

# Labels that use the group field (all others have group=None)
GROUPED_LABELS = {"case_number", "parties"}

# Annotation file path (relative to cwd, which is regex_improve/)
ANNOTATION_FILE = "annotations.json"
SAMPLES_DIR = "samples"
IMPROVED_REGEX_FILE = "improved_regex.py"