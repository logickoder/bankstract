from pathlib import Path

import pytest

from bankstract._layout import Word, classify
from bankstract.parsers import get
from bankstract.parsers._columnar import column_of, row_columns
from bankstract.parsers.zenith import COLUMNS, _is_chrome_row, _is_tx_row
from bankstract.reconcile import reconcile
from bankstract.schema import ParseResult

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_parser_registered() -> None:
    parser = get("zenith")
    assert parser.bank == "zenith"


def test_classify_zenith_date_format() -> None:
    assert classify("31/10/2024") == "date"
    assert classify("04/06/2026") == "date"


def _w(x0: float, text: str) -> Word:
    return Word(text=text, x0=x0, top=100, x1=x0 + 30, bottom=110)


def test_column_of_buckets() -> None:
    assert column_of(_w(52, "31/10/2024"), COLUMNS) == "date"
    assert column_of(_w(111, "CAPITALIZED"), COLUMNS) == "desc"
    assert column_of(_w(321, "0.00"), COLUMNS) == "debit"
    assert column_of(_w(382, "4,072.79"), COLUMNS) == "credit"
    assert column_of(_w(413, "01/11/2024"), COLUMNS) == "value_date"
    assert column_of(_w(508, "592,271.39"), COLUMNS) == "balance"
    assert column_of(_w(0, ""), COLUMNS) is None


def test_is_tx_row() -> None:
    row = [
        _w(52, "31/10/2024"),
        _w(111, "CAPITALIZED"),
        _w(158, "INTEREST"),
        _w(195, "CREDIT"),
        _w(321, "0.00"),
        _w(382, "4,072.79"),
        _w(413, "01/11/2024"),
        _w(508, "592,271.39"),
    ]
    assert _is_tx_row(row_columns(row, COLUMNS))

    no_date = [_w(111, "ORAZULIKE/TBILLS")]
    assert not _is_tx_row(row_columns(no_date, COLUMNS))

    no_balance = [_w(52, "31/10/2024"), _w(111, "DESC")]
    assert not _is_tx_row(row_columns(no_balance, COLUMNS))


def test_chrome_row_matches_structural_patterns_not_narration_credit() -> None:
    # Narration row containing "CREDIT" must NOT be chrome — that was the
    # bug that dropped every CAPITALIZED INTEREST CREDIT tx.
    tx_like = [
        _w(52, "31/10/2024"),
        _w(111, "CAPITALIZED"),
        _w(158, "INTEREST"),
        _w(195, "CREDIT"),
        _w(321, "0.00"),
        _w(382, "4,072.79"),
        _w(508, "592,271.39"),
    ]
    assert not _is_chrome_row(tx_like)

    assert _is_chrome_row([_w(50, "DATE"), _w(110, "DESCRIPTION"), _w(260, "DEBIT")])
    assert _is_chrome_row([_w(110, "Opening"), _w(150, "Balance")])
    assert _is_chrome_row([_w(230, "TOTALS"), _w(290, "-8,281,764.21")])
    assert _is_chrome_row(
        [_w(147, "TOTAL"), _w(170, "(CLEARED"), _w(210, "+"), _w(215, "UNCLEARED)")]
    )
    assert _is_chrome_row([_w(270, "Page"), _w(300, "1")])
    assert _is_chrome_row([_w(258, "ALERTZ"), _w(287, "VERIFICATION")])


@pytest.mark.skipif(
    not any(FIXTURE_DIR.glob("*.pdf")),
    reason="no zenith fixture PDF — drop a redacted sample in tests/zenith/fixtures/",
)
def test_parses_redacted_fixture() -> None:
    parser = get("zenith")
    pdf = next(FIXTURE_DIR.glob("*.pdf"))
    result: ParseResult = parser.parse(pdf)
    assert result.format_version == "zenith-2026-01"
    assert len(result.transactions) > 0
    for tx in result.transactions:
        assert tx.debit > 0 or tx.credit > 0
        assert tx.balance is not None

    # Zenith ships a running balance; row-wise reconcile is the load-bearing
    # invariant (the statement TOTALS row mixes opening balance into the
    # credit column so it isn't a clean period sum — see parser docstring).
    reconcile(result.transactions)
