"""Shared pdfplumber boundary helpers used by every parser."""

from __future__ import annotations

from typing import Any

from .._layout import Word, from_pdfplumber_words
from .._pdfplumber import open_doc
from .._source import Source, rewind


def extract_words_per_page(source: Source) -> list[list[Word]]:
    rewind(source)
    with open_doc(source) as pdf:
        return [from_pdfplumber_words(page.extract_words()) for page in pdf.pages]


def first_page_text(source: Source) -> str:
    """Return the first page's text, or '' on any open/extract failure.
    Parsers use this from `detect()`, where exceptions must downgrade to a
    negative match rather than propagate."""
    rewind(source)
    try:
        with open_doc(source) as pdf:
            pages: list[Any] = pdf.pages
            if not pages:
                return ""
            return pages[0].extract_text() or ""
    except Exception:
        return ""


def marker_fraction(text: str, markers: tuple[str, ...]) -> float:
    """Fraction of `markers` substrings present in `text`. Shared by every
    parser's `detect_confidence` and by `EmptyStatementError.marker_coverage`
    computation at raise sites — the two must stay in lockstep so Cloud /
    CLI can compare the coverage on a failed parse to the confidence used
    for detection."""
    if not markers:
        return 0.0
    return sum(1 for m in markers if m in text) / len(markers)


def all_pages_text(source: Source) -> str:
    """Concatenated text from every page — used by metadata extractors that
    need to look past page 1 (e.g. closing balance on the last page)."""
    rewind(source)
    try:
        with open_doc(source) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:
        return ""
