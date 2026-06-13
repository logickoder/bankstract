from pathlib import Path

import pytest

from bankstract._layout import Word, classify
from bankstract.parsers import get
from bankstract.parsers.fbn import (
    CHROME_MARKERS,
    _column_of,
    _is_chrome_row,
    _is_tx_row,
    _row_columns,
)
from bankstract.reconcile import reconcile, verify_totals
from bankstract.schema import ParseResult

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_parser_registered() -> None:
    parser = get("fbn")
    assert parser.bank == "fbn"


def test_classify_fbn_date_format() -> None:
    assert classify("18-Mar-2026") == "date"
    assert classify("13-Jun-2026") == "date"
    # PalmPay-style still recognised
    assert classify("06/13/2026") == "date"


def _w(x0: float, text: str) -> Word:
    return Word(text=text, x0=x0, top=100, x1=x0 + 30, bottom=110)


def test_column_of_buckets() -> None:
    assert _column_of(_w(54, "18-Mar-2026")) == "date"
    assert _column_of(_w(106, "S44787493")) == "ref"
    assert _column_of(_w(158, "FIP:LIT:PLP/")) == "detail"
    assert _column_of(_w(314, "18-Mar-2026")) == "value_date"
    assert _column_of(_w(387, "200,000.00")) == "withdrawal"
    assert _column_of(_w(464, "0.00")) == "deposit"
    assert _column_of(_w(510, "332,878.27")) == "balance"
    assert _column_of(_w(0, "")) is None


def test_is_tx_row() -> None:
    row = [
        _w(54, "18-Mar-2026"),
        _w(106, "S44787493"),
        _w(158, "FIP:LIT:PLP/"),
        _w(314, "18-Mar-2026"),
        _w(387, "200,000.00"),
        _w(464, "0.00"),
        _w(510, "332,878.27"),
    ]
    assert _is_tx_row(_row_columns(row))

    no_date = [_w(158, "FUNDS"), _w(180, "RefXYZ")]
    assert not _is_tx_row(_row_columns(no_date))

    no_balance = [_w(54, "18-Mar-2026"), _w(158, "Stamp")]
    assert not _is_tx_row(_row_columns(no_balance))


def test_chrome_markers_terminate_continuation() -> None:
    # Sanity: every marker is a single token (no spaces) so plain word match works.
    for m in CHROME_MARKERS:
        assert " " not in m
    assert _is_chrome_row([_w(50, "Please")])
    assert _is_chrome_row([_w(50, "Closing"), _w(80, "Balance")])
    assert not _is_chrome_row([_w(158, "FIP:LIT:PLP/"), _w(220, "FOO")])


@pytest.mark.skipif(
    not any(FIXTURE_DIR.glob("*.pdf")),
    reason="no fbn fixture PDF — drop a redacted sample in tests/fixtures/fbn/",
)
def test_parses_redacted_fixture() -> None:
    parser = get("fbn")
    pdf = next(FIXTURE_DIR.glob("*.pdf"))
    result: ParseResult = parser.parse(pdf)
    assert result.format_version == "fbn-2026-01"
    assert len(result.transactions) > 0
    for tx in result.transactions:
        assert tx.debit > 0 or tx.credit > 0
        assert tx.balance is not None

    # Row-wise reconcile MUST pass (FBN has a running balance column).
    reconcile(result.transactions)

    # Totals are also extracted from the header; assert they match the sum.
    assert result.total_credit is not None
    assert result.total_debit is not None
    verify_totals(
        result.transactions,
        total_credit=result.total_credit,
        total_debit=result.total_debit,
    )
