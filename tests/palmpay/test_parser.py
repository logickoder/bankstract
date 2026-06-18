from datetime import datetime
from pathlib import Path

import pytest

from bankstract._layout import Word, classify
from bankstract.parsers import get
from bankstract.parsers.palmpay import (
    _continuation_tokens,
    _parse_row,
    _row_kind,
)
from bankstract.reconcile import verify_totals
from bankstract.schema import ParseResult

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURE_DIR / "sample.pdf"
LOCAL = FIXTURE_DIR / "_local" / "statement.pdf"

_FIXTURES = [
    pytest.param(SAMPLE, id="sample"),
    pytest.param(
        LOCAL,
        id="local",
        marks=pytest.mark.skipif(
            not LOCAL.exists(), reason="raw fixture absent (CI / fresh clone)"
        ),
    ),
]


def test_parser_registered() -> None:
    parser = get("palmpay")
    assert parser.bank == "palmpay"


def test_classify_buckets() -> None:
    assert classify("06/13/2026") == "date"
    assert classify("06:38:19") == "time"
    assert classify("AM") == "ampm"
    assert classify("+3.79") == "amount"
    assert classify("-1,250.50") == "amount"
    assert classify("u835z3qh9b90y") == "alnum"
    assert classify("at_35pc6b9301") == "alnum"
    assert classify("CashBox") == "text"


def _w(x0: float, text: str) -> Word:
    return Word(text=text, x0=x0, top=100, x1=x0 + 30, bottom=110)


def test_row_kind_classifies_correctly() -> None:
    tx_row = [
        _w(10, "06/13/2026"),
        _w(50, "06:38:19"),
        _w(90, "AM"),
        _w(120, "CashBox"),
        _w(170, "Interest"),
        _w(300, "+3.79"),
        _w(400, "u835z3qh9b90y"),
    ]
    classes = [classify(w.text) for w in tx_row]
    assert _row_kind(classes) == "tx"

    cont_row = [_w(120, "ACME"), _w(170, "CORP")]
    classes = [classify(w.text) for w in cont_row]
    assert _row_kind(classes) == "continuation"


def test_parse_row_extracts_components() -> None:
    row = [
        _w(10, "06/13/2026"),
        _w(50, "06:38:19"),
        _w(90, "AM"),
        _w(120, "CashBox"),
        _w(170, "Interest"),
        _w(300, "+3.79"),
        _w(400, "u835z3qh9b90y"),
    ]
    parsed = _parse_row(row)
    assert parsed is not None
    datetime_str, narration, amount, txid = parsed
    assert datetime_str == "06/13/2026 06:38:19 AM"
    assert narration == ["CashBox", "Interest"]
    assert amount == "+3.79"
    assert txid == "u835z3qh9b90y"


def test_parse_row_underscore_txid() -> None:
    row = [
        _w(10, "06/08/2026"),
        _w(50, "12:04:37"),
        _w(90, "AM"),
        _w(120, "CashBox"),
        _w(170, "Auto"),
        _w(220, "Save"),
        _w(300, "-2010.00"),
        _w(400, "at_35pc6b9301"),
    ]
    parsed = _parse_row(row)
    assert parsed is not None
    _, _, _, txid = parsed
    assert txid == "at_35pc6b9301"


def test_continuation_tokens_extracts_text_only() -> None:
    row = [_w(140, "ACME"), _w(190, "CORP"), _w(250, "20260611112237284501")]
    assert _continuation_tokens(row) == ["ACME", "CORP"]


@pytest.mark.skipif(not SAMPLE.exists(), reason="no palmpay sample fixture")
def test_parses_redacted_fixture() -> None:
    parser = get("palmpay")
    result: ParseResult = parser.parse(SAMPLE)
    assert result.format_version == "palmpay-2026-01"
    assert len(result.transactions) > 0
    assert result.total_credit is not None
    assert result.total_debit is not None
    for tx in result.transactions:
        assert tx.debit > 0 or tx.credit > 0

    # Load-bearing invariant (CLAUDE.md directive 2): parsed sums must equal
    # the totals printed in the statement header.
    verify_totals(
        result.transactions,
        total_credit=result.total_credit,
        total_debit=result.total_debit,
    )


@pytest.mark.parametrize("fixture", _FIXTURES)
def test_metadata_extracted(fixture: Path) -> None:
    parser = get("palmpay")
    result = parser.parse(fixture)
    md = result.metadata
    assert md is not None
    assert md.bank == "palmpay"
    assert md.account_holder is not None
    assert md.account_number_masked is not None and md.account_number_masked.startswith("X")
    assert md.statement_period_start is not None
    assert md.statement_period_end is not None
    assert md.statement_period_start <= md.statement_period_end
    # PalmPay statements omit a running-balance column → no opening/closing.
    assert md.opening_balance is None
    assert md.closing_balance is None
    if fixture == SAMPLE:
        assert md.account_holder == "TEST USER"
        assert md.account_number_masked == "XXXXXX0000"
        assert md.statement_period_start == datetime(2026, 6, 5)
        assert md.statement_period_end == datetime(2026, 6, 13)
