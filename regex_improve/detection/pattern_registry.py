import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict

logger = logging.getLogger(__name__)


@dataclass
class Era:
    """A volume range with a name."""
    name: str          # e.g., "era1"
    vol_start: int     # inclusive lower bound
    vol_end: int       # inclusive upper bound
    description: str   # e.g., "1980s baseline"


@dataclass
class EraConfig:
    """All regex patterns and scoring settings for a specific era.
    Treat instances as immutable after creation."""
    era_name: str

    # -- Shared (used by preprocess.py AND boundary_fsm.py) --
    re_division: re.Pattern

    # -- Preprocessing (preprocess.py) --
    re_page_marker: re.Pattern
    re_volume_header: re.Pattern
    re_philippine_reports: re.Pattern
    re_short_title: re.Pattern
    re_syllabus_header: re.Pattern

    # -- Boundary detection (boundary_fsm.py) --
    re_case_bracket: re.Pattern
    re_case_bracket_no_close: re.Pattern

    # -- Section extraction (section_extractor.py) --
    re_syllabus: re.Pattern
    re_counsel_header: re.Pattern
    re_doc_type: re.Pattern
    re_ponente: re.Pattern
    re_per_curiam: re.Pattern
    re_so_ordered: re.Pattern
    re_separate_opinion: re.Pattern
    re_votes_content: re.Pattern
    re_footnote_start: re.Pattern
    re_wherefore: re.Pattern
    re_counsel_designation: re.Pattern
    re_parties_end: re.Pattern
    re_vs_line: re.Pattern

    # -- Confidence scoring (confidence.py) --
    required_labels: frozenset = field(default_factory=lambda: frozenset({
        "start_of_case", "case_number", "date", "division", "doc_type",
        "start_decision", "end_decision", "votes", "end_of_case"
    }))
    label_order: tuple = field(default_factory=lambda: (
        "start_of_case", "case_number", "date", "division", "parties",
        "start_syllabus", "end_syllabus", "counsel", "doc_type", "ponente",
        "start_decision", "end_decision", "votes", "start_opinion",
        "end_opinion", "end_of_case"
    ))
    parties_len_range: Tuple[int, int] = (50, 2000)
    votes_len_range: Tuple[int, int] = (20, 500)

    # -- Votes extraction tuning --
    votes_max_non_blank_lines: int = 15
    votes_continuation_lookahead: int = 0   # lines to look ahead past blanks/footnotes
    votes_extend_past_boundary: bool = False # allow votes to extend past case boundary

    # -- Behavioral flags --
    has_syllabus: bool = True   # False for era5: skip syllabus extraction entirely


# Define the 5 default eras
DEFAULT_ERAS: List[Era] = [
    Era("era1", 121,  260, "1980s baseline (OCR-heavy, non-spaced DECISION)"),
    Era("era2", 261,  500, "1990-2005 (non-spaced DECISION, varied OCR quality)"),
    Era("era3", 501,  700, "2005-2012 (spaced D E C I S I O N transition)"),
    Era("era4", 701,  900, "2012-2022 (modern digital, spaced DECISION)"),
    Era("era5", 901,  999, "2022-2024 (no SYLLABUS, Unicode ligature issues)"),
]


