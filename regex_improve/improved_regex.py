"""
improved_regex.py — Drop-in replacement patterns for regex testing
==================================================================

After exporting ground truth and pasting the .md into Claude,
Claude will generate improved regex patterns. Paste them here
using the SAME variable names as annotate_tool.py uses.

The test command will load these patterns and score them against
your annotated ground truth.

Pattern names expected by the test harness:
  RE_CASE_START     — case boundary detection
  RE_CASE_BRACKET   — bracketed case number + date
  RE_CASE_NUM       — standalone case number
  RE_DATE           — date extraction
  RE_DIVISION       — division label
  RE_PONENTE        — ponente/author byline
  RE_DECISION       — D E C I S I O N header
  RE_RESOLUTION     — R E S O L U T I O N header
  RE_SYLLABUS       — SYLLABUS header
  RE_COUNSEL        — APPEARANCES OF COUNSEL header

Any pattern you don't define here will fall back to the baseline.
"""

import re

# ---------------------------------------------------------------------------
# PASTE CLAUDE'S IMPROVED PATTERNS BELOW
# ---------------------------------------------------------------------------

# Example — uncomment and replace with Claude's output:
#
# RE_CASE_START = re.compile(
#     r'...',
#     re.IGNORECASE | re.MULTILINE
# )
#
# RE_CASE_BRACKET = re.compile(
#     r'...',
#     re.IGNORECASE
# )
