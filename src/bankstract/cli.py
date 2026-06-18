import sys
from io import BytesIO
from pathlib import Path
from typing import Literal

import click

from . import __version__
from ._source import Source
from ._xlsx import sniff_format
from .parsers import all_parsers, get
from .parsers.base import Parser
from .reconcile import reconcile, verify_totals
from .redactors import all_redactors
from .redactors import get as get_redactor
from .schema import ParseError, ParseResult, ReconciliationError
from .writers.csv import write_csv
from .writers.json import write_json

Format = Literal["csv", "json"]


def _read_source(pdf_arg: str) -> Source:
    """`-` reads the entire stdin into BytesIO (pdfplumber needs seek);
    anything else is treated as a filesystem path."""
    if pdf_arg == "-":
        return BytesIO(sys.stdin.buffer.read())
    p = Path(pdf_arg)
    if not p.exists() or not p.is_file():
        raise click.ClickException(f"file not found: {pdf_arg}")
    return p


def _info(msg: str, *, stdout_used: bool) -> None:
    click.echo(msg, err=stdout_used)


def _write_result(result: ParseResult, output: str, fmt: Format) -> int:
    target = sys.stdout if output == "-" else Path(output)
    if fmt == "json":
        return write_json(result, target)
    return write_csv(result.transactions, target)


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
@click.option("-o", "--output", required=True, type=click.STRING)
@click.option(
    "-f",
    "--format",
    "fmt",
    type=click.Choice(["csv", "json"]),
    default="csv",
    show_default=True,
)
@click.option("--no-reconcile", is_flag=True, help="Skip reconciliation invariant check.")
def auto(pdf: str, output: str, fmt: Format, no_reconcile: bool) -> None:
    """Detect bank automatically and parse."""
    source = _read_source(pdf)
    stdout_used = output == "-"
    candidates = [(name, p, p.detect_confidence(source)) for name, p in all_parsers().items()]
    candidates.sort(key=lambda t: t[2], reverse=True)
    if not candidates or candidates[0][2] <= 0:
        raise click.ClickException(f"no registered parser detected {pdf}")
    name, parser, _ = candidates[0]
    _info(f"detected: {name}", stdout_used=stdout_used)
    _run(parser, source, output, fmt, no_reconcile)


def _bank_command(bank: str) -> click.Command:
    @main.command(bank)
    @click.argument("pdf", type=click.STRING)
    @click.option("-o", "--output", required=True, type=click.STRING)
    @click.option(
        "-f",
        "--format",
        "fmt",
        type=click.Choice(["csv", "json"]),
        default="csv",
        show_default=True,
    )
    @click.option("--no-reconcile", is_flag=True, help="Skip reconciliation invariant check.")
    def cmd(pdf: str, output: str, fmt: Format, no_reconcile: bool) -> None:
        source = _read_source(pdf)
        _run(get(bank), source, output, fmt, no_reconcile)

    return cmd


def _check_supported(parser: Parser, source: Source) -> None:
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
            f"{parser.bank} parser does not support {src_fmt!r} input "
            f"(supported: {', '.join(parser.supported_formats)})"
        )


def _run(parser: Parser, source: Source, output: str, fmt: Format, no_reconcile: bool) -> None:
    stdout_used = output == "-"
    _check_supported(parser, source)
    try:
        result: ParseResult = parser.parse(source)
    except ParseError as exc:
        raise click.ClickException(
            f"parse error ({getattr(exc, 'format_version', 'unknown')}): {exc}"
        ) from exc

    if not no_reconcile:
        try:
            # Run every check the parser supplied evidence for. reconcile()
            # is row-wise (needs balance column); verify_totals() is sum-based
            # (needs header totals). Banks like FBN ship both and benefit from
            # running both — totals catch dropped rows, row-wise catches
            # per-row arithmetic errors that happen to sum out.
            if result.total_credit is not None and result.total_debit is not None:
                verify_totals(
                    result.transactions,
                    total_credit=result.total_credit,
                    total_debit=result.total_debit,
                )
            if result.row_wise_reconcilable:
                reconcile(result.transactions)
        except ReconciliationError as exc:
            raise click.ClickException(f"reconciliation failed: {exc}") from exc

    count = _write_result(result, output, fmt)
    _info(f"wrote {count} transactions -> {output}", stdout_used=stdout_used)


@main.group()
def redact() -> None:
    """Strip PII from raw statement PDFs into committable fixtures."""


@redact.command("list")
def redact_list() -> None:
    for name in sorted(all_redactors()):
        click.echo(name)


def _redactor_command(bank: str) -> click.Command:
    @redact.command(bank)
    @click.argument("src", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.argument("dst", type=click.Path(dir_okay=False, path_type=Path))
    @click.option("--audit/--no-audit", default=True, help="Print per-page audit to stderr.")
    def cmd(src: Path, dst: Path, audit: bool) -> None:
        redactor = get_redactor(bank)
        report = redactor.redact(src, dst)
        click.echo(
            f"{report.bank}: {report.redactions} redactions across {report.pages} pages -> {dst}"
        )
        if audit:
            for page_no, entries in report.audit:
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
