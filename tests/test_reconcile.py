from datetime import datetime
from decimal import Decimal

import pytest

from bankstract.reconcile import reconcile, verify_totals
from bankstract.schema import ReconciliationError, Transaction


def _tx(
    balance: str | None,
    debit: str = "0",
    credit: str = "0",
) -> Transaction:
    return Transaction(
        date=datetime(2026, 1, 1),
        narration="t",
        debit=Decimal(debit),
        credit=Decimal(credit),
        balance=Decimal(balance) if balance is not None else None,
    )


def test_reconcile_passes_on_consistent_balances() -> None:
    rows = [
        _tx("1000.00"),
        _tx("800.00", debit="200.00"),
        _tx("1300.00", credit="500.00"),
    ]
    reconcile(rows)


def test_reconcile_raises_on_drop() -> None:
    rows = [
        _tx("1000.00"),
        _tx("500.00", debit="100.00"),
    ]
    with pytest.raises(ReconciliationError) as info:
        reconcile(rows)
    assert info.value.row_index == 1


def test_reconcile_empty_is_noop() -> None:
    reconcile([])


def test_reconcile_skips_when_balance_missing() -> None:
    # Statements without a balance column (PalmPay) yield txs with balance=None;
    # row-wise reconcile() should silently skip — verify_totals handles it.
    rows = [_tx(None, credit="100.00"), _tx(None, debit="40.00")]
    reconcile(rows)


def test_verify_totals_passes_on_match() -> None:
    rows = [_tx(None, credit="100.00"), _tx(None, debit="40.00"), _tx(None, credit="25.00")]
    verify_totals(rows, total_credit=Decimal("125.00"), total_debit=Decimal("40.00"))


def test_verify_totals_raises_on_credit_mismatch() -> None:
    rows = [_tx(None, credit="100.00"), _tx(None, credit="25.00")]
    with pytest.raises(ReconciliationError, match="credits"):
        verify_totals(rows, total_credit=Decimal("200.00"), total_debit=Decimal("0"))


def test_verify_totals_raises_on_debit_mismatch() -> None:
    rows = [_tx(None, debit="100.00")]
    with pytest.raises(ReconciliationError, match="debits"):
        verify_totals(rows, total_credit=Decimal("0"), total_debit=Decimal("50.00"))


def test_verify_totals_respects_tolerance() -> None:
    rows = [_tx(None, credit="100.005")]
    verify_totals(rows, total_credit=Decimal("100.00"), total_debit=Decimal("0"))
