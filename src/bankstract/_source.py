"""
Generic source type accepted at every parse/redact entry point.

Path or seekable binary stream — covers filesystem inputs, BytesIO buffers
(stdin), and any future format (PDF, XLSX, CSV, etc.). Lives in its own
module so format-specific boundary modules (`_pdfplumber`, `_xlsx`) all
import the same alias instead of redefining it.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO

Source = Path | IO[bytes]


def rewind(source: Source) -> None:
    """Reset the stream cursor to 0 if `source` is a file-like. No-op for
    `Path`. Every reader (pdfplumber, openpyxl) needs the source at offset
    0 — callers that may pass the same handle to multiple readers in a row
    rewind between calls instead of caring about file-vs-stream branching."""
    seek = getattr(source, "seek", None)
    if seek is not None:
        seek(0)