def _build_baseline_config(era_name: str, **overrides) -> EraConfig:
    """Build an EraConfig with the exact current patterns from all modules.
    
    All patterns are copied verbatim from the current source modules.
    """
    # -- Preprocessing patterns (from preprocess.py) --
    re_page_marker = re.compile(r'^--- Page \d+ ---$')
    re_volume_header = re.compile(r'^VOL[.,]\s*\d+.*\d+\s*$')
    re_philippine_reports = re.compile(r'^\d+\s+PHILIPPINE REPORTS\s*$')
    re_short_title = re.compile(
        r'^[A-Z][A-Za-z\s,.\'\"\-\u2018\u2019\u201c\u201d]+'
        r'(?:v|y|V|Y)s?\.'
        r'[A-Za-z\s,.\'\"\-\u2018\u2019\u201c\u201d]+$'
    )
    re_division = re.compile(
        r'^(EN\s*BAN\s*C|(?:FIRST|SECOND|THIRD)\s+DIVIS[ILO]*[ILO]+N)\s*$',
        re.IGNORECASE
    )
    re_syllabus_header = re.compile(r'^SY[IL]?LABUS\s*$', re.IGNORECASE)

    # -- Boundary detection patterns (from boundary_fsm.py) --
    # RE_CASE_BRACKET must match all variants listed in TASKS.md
    # Pattern: opening bracket [({, then case type prefix, then case number, 
    # then separator, then date, then closing bracket ])}
    # Handle OCR errors: comma for period in "No," and weird bracket patterns
    # Handle nested brackets like {Adm. Matter Nos. ...]. May 30, 1986]
    # Use greedy date match to capture everything up to the last closing bracket
    # Allow trailing characters after closing bracket (OCR errors like underscore)
    # FIX-2: Make opening bracket optional (allow [, (, {, or OCR-corrupted 1, or missing entirely)
    # Also make closing bracket more flexible: allow ], ), }, |, ., or even missing
    # Handle nested/multiple opening brackets like ([ or [I (OCR errors)
    re_case_bracket = re.compile(
        r'^[\[\(\{1I]*(?:[\[\(\{1I])?'  # Opening bracket(s) (optional, tolerates OCR errors)
        r'(?:G\.\s*R\.\s*No[\.\s,]*s?[\.\s,]*|'
        r'A\.\s*M\.\s*No[\.\s,]*s?[\.\s,]*|'
        r'Adm\.\s*(?:Matter|Case)\s*No[\.\s,]*s?[\.\s,]*)'
        r'\s*([\w\-/&\s\.]+?)'  # case number (non-greedy)
        r'[\.\s,]+'             # separator between case number and date
        r'(.+)'                 # date text (greedy — captures everything up to closing bracket)
        r'[\]\)\}]'             # Closing bracket (REQUIRED: ], ), or })
        r'.*$',                 # Allow trailing chars after closing bracket (OCR errors)
        re.IGNORECASE
    )

    # FIX-2: Fallback pattern for lines where BOTH brackets are corrupted/missing
    # but the line clearly contains a G.R. number and date with month name
    re_case_bracket_no_close = re.compile(
        r'^[\[\(\{1]?'
        r'(?:G\.\s*R\.\s*No[\.\s,]*s?[\.\s,]*|A\.\s*M\.\s*No[\.\s,]*s?[\.\s,]*|Adm\.\s*(?:Matter|Case)\s*No[\.\s,]*s?[\.\s,]*)'
        r'\s*([\w\-/&\s\.]+?)'
        r'[\.\s,]+'
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})',
        re.IGNORECASE
    )

    # -- Section extraction patterns (from section_extractor.py) --
    re_syllabus = re.compile(r'^SYLLABUS\s*$')
    re_counsel_header = re.compile(r'^APPEARANCES?\s+OF\s+COUNSEL\s*$', re.IGNORECASE)
    re_doc_type = re.compile(
        r'^(?:DECISION|RESOLUTION|'
        r'D\s+E\s+C\s+I\s+S\s+I\s+O\s+N|'
        r'R\s+E\s+S\s+O\s+L\s+U\s+T\s+I\s+O\s+N)\s*$'
    )
    re_ponente = re.compile(
        r'^\s*[\W]*'                                                    # optional leading OCR garbage
        r'([A-Z\u00C0-\u024F][A-Z\u00C0-\u024F\s,.\'\-]+?)'          # name (diacritics allowed)
        r',?\s*'
        r'(?:Actg\.\s*|Acting\s+)?'                                     # optional Acting/Actg.
        r'(?:'
            r'C[\s./)]*J[\s./)]*'                                       # C.J. variants
            r'|J[\s./)]*'                                               # J. variants
            r'|[CVJ/\u00C0-\u024F][A-Za-z\u00C0-\u024F./)]*'          # OCR-mangled suffixes
        r')'
        r':\s*'                                                         # REQUIRED colon
        r'[./)!*\u201c\u201d\u2018\u2019\u00c2\x22\':]*'             # trailing garbage
        r'\s*$'
    )
    re_per_curiam = re.compile(r'^PER\s+CURIAM\s*[,:;]*\s*$', re.IGNORECASE)
    re_so_ordered = re.compile(
        r'^\s*[\u201c\u201d\u2018\u2019\u00ab\u00bb"\']*\s*'  # optional leading smart/straight quotes
        r'(?:IT\s+IS\s+)?'                                      # optional "IT IS" prefix
        r'SO\s*ORDERED'
        r'\s*[.,;:!]*'                                           # optional punctuation
        r'\s*[\u201c\u201d\u2018\u2019\u00ab\u00bb"\']*'        # optional trailing smart/straight quotes
        r'\s*\d{0,3}'                                            # optional footnote number (1-3 digits)
        r'\s*$',
        re.IGNORECASE
    )
    re_separate_opinion = re.compile(
        r'^\s*[\W]*'
        r'([A-Z\u00C0-\u024F][A-Z\u00C0-\u024F\s,.\'\-]+?)'          # name (diacritics allowed)
        r',\s*'
        r'(?:Actg\.\s*|Acting\s+)?'
        r'(?:'
            r'C[\s./)]*J[\s./)]*'
            r'|J[\s./)]*'
            r'|[CVJ/\u00C0-\u024F][A-Za-z\u00C0-\u024F./)]*'
        r')'
        r',?\s*'
        r'(?:concurring|dissenting|separate)\b',
        re.IGNORECASE
    )
    re_votes_content = re.compile(
        r'(?:concur|dissent|dissenting|separate opinion|'
        r'JJ\.|J\.\,|J\.\:|C\.J\.|'
        r'Chairman|Presiding|'
        r'\(on leave\)|\(on official leave\)|\(no part\)|'
        r'[A-Z]{3,}(?:\s+[A-Z]{3,})*(?:\s+[A-Z]\.)?(?:\s+[A-Z]{3,})*)',
        re.IGNORECASE
    )
    re_footnote_start = re.compile(r'^(?:\d+\s+|\*|\")')
    re_wherefore = re.compile(r'^\s*WHEREFORE\b', re.IGNORECASE)
    re_counsel_designation = re.compile(
        r'for\s+(?:the\s+)?(?:petitioner|respondent|plaintiff|defendant|appellant|appellee|'
        r'accused|complainant|private|intervenor|oppositor)',
        re.IGNORECASE
    )
    re_parties_end = re.compile(
        r'(?:respondents?|petitioners?|plaintiffs?|defendants?|appellants?|appellees?|'
        r'accused-appellants?|intervenors?|oppositors?)\s*[.,;]*\s*$',
        re.IGNORECASE
    )
    re_vs_line = re.compile(r'^\s*vs\.?\s', re.IGNORECASE)

    # Build the config
    config = EraConfig(
        era_name=era_name,
        re_division=re_division,
        re_page_marker=re_page_marker,
        re_volume_header=re_volume_header,
        re_philippine_reports=re_philippine_reports,
        re_short_title=re_short_title,
        re_syllabus_header=re_syllabus_header,
        re_case_bracket=re_case_bracket,
        re_case_bracket_no_close=re_case_bracket_no_close,
        re_syllabus=re_syllabus,
        re_counsel_header=re_counsel_header,
        re_doc_type=re_doc_type,
        re_ponente=re_ponente,
        re_per_curiam=re_per_curiam,
        re_so_ordered=re_so_ordered,
        re_separate_opinion=re_separate_opinion,
        re_votes_content=re_votes_content,
        re_footnote_start=re_footnote_start,
        re_wherefore=re_wherefore,
        re_counsel_designation=re_counsel_designation,
        re_parties_end=re_parties_end,
        re_vs_line=re_vs_line,
    )

    # Apply overrides
    for key, value in overrides.items():
        if not hasattr(config, key):
            raise ValueError(f"Unknown EraConfig field: {key}")
        setattr(config, key, value)
    
    return config


