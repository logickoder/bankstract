import io
from typing import get_args

from ..schema import OutputFormat, ParseResult
from .csv import write_csv
from .json import write_json


def check_format(format: str) -> None:
    allowed = get_args(OutputFormat)
    if format not in allowed:
        raise ValueError(f"unsupported output format: {format!r} (expected one of {allowed})")


def serialize(result: ParseResult, format: OutputFormat) -> bytes:
    """Canonical bytes for `result`, the same `convert()` (and so the CLI)
    emits. Add a format: a writer module, `OutputFormat`, and a `case` here."""
    check_format(format)
    buf = io.StringIO()
    match format:
        case "csv":
            write_csv(result.transactions, buf)
        case "json":
            write_json(result, buf)
    # csv.writer emits "\r\n" per RFC 4180; StringIO doesn't translate.
    # The replace catches a wrapped stream that double-translates (Windows
    # text mode). Idempotent on clean input.
    return buf.getvalue().encode("utf-8").replace(b"\r\r\n", b"\r\n")
