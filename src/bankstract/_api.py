"""
Public Python API. Lifecycle promise: every name re-exported from
`bankstract.__init__` is part of the semver-stable surface; everything
else (modules prefixed `_`, parser internals, redactor internals) may
change in any release.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal, TypeVar

from ._source import Source, rewind
from .parsers import all_parsers, get
from .parsers.base import Parser
from .reconcile import reconcile as _reconcile_rows
from .reconcile import verify_totals
from .redactors import all_redactors
from .redactors import get as get_redactor
from .redactors.base import Redactor
from .schema import ParseError, ParseResult, RedactResult
from .writers.csv import write_csv
from .writers.json import write_json

# Lib API accepts a string path as a friendly shorthand on top of the
# strict Path | IO[bytes] union used internally. Distinct name from
# `Source` so contributors don't confuse the public ergonomic union with
# the strict internal one.
SourceLike = Source | str

_W = TypeVar("_W", ParseResult, RedactResult)


def _normalize(source: SourceLike) -> Source:
    if isinstance(source, str):
        return Path(source)
    return source


def _pick_max(scored: Iterable[tuple[str, float]]) -> str | None:
    """Pick the name with the highest positive score; None on no positive
    candidate. Ties resolve to first-seen (insertion order) because
    `sorted()` is stable."""
    ordered = sorted(scored, key=lambda t: t[1], reverse=True)
    if not ordered or ordered[0][1] <= 0:
        return None
    return ordered[0][0]


def _confidence(bank: str, source: Source) -> float:
    """detect_confidence lives on the Parser, not the Redactor — they share
    the same markers. Look up via the parser registry; return 0.0 if no
    parser registered (a redactor without a sibling parser is unusual but
    not illegal)."""
    parser = all_parsers().get(bank)
    if parser is None:
        return 0.0
    return parser.detect_confidence(source)


def _detect(source: Source, *, banks: Iterable[str]) -> str | None:
    """Score every named bank via the parser registry, pick the winner."""
    scored = [(name, _confidence(name, source)) for name in banks]
    rewind(source)
    return _pick_max(scored)


def list_parsers() -> list[str]:
    """Names of every registered parser, sorted alphabetically."""
    return sorted(all_parsers())


def list_redactors() -> list[str]:
    """Names of every registered redactor, sorted alphabetically."""
    return sorted(all_redactors())


def detect(source: SourceLike) -> str | None:
    """Return the bank name whose parser scores highest on `source`, or
    None if no parser claims it."""
    return _detect(_normalize(source), banks=all_parsers().keys())


def _dispatch(
    source: SourceLike,
    *,
    bank: str | None,
    registry_lookup: Callable[[str], Parser | Redactor],
    candidate_banks: Iterable[str],
    worker: Callable[[Parser | Redactor, Source], _W],
    none_match_msg: str,
) -> _W:
    """Shared auto-detect-or-explicit + invoke flow.

    Both `parse()` and `redact()` walk the same path: normalize, pick a
    bank (auto or explicit), fetch from the matching registry, rewind,
    invoke. Wrapping bare `ValueError` as `ParseError` keeps the public
    exception surface consistent across format-sniff failures and parser
    layout drift.
    """
    src = _normalize(source)
    if bank is None:
        try:
            name = _detect(src, banks=candidate_banks)
        except ValueError as exc:
            raise ParseError(str(exc)) from exc
        if name is None:
            raise ParseError(none_match_msg)
        target = registry_lookup(name)
    else:
        target = registry_lookup(bank)
    rewind(src)
    try:
        return worker(target, src)
    except ValueError as exc:
        raise ParseError(str(exc)) from exc


def parse(source: SourceLike, *, bank: str | None = None) -> ParseResult:
    """Parse `source` into a ParseResult.

    `bank=None` auto-detects via `detect_confidence` (picks max-scoring
    parser). Pass an explicit bank name to skip detection. `source` may be
    a `pathlib.Path`, a string path, or a seekable binary stream
    (e.g. `io.BytesIO`). An unrecognised format (neither PDF nor XLSX)
    surfaces as a `ParseError`, not a bare `ValueError`."""

    def _parse_call(parser: Parser | Redactor, src: Source) -> ParseResult:
        assert isinstance(parser, Parser)  # _dispatch contract: registry returns Parser
        return parser.parse(src)

    return _dispatch(
        source,
        bank=bank,
        registry_lookup=get,
        candidate_banks=all_parsers().keys(),
        worker=_parse_call,
        none_match_msg="no registered parser detected this source",
    )


def parse_to(
    source: SourceLike,
    *,
    format: Literal["csv", "json"] = "csv",
    bank: str | None = None,
    reconcile: bool = True,
) -> bytes:
    """Parse `source` and serialize the result to bytes in one call.

    Mirrors the CLI's parse + write code path exactly — same writer, same
    column order, same encoding. Use this from HTTP handlers, stdout pipes,
    or anywhere bytes are needed without staging a temp file.

    `format` matches the CLI `-f` flag: "csv" (default) or "json".
    `reconcile=True` (default) runs the reconciliation invariant before
    serializing. Caller chooses on/off per call — Cloud workers may want a
    debug-skip path or a strict-only path; same engine code path either way.

    `bank=None` auto-detects via `detect_confidence`; pass an explicit bank
    name to skip detection. `source` accepts a `pathlib.Path`, a string path,
    or a seekable binary stream (e.g. `io.BytesIO`). An unrecognised
    output `format` raises `ValueError`; a layout mismatch surfaces as
    `ParseError`; an invariant break surfaces as `ReconciliationError`.
    """
    if format not in ("csv", "json"):
        raise ValueError(f"unsupported output format: {format!r} (expected 'csv' or 'json')")

    result = parse(source, bank=bank)

    if reconcile:
        # Run every check the parser supplied evidence for. verify_totals is
        # sum-based (needs header totals); _reconcile_rows is row-wise (needs a
        # balance column). Banks like FBN ship both — totals catch dropped
        # rows, row-wise catches per-row arithmetic that happens to sum out.
        if result.total_credit is not None and result.total_debit is not None:
            verify_totals(
                result.transactions,
                total_credit=result.total_credit,
                total_debit=result.total_debit,
            )
        if result.row_wise_reconcilable:
            _reconcile_rows(result.transactions)

    buf = io.StringIO()
    if format == "csv":
        write_csv(result.transactions, buf)
    else:
        write_json(result, buf)
    # csv.writer emits "\r\n" per RFC 4180; StringIO doesn't translate.
    # Defensive replace catches any wrapped-stream path that might double-
    # translate (Windows text mode through a layered writer). Idempotent on
    # clean input — already-correct bytes pass through untouched.
    return buf.getvalue().encode("utf-8").replace(b"\r\r\n", b"\r\n")


def redact(source: SourceLike, *, bank: str | None = None) -> RedactResult:
    """Redact `source` into a `RedactResult` carrying bytes + metadata.

    `bank=None` auto-detects via `detect_confidence` on every registered
    redactor's matching parser. Pass an explicit bank name to skip
    detection. `source` may be a `pathlib.Path`, a string path, or a
    seekable binary stream (e.g. `io.BytesIO`). Output is always in-memory
    bytes — the redactor never writes to disk on this path, so streaming
    callers (HTTP responses, archives, Cloud workers) get the payload
    without tempfile cleanup. Unrecognised format → `ParseError`."""

    def _redact_call(redactor: Parser | Redactor, src: Source) -> RedactResult:
        assert isinstance(redactor, Redactor)
        return redactor.redact(src)

    return _dispatch(
        source,
        bank=bank,
        registry_lookup=get_redactor,
        candidate_banks=all_redactors().keys(),
        worker=_redact_call,
        none_match_msg="no registered redactor detected this source",
    )
