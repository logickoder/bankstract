import sys
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

import click

from . import __version__, detect, parse_to
from ._progress import ProgressCallback, ProgressEvent, throttle
from ._source import Source
from ._xlsx import sniff_format
from .parsers import all_parsers, get
from .redactors import all_redactors
from .schema import ParseError, ReconciliationError

# Output format type. Inline Literal at call sites is the Python idiom,
# but the alias here keeps the long function signatures readable. Distinct
# name from `schema.Format` (the INPUT format alias — pdf/xlsx) to avoid
# the "two unrelated Formats" collision flagged in audit.
_OutputFormat = Literal["csv", "json"]


def _read_source(pdf_arg: str) -> Source:
    """`-` reads the entire stdin into BytesIO (pdfplumber needs seek);
    anything else is treated as a filesystem path."""
    if pdf_arg == "-":
        return BytesIO(sys.stdin.buffer.read())
    p = Path(pdf_arg)
    if not p.exists() or not p.is_file():
        raise click.ClickException(f"file not found: {pdf_arg}")
    return p


def _write_bytes(data: bytes, output: str) -> None:
    if output == "-":
        sys.stdout.buffer.write(data)
    else:
        Path(output).write_bytes(data)


def _info(msg: str, *, stdout_used: bool) -> None:
    click.echo(msg, err=stdout_used)


def _stderr_bar(ev: ProgressEvent) -> None:
    """Single-line progress to stderr. Carriage-return overwrites; `done`
    leaves the cursor on a fresh line so the next CLI message starts
    clean."""
    line = f"\r{ev.stage}: {ev.current}/{ev.total}"
    sys.stderr.write(line.ljust(48))
    if ev.stage == "done":
        sys.stderr.write("\n")
    sys.stderr.flush()


def _progress_callback(*, quiet: bool) -> ProgressCallback | None:
    """CLI default: throttled stderr bar when stderr is a TTY and `--quiet`
    wasn't passed. Non-TTY (pipe, file) gets None so log capture stays
    clean."""
    if quiet or not sys.stderr.isatty():
        return None
    return throttle(_stderr_bar, min_interval_ms=100)


def _io_options(f: Callable[..., Any]) -> Callable[..., Any]:
    """Shared `-o/-f/--no-reconcile/--quiet` options for every parse-shaped
    command. Stacked bottom-up; Click binds by parameter name, not decorator
    order."""
    f = click.option(
        "-q",
        "--quiet",
        is_flag=True,
        help="Suppress the progress bar (stderr).",
    )(f)
    f = click.option("--no-reconcile", is_flag=True, help="Skip reconciliation invariant check.")(f)
    f = click.option(
        "-f",
        "--format",
        "fmt",
        type=click.Choice(["csv", "json"]),
        default="csv",
        show_default=True,
    )(f)
    f = click.option("-o", "--output", required=True, type=click.STRING)(f)
    return f


@click.group()
@click.version_option(__version__, prog_name="bankstract")
def main() -> None:
    """Convert Nigerian bank PDF statements into CSV or JSON."""


@main.command("list")
def list_parsers_cmd() -> None:
    """Show registered bank parsers + the input formats each supports."""
    for name in sorted(all_parsers()):
        parser = get(name)
        fmts = ", ".join(parser.supported_formats)
        click.echo(f"{name} ({fmts})")


@main.command("auto")
@click.argument("pdf", type=click.STRING)
@_io_options
def auto(pdf: str, output: str, fmt: _OutputFormat, no_reconcile: bool, quiet: bool) -> None:
    """Detect bank automatically and parse."""
    source = _read_source(pdf)
    try:
        name = detect(source)
    except ParseError as exc:
        raise click.ClickException(str(exc)) from exc
    if name is None:
        raise click.ClickException(f"no registered parser detected {pdf}")
    _info(f"detected: {name}", stdout_used=(output == "-"))
    _run(name, source, output, fmt, no_reconcile, quiet)


def _bank_command(bank: str) -> click.Command:
    @main.command(bank)
    @click.argument("pdf", type=click.STRING)
    @_io_options
    def cmd(pdf: str, output: str, fmt: _OutputFormat, no_reconcile: bool, quiet: bool) -> None:
        _run(bank, _read_source(pdf), output, fmt, no_reconcile, quiet)

    return cmd


def _check_supported(bank: str, source: Source) -> None:
    parser = get(bank)
    try:
        src_fmt = sniff_format(source)
    except ValueError as exc:
        # Unknown format hits the user as a clean CLI error rather than a
        # traceback. Parsers may still recover when given a Path with no
        # extension if their detect() works on content, so we only fail
        # loud here, not lower in parser.parse().
        raise click.ClickException(str(exc)) from exc
    if src_fmt not in parser.supported_formats:
        raise click.ClickException(
            f"{bank} parser does not support {src_fmt!r} input "
            f"(supported: {', '.join(parser.supported_formats)})"
        )


def _run(
    bank: str,
    source: Source,
    output: str,
    fmt: _OutputFormat,
    no_reconcile: bool,
    quiet: bool,
) -> None:
    stdout_used = output == "-"
    _check_supported(bank, source)
    try:
        data = parse_to(
            source,
            format=fmt,
            bank=bank,
            reconcile=not no_reconcile,
            progress_callback=_progress_callback(quiet=quiet),
        )
    except ParseError as exc:
        raise click.ClickException(
            f"parse error ({getattr(exc, 'format_version', 'unknown')}): {exc}"
        ) from exc
    except ReconciliationError as exc:
        raise click.ClickException(f"reconciliation failed: {exc}") from exc

    _write_bytes(data, output)
    _info(f"wrote {len(data)} bytes -> {output}", stdout_used=stdout_used)


@main.group()
def redact() -> None:
    """Strip PII from raw statement PDFs into committable fixtures."""


@redact.command("list")
def redact_list() -> None:
    for name in sorted(all_redactors()):
        click.echo(name)


def _redactor_command(bank: str) -> click.Command:
    @redact.command(bank)
    @click.argument("src", type=click.STRING)
    @click.argument("dst", type=click.STRING)
    @click.option("--audit/--no-audit", default=True, help="Print per-page audit to stderr.")
    @click.option("-q", "--quiet", is_flag=True, help="Suppress the progress bar (stderr).")
    def cmd(src: str, dst: str, audit: bool, quiet: bool) -> None:
        # Thin wrapper over bankstract.redact — single source of truth for
        # the dispatch logic lives in _api. CLI just handles I/O framing.
        from . import redact as _lib_redact

        source = _read_source(src)
        try:
            result = _lib_redact(
                source, bank=bank, progress_callback=_progress_callback(quiet=quiet)
            )
        except ParseError as exc:
            raise click.ClickException(str(exc)) from exc

        _write_bytes(result.data, dst)
        stdout_used = dst == "-"
        _info(
            f"{result.bank}: {result.report.redactions} redactions across "
            f"{result.report.pages} pages -> {dst}",
            stdout_used=stdout_used,
        )
        if audit:
            for page_no, entries in result.report.audit:
                if not entries:
                    continue
                click.echo(f"\n[page {page_no}]", err=True)
                for e in entries:
                    click.echo(f"  {e}", err=True)

    return cmd


for _bank in sorted(all_parsers()):
    _bank_command(_bank)

for _bank in sorted(all_redactors()):
    _redactor_command(_bank)
