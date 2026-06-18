from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from bankstract.parsers import get
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
    parser = get("opay")
    assert parser.bank == "opay"


@pytest.mark.skipif(not SAMPLE.exists(), reason="no opay sample fixture")
def test_parses_redacted_fixture() -> None:
    parser = get("opay")
    result: ParseResult = parser.parse(SAMPLE)
    assert result.format_version == "opay-2026-01"
    assert len(result.transactions) > 0
    for tx in result.transactions:
        assert tx.debit > 0 or tx.credit > 0
        assert tx.balance is not None

    # OPay opts out of row-wise reconcile (wallet column hides OWealth
    # auto-save/withdrawal side effects), but totals must reconcile.
    assert result.row_wise_reconcilable is False
    assert result.total_credit is not None
    assert result.total_debit is not None
    verify_totals(
        result.transactions,
        total_credit=result.total_credit,
        total_debit=result.total_debit,
    )


@pytest.mark.parametrize("fixture", _FIXTURES)
def test_metadata_extracted(fixture: Path) -> None:
    parser = get("opay")
    result = parser.parse(fixture)
    md = result.metadata
    assert md is not None
    assert md.bank == "opay"
    assert md.account_holder is not None
    assert md.account_number_masked is not None and md.account_number_masked.startswith("X")
    assert md.statement_period_start is not None
    assert md.statement_period_end is not None
    assert md.statement_period_start <= md.statement_period_end
    assert md.opening_balance is not None
    assert md.closing_balance is not None
    if fixture == SAMPLE:
        assert md.account_holder == "TEST USER"
        assert md.account_number_masked == "XXXXXX0000"
        assert md.statement_period_start == datetime(2023, 5, 1)
        assert md.statement_period_end == datetime(2023, 5, 12)
        assert md.opening_balance == Decimal("204.31")
        assert md.closing_balance == Decimal("7581.31")
        # 18 transactions in the short-period wallet sample (16 dr + 2 cr).
        assert len(result.transactions) == 18
