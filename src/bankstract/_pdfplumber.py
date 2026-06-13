"""
Typed facade over pdfplumber.

Same rationale as _pymupdf: restrict the untyped third-party surface to one
file so the rest of the codebase stays clean under pyright/Pylance strict.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pdfplumber as _pdfplumber  # type: ignore[import-untyped]


@contextmanager
def open_doc(path: Path) -> Any:
    pdf = _pdfplumber.open(str(path))
    try:
        yield pdf
    finally:
        pdf.close()
