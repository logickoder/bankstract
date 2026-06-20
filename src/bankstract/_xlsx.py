"""
Typed facade over openpyxl + format-sniff helper.

Same boundary rationale as _pdfplumber: keep the untyped third-party
surface in one file so the rest of the codebase stays clean. The sniff
helper lives here because XLSX detection (magic bytes + openpyxl
fail-fast) is the cheap side of the dispatch — PDF detection is a single
header byte check.
"""

from __future__ import annotations

import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from openpyxl import load_workbook  # type: ignore[import-untyped]
from openpyxl.utils.exceptions import InvalidFileException  # type: ignore[import-untyped]

from ._source import Source, rewind
from .schema import EncryptedSourceError, Format

_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK"
# CDFV2 (Compound File Binary Format) container — the wrapper MS Office uses
# for encrypted OOXML files. A real encrypted XLSX is a CDFV2 envelope, not
# a ZIP, so openpyxl's zipfile reader raises BadZipFile on it. Sniffing the
# magic up front lets us surface EncryptedSourceError instead.
_CDFV2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def is_cdfv2(source: Source) -> bool:
    """True if `source` opens with the CDFV2 container magic. A non-encrypted
    XLSX never starts with this — it's plain ZIP. Encrypted OOXML, .doc, .xls
    and other legacy Office formats do."""
    return _peek(source, 8).startswith(_CDFV2_MAGIC)


def sniff_format(source: Source) -> Format:
    """Detect input format. Extension first (O(1), 100% reliable when
    present); magic bytes fallback for streams or extension-less paths.
    The ZIP magic-byte match is shared by XLSX / DOCX / PPTX / EPUB /
    JAR — we return 'xlsx' optimistically and let openpyxl raise on a
    real format mismatch downstream. CDFV2 (the MS-OFFCRYPTO envelope)
    also returns 'xlsx' — the file IS an XLSX, just encrypted;
    `open_workbook` re-sniffs and raises `EncryptedSourceError` so the
    user sees actionable copy instead of 'unknown format'."""
    if isinstance(source, Path):
        suffix = source.suffix.lower()
        if suffix == ".pdf":
            return "pdf"
        if suffix == ".xlsx":
            return "xlsx"
    head = _peek(source, 8)
    if head.startswith(_PDF_MAGIC):
        return "pdf"
    if head.startswith(_ZIP_MAGIC) or head.startswith(_CDFV2_MAGIC):
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
    Raises `EncryptedSourceError` when the file is a password-protected
    OOXML wrapped in a CDFV2 envelope. Raises `ValueError` (wrapped to
    `ParseError` by the lib API layer) for genuine non-XLSX inputs."""
    rewind(source)
    handle: Any = source if hasattr(source, "read") else str(source)
    try:
        wb = load_workbook(handle, read_only=True, data_only=True)
    except (InvalidFileException, KeyError, zipfile.BadZipFile) as exc:
        rewind(source)
        if is_cdfv2(source):
            raise EncryptedSourceError("password-protected XLSX") from exc
        raise ValueError(f"not a valid XLSX: {exc}") from exc
    try:
        yield wb
    finally:
        wb.close()
