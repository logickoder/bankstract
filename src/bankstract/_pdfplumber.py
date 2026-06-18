"""
Typed facade over pdfplumber.

Same rationale as _pymupdf: restrict the untyped third-party surface to one
file so the rest of the codebase stays clean under pyright/Pylance strict.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

import pdfplumber as _pdfplumber  # type: ignore[import-untyped]

# Accepted at every entry point — parser ABCs, CLI, lib API. File-like
# inputs must be seekable (pdfplumber reads the trailer); CLI buffers stdin
# into BytesIO before handing it down.
PdfSource = Path | IO[bytes]


@contextmanager
def open_doc(source: PdfSource) -> Any:
    handle: Any = source if hasattr(source, "read") else str(source)
    pdf = _pdfplumber.open(handle)
    try:
        yield pdf
    finally:
        pdf.close()
