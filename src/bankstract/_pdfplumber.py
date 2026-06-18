"""
Typed facade over pdfplumber.

Same rationale as _pymupdf: restrict the untyped third-party surface to one
file so the rest of the codebase stays clean under pyright/Pylance strict.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pdfplumber as _pdfplumber  # type: ignore[import-untyped]

from ._source import Source


@contextmanager
def open_doc(source: Source) -> Any:
    handle: Any = source if hasattr(source, "read") else str(source)
    pdf = _pdfplumber.open(handle)
    try:
        yield pdf
    finally:
        pdf.close()