# Module-level registry
_ERA_CONFIGS: Dict[str, EraConfig] = {}


def _init_registry():
    """Build era configs. Called once at module load."""
    for era in DEFAULT_ERAS:
        overrides = {}
        if era.name == "era5":
            overrides["has_syllabus"] = False
        elif era.name == "era2":
            # ERA-2 (261-500): 1990-2005 volumes with long votes, OCR quirks,
            # and formatting anomalies like page-break-split votes and
            # pre-header parties (e.g., Estrada vs. Sandiganbayan, Vol 421).
            overrides["votes_len_range"] = (20, 1500)
            overrides["votes_max_non_blank_lines"] = 30
            overrides["votes_continuation_lookahead"] = 10
            overrides["votes_extend_past_boundary"] = True
            # Require trailing colon/semicolon on opinion headers to prevent
            # false positives from body-text cross-references in multi-opinion
            # cases (e.g., G.R. No. 133879 has 3 opinions citing each other).
            overrides["re_separate_opinion"] = re.compile(
                r'^([A-Z][A-Z\s,.\'\-]+?),\s*(?:C\.?\s*J\.?\s*|J\.?\s*),?\s*'
                r'(?:concurring|dissenting|separate)\b'
                r'.*[:\;]\s*$',
                re.IGNORECASE
            )
            # OCR-tolerant party designations: handles pétitioner (accent),
            # respondeni (OCR i-for-t), and similar single-char OCR errors.
            overrides["re_parties_end"] = re.compile(
                r'(?:respond.n.s?|p.titioners?|plaintiffs?|defendants?|appellants?|appellees?|'
                r'accused-appellants?|intervenors?|oppositors?)\s*[.,;]*\s*$',
                re.IGNORECASE
            )
        _ERA_CONFIGS[era.name] = _build_baseline_config(era.name, **overrides)


