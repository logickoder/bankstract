"""
Typed facade over pdfplumber.

Same rationale as _pymupdf: restrict the untyped third-party surface to one
file so the rest of the codebase stays clean under pyright/Pylance strict.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pdfplumber as _pdfplumber  # type: ignore[import-untyped]
from pdfminer.pdfdocument import PDFPasswordIncorrect  # type: ignore[import-untyped]
from pdfplumber.utils.exceptions import PdfminerException  # type: ignore[import-untyped]

from ._source import Source
from .schema import EncryptedSourceError


@contextmanager
def open_doc(source: Source) -> Any:
    handle: Any = source if hasattr(source, "read") else str(source)
    try:
        pdf = _pdfplumber.open(handle)
    except PdfminerException as exc:
        # pdfplumber wraps pdfminer errors uniformly; the original lives at
        # exc.args[0]. PDFPasswordIncorrect is raised when pdfminer needs a
        # password (the default empty string fails). Other PdfminerException
        # causes (malformed XREF, corrupt streams) bubble unchanged.
        if exc.args and isinstance(exc.args[0], PDFPasswordIncorrect):
            raise EncryptedSourceError("password-protected PDF") from exc
        raise
    try:
        yield pdf
    finally:
        pdf.close()
