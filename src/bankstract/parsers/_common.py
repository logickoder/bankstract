"""Shared pdfplumber boundary helpers used by every parser."""

from __future__ import annotations

from typing import Any, NoReturn

from .._layout import Word, from_pdfplumber_words
from .._pdfplumber import open_doc
from .._source import Source, rewind
from ..schema import EmptyStatementError, EncryptedSourceError


def extract_words_per_page(source: Source) -> list[list[Word]]:
    rewind(source)
    with open_doc(source) as pdf:
        return [from_pdfplumber_words(page.extract_words()) for page in pdf.pages]


def first_page_text(source: Source) -> str:
    """Return the first page's text, or '' on any open/extract failure.
    Parsers use this from `detect()`, where exceptions must downgrade to a
    negative match rather than propagate.

    `EncryptedSourceError` is the one explicit exception: a password-protected
    PDF can't be read by anyone, so swallowing it on auto-detect would silently
    downgrade to `ParseError("no parser detected")` — burying the actionable
    cause from Cloud / CLI consumers. Let it propagate so callers see the
    typed exception."""
    rewind(source)
    try:
        with open_doc(source) as pdf:
            pages: list[Any] = pdf.pages
            if not pages:
                return ""
            return pages[0].extract_text() or ""
    except EncryptedSourceError:
        raise
    except Exception:
        return ""


def raise_empty_pdf(format_version: str) -> NoReturn:
    """Raise the canonical EmptyStatementError for a PDF that yielded zero
    extractable words. marker_coverage=0.0 because the parser never got
    far enough to score markers."""
    raise EmptyStatementError(
        "empty PDF",
        format_version=format_version,
        marker_coverage=0.0,
    )


def raise_no_transactions(
    *,
    format_version: str,
    text: str,
    markers: tuple[str, ...],
) -> NoReturn:
    """Raise the canonical EmptyStatementError for the post-walk path:
    parser ran clean, extracted zero transactions. marker_coverage is the
    fraction of `markers` present in `text` — high coverage points at a
    legitimately empty statement, lower coverage at silent layout drift."""
    raise EmptyStatementError(
        "no transactions parsed — empty statement or silent layout drift",
        format_version=format_version,
        marker_coverage=marker_fraction(text, markers),
    )


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
    need to look past page 1 (e.g. closing balance on the last page).
    Same `EncryptedSourceError` re-raise rule as `first_page_text`."""
    rewind(source)
    try:
        with open_doc(source) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except EncryptedSourceError:
        raise
    except Exception:
        return ""
