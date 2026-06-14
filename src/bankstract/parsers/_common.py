"""Shared pdfplumber boundary helpers used by every parser."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .._layout import Word, from_pdfplumber_words
from .._pdfplumber import open_doc


def extract_words_per_page(pdf_path: Path) -> list[list[Word]]:
    with open_doc(pdf_path) as pdf:
        return [from_pdfplumber_words(page.extract_words()) for page in pdf.pages]


def first_page_text(pdf_path: Path) -> str:
    """Return the first page's text, or '' on any open/extract failure.
    Parsers use this from `detect()`, where exceptions must downgrade to a
    negative match rather than propagate."""
    try:
        with open_doc(pdf_path) as pdf:
            pages: list[Any] = pdf.pages
            if not pages:
                return ""
            return pages[0].extract_text() or ""
    except Exception:
        return ""
