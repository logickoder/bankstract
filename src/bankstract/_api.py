"""
Public Python API. Lifecycle promise: every name re-exported from
`bankstract.__init__` is part of the semver-stable surface; everything
else (modules prefixed `_`, parser internals, redactor internals) may
change in any release.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO

from ._pdfplumber import PdfSource
from .parsers import all_parsers, get
from .schema import ParseError, ParseResult

Source = Path | IO[bytes] | str


def _normalize(source: Source) -> PdfSource:
    if isinstance(source, str):
        return Path(source)
    return source


def _rewind(source: PdfSource) -> None:
    seek = getattr(source, "seek", None)
    if seek is not None:
        seek(0)


def list_parsers() -> list[str]:
    """Names of every registered parser, sorted alphabetically."""
    return sorted(all_parsers())


def detect(source: Source) -> str | None:
    """Return the bank name whose parser scores highest on `source`, or
    None if no parser claims it."""
    src = _normalize(source)
    candidates = [(name, p.detect_confidence(src)) for name, p in all_parsers().items()]
    _rewind(src)
    candidates.sort(key=lambda t: t[1], reverse=True)
    if not candidates or candidates[0][1] <= 0:
        return None
    return candidates[0][0]


def parse(source: Source, *, bank: str | None = None) -> ParseResult:
    """Parse `source` into a ParseResult.

    `bank=None` auto-detects via `detect_confidence` (picks max-scoring
    parser). Pass an explicit bank name to skip detection. `source` may be
    a `pathlib.Path`, a string path, or a seekable binary stream
    (e.g. `io.BytesIO`)."""
    src = _normalize(source)
    if bank is None:
        name = detect(src)
        if name is None:
            raise ParseError("no registered parser detected this PDF")
        parser = get(name)
    else:
        parser = get(bank)
    _rewind(src)
    return parser.parse(src)
