"""
Public Python API. Lifecycle promise: every name re-exported from
`bankstract.__init__` is part of the semver-stable surface; everything
else (modules prefixed `_`, parser internals, redactor internals) may
change in any release.
"""

from __future__ import annotations

from pathlib import Path

from ._source import Source, rewind
from .parsers import all_parsers, get
from .redactors import all_redactors
from .redactors import get as get_redactor
from .schema import ParseError, ParseResult, RedactResult

# Lib API accepts a string path as a friendly shorthand on top of the
# strict Path | IO[bytes] union used internally. Distinct name from
# `Source` so contributors don't confuse the public ergonomic union with
# the strict internal one.
SourceLike = Source | str


def _normalize(source: SourceLike) -> Source:
    if isinstance(source, str):
        return Path(source)
    return source


def list_parsers() -> list[str]:
    """Names of every registered parser, sorted alphabetically."""
    return sorted(all_parsers())


def list_redactors() -> list[str]:
    """Names of every registered redactor, sorted alphabetically."""
    return sorted(all_redactors())


def detect(source: SourceLike) -> str | None:
    """Return the bank name whose parser scores highest on `source`, or
    None if no parser claims it."""
    src = _normalize(source)
    candidates = [(name, p.detect_confidence(src)) for name, p in all_parsers().items()]
    rewind(src)
    candidates.sort(key=lambda t: t[1], reverse=True)
    if not candidates or candidates[0][1] <= 0:
        return None
    return candidates[0][0]


def _detect_redactor(source: Source) -> str | None:
    """Mirror of `detect` but iterating registered redactors. Each registered
    redactor's bank name maps 1:1 to the matching parser; we route via the
    parser's detect_confidence to avoid duplicating detection logic."""
    parsers = all_parsers()
    redactor_names = set(all_redactors())
    candidates: list[tuple[str, float]] = []
    for name, parser in parsers.items():
        if name not in redactor_names:
            continue
        candidates.append((name, parser.detect_confidence(source)))
    rewind(source)
    candidates.sort(key=lambda t: t[1], reverse=True)
    if not candidates or candidates[0][1] <= 0:
        return None
    return candidates[0][0]


def redact(source: SourceLike, *, bank: str | None = None) -> RedactResult:
    """Redact `source` into a `RedactResult` carrying bytes + metadata.

    `bank=None` auto-detects via `detect_confidence` on every registered
    redactor's matching parser. Pass an explicit bank name to skip
    detection. `source` may be a `pathlib.Path`, a string path, or a
    seekable binary stream (e.g. `io.BytesIO`). Output is always in-memory
    bytes — the redactor never writes to disk on this path, so streaming
    callers (HTTP responses, archives, Cloud workers) get the payload
    without tempfile cleanup. Unrecognised format → `ParseError`."""
    src = _normalize(source)
    if bank is None:
        try:
            name = _detect_redactor(src)
        except ValueError as exc:
            raise ParseError(str(exc)) from exc
        if name is None:
            raise ParseError("no registered redactor detected this source")
        redactor = get_redactor(name)
    else:
        redactor = get_redactor(bank)
    rewind(src)
    try:
        return redactor.redact(src)
    except ValueError as exc:
        raise ParseError(str(exc)) from exc


def parse(source: SourceLike, *, bank: str | None = None) -> ParseResult:
    """Parse `source` into a ParseResult.

    `bank=None` auto-detects via `detect_confidence` (picks max-scoring
    parser). Pass an explicit bank name to skip detection. `source` may be
    a `pathlib.Path`, a string path, or a seekable binary stream
    (e.g. `io.BytesIO`). An unrecognised format (neither PDF nor XLSX)
    surfaces as a `ParseError`, not a bare `ValueError`."""
    src = _normalize(source)
    if bank is None:
        try:
            name = detect(src)
        except ValueError as exc:
            raise ParseError(str(exc)) from exc
        if name is None:
            raise ParseError("no registered parser detected this source")
        parser = get(name)
    else:
        parser = get(bank)
    rewind(src)
    try:
        return parser.parse(src)
    except ValueError as exc:
        raise ParseError(str(exc)) from exc
