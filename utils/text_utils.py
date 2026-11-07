"""
TOKENFORGE — Text Processing Utilities
========================================
Functions for whitespace normalisation, header/footer removal, markdown
cleanup, content-type heuristics, OCR artifact correction, and compact
formatting.
"""

import re
import unicodedata
from collections import Counter
from typing import List, Optional, Tuple


# ── Whitespace normalisation ────────────────────────────────────────────────


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces / newlines and strip leading/trailing space.

    * Runs of whitespace *within* a line become a single space.
    * Three or more consecutive newlines become exactly two (one blank line).
    * Leading and trailing whitespace is stripped from each line and from the
      whole result.
    """
    if not text:
        return ""
    # Normalize each line individually
    lines = text.splitlines()
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
    # Rejoin, then collapse excessive blank lines (3+ newlines -> 2)
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def collapse_blank_lines(text: str) -> str:
    """Collapse 3 or more consecutive newlines into 2 (at most one blank line)."""
    if not text:
        return ""
    text = re.sub(r"\r\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def strip_excessive_newlines(text: str) -> str:
    """Strip redundant newlines from start, end, and internal runs."""
    if not text:
        return ""
    text = re.sub(r"\r\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ── Repeated-line removal ───────────────────────────────────────────────────


def remove_repeated_lines(text: str, threshold: int = 3) -> str:
    """Remove lines that repeat more than *threshold* times.

    Useful for stripping recurring headers, footers, or page numbers that
    were merged into a single text stream.
    """
    if not text:
        return ""

    lines = text.splitlines()
    # Count occurrences of each non-empty stripped line
    counts: Counter = Counter()
    for line in lines:
        stripped = line.strip()
        if stripped:
            counts[stripped] += 1

    repeated = {line for line, count in counts.items() if count > threshold}

    filtered = [
        line for line in lines if line.strip() not in repeated
    ]
    return "\n".join(filtered)


# ── Header / Footer detection ───────────────────────────────────────────────


def detect_repeated_headers_footers(
    pages_text: List[str],
    ratio: float = 0.5,
    max_lines: int = 3,
) -> Tuple[List[str], List[str]]:
    """Identify common headers and footers across multiple pages.

    A line that appears in the first *max_lines* (or last *max_lines*) of
    at least ``ratio`` fraction of pages is considered a header (or footer).

    Parameters
    ----------
    pages_text : list[str]
        A list where each element is the full text of a single page.
    ratio : float
        Minimum fraction of pages a line must appear on (default 0.5 = 50 %).
    max_lines : int
        How many lines from the top / bottom of each page to inspect.

    Returns
    -------
    (headers, footers) : tuple[list[str], list[str]]
    """
    if not pages_text:
        return [], []

    num_pages = len(pages_text)
    min_occurrences = max(2, int(num_pages * ratio))

    header_candidates: Counter = Counter()
    footer_candidates: Counter = Counter()

    for page in pages_text:
        lines = [l.strip() for l in page.splitlines() if l.strip()]
        # Inspect the first few lines
        for line in lines[:max_lines]:
            header_candidates[line] += 1
        # Inspect the last few lines
        for line in lines[-max_lines:]:
            footer_candidates[line] += 1

    headers = [
        line for line, count in header_candidates.items()
        if count >= min_occurrences
    ]
    footers = [
        line for line, count in footer_candidates.items()
        if count >= min_occurrences
    ]

    return headers, footers


def remove_headers_footers(
    text: str,
    headers: List[str],
    footers: List[str],
) -> str:
    """Remove identified *headers* and *footers* from *text*.

    Each matching line is removed entirely.
    """
    if not text or (not headers and not footers):
        return text

    removable = set(headers) | set(footers)
    lines = text.splitlines()
    filtered = [line for line in lines if line.strip() not in removable]
    return "\n".join(filtered)


# ── Markdown normalisation ───────────────────────────────────────────────────


def normalize_markdown(text: str) -> str:
    """Clean up markdown text.

    * Fix heading levels — ensure a single ``#`` top-level heading; shift
      lower-level headings so the minimum heading uses ``##``.
    * Remove excessive blank lines (max one blank line between blocks).
    * Normalize unordered list markers to ``-``.
    * Strip trailing whitespace from every line.
    """
    if not text:
        return ""

    lines = text.splitlines()

    # --- Normalize list markers (*, +) -> - ----------------------------------
    normalized: List[str] = []
    for line in lines:
        stripped = line.lstrip()
        if re.match(r"^[*+]\s", stripped):
            indent = len(line) - len(stripped)
            normalized.append(" " * indent + "-" + stripped[1:])
        else:
            normalized.append(line)
    lines = normalized

    # --- Normalize heading levels --------------------------------------------
    heading_re = re.compile(r"^(#{1,6})\s")
    heading_levels: List[int] = []
    for line in lines:
        m = heading_re.match(line)
        if m:
            heading_levels.append(len(m.group(1)))

    if heading_levels:
        min_level = min(heading_levels)
        # Shift so that the smallest heading is level 1
        if min_level > 1:
            shift = min_level - 1
            shifted: List[str] = []
            for line in lines:
                m = heading_re.match(line)
                if m:
                    current = len(m.group(1))
                    new_level = max(1, current - shift)
                    shifted.append("#" * new_level + line[current:])
                else:
                    shifted.append(line)
            lines = shifted

    # --- Strip trailing whitespace -------------------------------------------
    lines = [line.rstrip() for line in lines]

    # --- Collapse excessive blank lines (max 1 blank line) -------------------
    result_lines: List[str] = []
    prev_blank = False
    for line in lines:
        if not line:
            if prev_blank:
                continue  # skip additional blank line
            prev_blank = True
        else:
            prev_blank = False
        result_lines.append(line)

    return "\n".join(result_lines).strip()


# ── Compact formatting ──────────────────────────────────────────────────────


def render_table(table_data: List[List[str]], compact: bool = True) -> str:
    """Render rows as a Markdown table.

    ``compact=True`` drops the padding spaces (``|a|b|`` + ``|-|-|``), which is
    still valid GitHub-flavoured Markdown but costs noticeably fewer tokens.
    """
    if not table_data:
        return ""
    rows = [[str(c).replace("|", "\\|").replace("\n", " ").strip() for c in r] for r in table_data]
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    if compact:
        sep = "|" + "|".join("-" for _ in range(n)) + "|"
        out = ["|" + "|".join(rows[0]) + "|", sep]
        out += ["|" + "|".join(r) + "|" for r in rows[1:]]
    else:
        sep = "| " + " | ".join("---" for _ in range(n)) + " |"
        out = ["| " + " | ".join(rows[0]) + " |", sep]
        out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def compact_table_format(table_data: List[List[str]]) -> str:
    """Convert a 2D table into a compact markdown table string.

    The first row is treated as the header.

    >>> compact_table_format([["Name", "Age"], ["Alice", "30"]])
    '| Name | Age |\\n| --- | --- |\\n| Alice | 30 |'
    """
    if not table_data:
        return ""

    # Ensure every row is a list of strings
    rows = [[str(cell).strip() for cell in row] for row in table_data]

    # Determine the number of columns from the widest row
    num_cols = max(len(row) for row in rows)

    # Pad short rows
    for row in rows:
        while len(row) < num_cols:
            row.append("")

    lines: List[str] = []
    # Header
    header = "| " + " | ".join(rows[0]) + " |"
    separator = "| " + " | ".join("---" for _ in range(num_cols)) + " |"
    lines.append(header)
    lines.append(separator)

    # Data rows
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def compact_list_format(items: List[str]) -> str:
    """Format a list compactly, one item per line with ``-`` markers.

    Empty/whitespace-only items are skipped.

    >>> compact_list_format(["apples", "bananas"])
    '- apples\\n- bananas'
    """
    if not items:
        return ""
    return "\n".join(
        f"- {item.strip()}" for item in items if item.strip()
    )


# ── Content-type heuristics ─────────────────────────────────────────────────


def estimate_content_type(text: str) -> str:
    """Heuristically classify *text* as one of:

    ``'narrative'``, ``'tabular'``, ``'list'``, ``'code'``, or ``'mixed'``.

    The classification is based on surface-level patterns; it does **not**
    perform deep NLP analysis.
    """
    if not text or not text.strip():
        return "narrative"

    lines = [l for l in text.splitlines() if l.strip()]
    total_lines = len(lines)
    if total_lines == 0:
        return "narrative"

    # --- Code detection -------------------------------------------------------
    code_indicators = 0
    code_patterns = [
        r"^\s*(def |class |import |from |if |for |while |return |#!)",
        r"[{};]\s*$",
        r"^\s*(public |private |void |int |string )",
        r"=>|->|\|\||&&",
        r"^\s*//",
        r'^\s*["\']use strict["\']',
    ]
    for line in lines:
        for pattern in code_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                code_indicators += 1
                break
    if code_indicators / total_lines > 0.3:
        return "code"

    # --- Tabular detection (pipes or tab-delimited) --------------------------
    table_lines = sum(
        1 for l in lines if l.count("|") >= 2 or l.count("\t") >= 2
    )
    if table_lines / total_lines > 0.4:
        return "tabular"

    # --- List detection -------------------------------------------------------
    list_patterns = re.compile(
        r"^\s*[-*+•]\s|^\s*\d+[.)]\s|^\s*[a-zA-Z][.)]\s"
    )
    list_lines = sum(1 for l in lines if list_patterns.match(l))
    if list_lines / total_lines > 0.4:
        return "list"

    # --- Mixed detection (significant presence of multiple types) ------------
    scores = {
        "table": table_lines / total_lines,
        "list": list_lines / total_lines,
        "code": code_indicators / total_lines,
    }
    significant = sum(1 for v in scores.values() if v > 0.15)
    if significant >= 2:
        return "mixed"

    return "narrative"


# ── OCR cleanup ──────────────────────────────────────────────────────────────

# Common OCR mis-recognitions (pattern -> replacement)
_OCR_REPLACEMENTS: List[Tuple[str, str]] = [
    (r"\bl\b(?=[A-Z])", "I"),         # lowercase-L before uppercase -> I
    (r"(?<=[a-z])0(?=[a-z])", "o"),   # zero between lowercase letters -> o
    (r"\brn\b", "m"),                 # 'rn' as standalone -> 'm' (careful)
    (r"(?<=\w)l1(?=\w)", "ll"),      # l1 inside word -> ll
    (r"\|(?=[a-zA-Z])", "l"),        # pipe before letter -> l
    (r"(?<=[a-zA-Z])\|", "l"),       # pipe after letter -> l
]

# Unicode categories for "garbage" characters
_GARBAGE_CATEGORIES = {"Cc", "Co", "Cf", "Cn"}
# But keep common control chars
_KEEP_CHARS = {"\n", "\r", "\t"}


def clean_ocr_text(text: str) -> str:
    """Clean up common OCR artifacts.

    * Applies common character-substitution fixes.
    * Removes non-printable / garbage Unicode characters (keeping newlines
      and tabs).
    * Collapses runs of spaces.
    """
    if not text:
        return ""

    # Remove garbage Unicode characters
    cleaned_chars: List[str] = []
    for ch in text:
        if ch in _KEEP_CHARS:
            cleaned_chars.append(ch)
        elif unicodedata.category(ch) not in _GARBAGE_CATEGORIES:
            cleaned_chars.append(ch)
    result = "".join(cleaned_chars)

    # Apply substitution patterns
    for pattern, replacement in _OCR_REPLACEMENTS:
        result = re.sub(pattern, replacement, result)

    # Fix common punctuation artifacts
    result = re.sub(r"\s+([.,;:!?])", r"\1", result)   # space before punctuation
    result = re.sub(r"([.,;:!?])(?=[A-Za-z])", r"\1 ", result)  # missing space after punct

    # Collapse runs of spaces (not newlines)
    result = re.sub(r"[ \t]+", " ", result)

    # Remove leading spaces on each line
    result = "\n".join(line.lstrip(" ") for line in result.splitlines())

    return result.strip()


# ── Preview truncation ───────────────────────────────────────────────────────


def truncate_for_preview(text: str, max_chars: int = 2000) -> str:
    """Truncate *text* to at most *max_chars*, appending ``…`` if trimmed.

    The cut happens at the last space before the limit so words are not
    split mid-way.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    # Try to cut at the last space before the limit
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.5:
        truncated = truncated[:last_space]

    return truncated.rstrip() + "…"