_init_registry()


def get_era(vol_num: Optional[int]) -> Era:
    """Find the era for a volume number. Returns era1 if vol_num is None or out of range."""
    if vol_num is None:
        return DEFAULT_ERAS[0]
    for era in DEFAULT_ERAS:
        if era.vol_start <= vol_num <= era.vol_end:
            return era
    logger.warning(f"Volume {vol_num} outside all era ranges, defaulting to era1")
    return DEFAULT_ERAS[0]


def get_era_config(vol_num: Optional[int] = None) -> EraConfig:
    """Get the EraConfig for a volume number."""
    era = get_era(vol_num)
    return _ERA_CONFIGS[era.name]


def get_fallback_order(vol_num: Optional[int]) -> List[str]:
    """Get era names in outward-from-matched order for fallthrough.

    Example for vol_num=600 (era3): ['era3', 'era4', 'era2', 'era5', 'era1']
    Tries adjacent eras alternating right then left.
    """
    matched = get_era(vol_num)
    matched_idx = next(i for i, e in enumerate(DEFAULT_ERAS) if e.name == matched.name)
    order = [matched.name]
    left, right = matched_idx - 1, matched_idx + 1
    while left >= 0 or right < len(DEFAULT_ERAS):
        if right < len(DEFAULT_ERAS):
            order.append(DEFAULT_ERAS[right].name)
            right += 1
        if left >= 0:
            order.append(DEFAULT_ERAS[left].name)
            left -= 1
    return order


def get_era_config_by_name(era_name: str) -> EraConfig:
    """Get EraConfig by era name. Used during fallthrough."""
    return _ERA_CONFIGS[era_name]


if __name__ == "__main__":
    """Test block."""
    print("Testing pattern_registry.py...")
    
    # Test era selection
    print("\n1. Era selection:")
    test_volumes = [None, 226, 421, 600, 813, 960, 9999]
    for vol in test_volumes:
        era = get_era(vol)
        print(f"  Volume {vol}: {era.name} ({era.description})")
    
    # Test config retrieval
    print("\n2. Config retrieval:")
    for vol in [226, 421, 600, 813, 960]:
        config = get_era_config(vol)
        print(f"  Volume {vol}: era={config.era_name}, has_syllabus={config.has_syllabus}")
    
    # Test fallback order
    print("\n3. Fallback order:")
    for vol in [226, 421, 600, 813, 960]:
        order = get_fallback_order(vol)
        print(f"  Volume {vol}: {order}")
    
    # Test pattern compilation
    print("\n4. Pattern compilation (spot check):")
    config = get_era_config(226)
    print(f"  re_division pattern: {config.re_division.pattern[:50]}...")
    print(f"  re_case_bracket pattern: {config.re_case_bracket.pattern[:50]}...")
    print(f"  re_doc_type pattern: {config.re_doc_type.pattern[:50]}...")
    
    # Test era5 has_syllabus=False
    print("\n5. Era5 special handling:")
    era5_config = get_era_config(960)
    print(f"  era5 has_syllabus: {era5_config.has_syllabus}")
    era1_config = get_era_config(226)
    print(f"  era1 has_syllabus: {era1_config.has_syllabus}")
    
    print("\nAll tests completed successfully!")