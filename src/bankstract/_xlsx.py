"""
Typed facade over openpyxl + format-sniff helper.

Same boundary rationale as _pdfplumber: keep the untyped third-party
surface in one file so the rest of the codebase stays clean. The sniff
helper lives here because XLSX detection (magic bytes + openpyxl
fail-fast) is the cheap side of the dispatch — PDF detection is a single
header byte check.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from openpyxl import load_workbook  # type: ignore[import-untyped]
from openpyxl.utils.exceptions import InvalidFileException  # type: ignore[import-untyped]

from ._source import Source, rewind
from .schema import Format

_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK"


def sniff_format(source: Source) -> Format:
    """Detect input format. Extension first (O(1), 100% reliable when
    present); magic bytes fallback for streams or extension-less paths.
    The ZIP magic-byte match is shared by XLSX / DOCX / PPTX / EPUB /
    JAR — we return 'xlsx' optimistically and let openpyxl raise on a
    real format mismatch downstream (reviewer's Option 1)."""
    if isinstance(source, Path):
        suffix = source.suffix.lower()
        if suffix == ".pdf":
            return "pdf"
        if suffix == ".xlsx":
            return "xlsx"
    head = _peek(source, 4)
    if head.startswith(_PDF_MAGIC):
        return "pdf"
    if head.startswith(_ZIP_MAGIC):
        return "xlsx"
    raise ValueError(f"unknown source format (head={head!r})")


def _peek(source: Source, n: int) -> bytes:
    if isinstance(source, Path):
        with source.open("rb") as f:
            return f.read(n)
    # Always peek from offset 0, not the current position. Callers in the
    # CLI / lib API run detect_confidence on every parser before reaching
    # sniff_format, and each parser's reader (pdfplumber / openpyxl)
    # advances the stream cursor. Reading from the leftover position
    # would return mid-document bytes that don't match PDF/ZIP magic.
    source.seek(0)
    try:
        return source.read(n)
    finally:
        source.seek(0)


@contextmanager
def open_workbook(source: Source) -> Any:
    """Open an XLSX file read-only + data-only (formulas pre-evaluated).
    Raises ValueError if the source isn't actually XLSX — caller wraps as
    ParseError so the CLI / lib API gets a clean failure message."""
    rewind(source)
    handle: Any = source if hasattr(source, "read") else str(source)
    try:
        wb = load_workbook(handle, read_only=True, data_only=True)
    except (InvalidFileException, KeyError) as exc:
        raise ValueError(f"not a valid XLSX: {exc}") from exc
    try:
        yield wb
    finally:
        wb.close()
