from pathlib import Path

import click

from . import __version__
from .parsers import all_parsers, get
from .parsers.base import Parser
from .reconcile import reconcile, verify_totals
from .redactors import all_redactors
from .redactors import get as get_redactor
from .schema import ParseError, ParseResult, ReconciliationError
from .writers.csv import write_csv


@click.group()
@click.version_option(__version__, prog_name="bankstract")
def main() -> None:
    """Convert Nigerian bank PDF statements into CSV."""


@main.command("list")
def list_parsers() -> None:
    """Show registered bank parsers."""
    for name in sorted(all_parsers()):
        click.echo(name)


@main.command("auto")
@click.argument("pdf", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--no-reconcile", is_flag=True, help="Skip reconciliation invariant check.")
def auto(pdf: Path, output: Path, no_reconcile: bool) -> None:
    """Detect bank automatically and parse."""
    for name, parser in all_parsers().items():
        if parser.detect(pdf):
            click.echo(f"detected: {name}")
            _run(parser, pdf, output, no_reconcile)
            return
    raise click.ClickException(f"no registered parser detected {pdf}")


def _bank_command(bank: str) -> click.Command:
    @main.command(bank)
    @click.argument("pdf", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("-o", "--output", required=True, type=click.Path(dir_okay=False, path_type=Path))
    @click.option("--no-reconcile", is_flag=True, help="Skip reconciliation invariant check.")
    def cmd(pdf: Path, output: Path, no_reconcile: bool) -> None:
        _run(get(bank), pdf, output, no_reconcile)

    return cmd


def _run(parser: Parser, pdf: Path, output: Path, no_reconcile: bool) -> None:
    try:
        result: ParseResult = parser.parse(pdf)
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
            reconcile(result.transactions)
        except ReconciliationError as exc:
            raise click.ClickException(f"reconciliation failed: {exc}") from exc

    count = write_csv(result.transactions, output)
    click.echo(f"wrote {count} transactions -> {output}")


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
