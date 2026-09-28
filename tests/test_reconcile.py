from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from bankstract.reconcile import reconcile, reconcile_result, verify_totals
from bankstract.schema import (
    ParseResult,
    ReconciledParseResult,
    ReconciliationError,
    ReconciliationReport,
    Transaction,
)

from ._fixtures import RECONCILIATION, fixture_params, parsed


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
    assert reconcile(rows) is False


def test_reconcile_raises_on_partial_balances() -> None:
    rows = [_tx("1000.00"), _tx(None, debit="200.00"), _tx("1300.00", credit="500.00")]
    with pytest.raises(ReconciliationError, match="balance missing") as info:
        reconcile(rows)
    assert info.value.row_index == 1


def test_reconcile_result_raises_on_partial_balances() -> None:
    # Totals alone would pass here. The partial column must still fail.
    rows = [_tx("1000.00"), _tx(None, debit="200.00")]
    with pytest.raises(ReconciliationError, match="balance missing"):
        reconcile_result(_result(rows, totals=("0", "200.00")))


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


def _result(
    rows: list[Transaction],
    *,
    totals: tuple[str, str] | None = None,
    row_wise_reconcilable: bool = True,
) -> ParseResult:
    return ParseResult(
        transactions=rows,
        total_credit=Decimal(totals[0]) if totals else None,
        total_debit=Decimal(totals[1]) if totals else None,
        format_version="synthetic",
        row_wise_reconcilable=row_wise_reconcilable,
    )


def test_reconcile_result_runs_both_checks() -> None:
    rows = [_tx("1000.00"), _tx("800.00", debit="200.00")]
    report = reconcile_result(_result(rows, totals=("0", "200.00"))).reconciliation
    assert report == ReconciliationReport(totals="passed", row_wise="passed")


def test_reconcile_result_row_wise_not_available_without_balances() -> None:
    rows = [_tx(None, credit="100.00"), _tx(None, debit="40.00")]
    report = reconcile_result(_result(rows, totals=("100.00", "40.00"))).reconciliation
    assert report == ReconciliationReport(totals="passed", row_wise="not_available")


def test_reconcile_result_row_wise_disabled_by_parser() -> None:
    # Balances present but broken: an opted-out parser must not run row-wise.
    rows = [_tx("1000.00"), _tx("1.00", debit="200.00")]
    report = reconcile_result(
        _result(rows, totals=("0", "200.00"), row_wise_reconcilable=False)
    ).reconciliation
    assert report == ReconciliationReport(totals="passed", row_wise="disabled")


def test_reconcile_result_totals_not_available_without_header() -> None:
    rows = [_tx("1000.00"), _tx("800.00", debit="200.00")]
    report = reconcile_result(_result(rows)).reconciliation
    assert report == ReconciliationReport(totals="not_available", row_wise="passed")


def test_reconcile_result_raises_without_evidence() -> None:
    rows = [_tx(None, credit="100.00")]
    with pytest.raises(ReconciliationError, match="no reconciliation evidence"):
        reconcile_result(_result(rows))


def test_reconcile_result_raises_on_row_break() -> None:
    rows = [_tx("1000.00"), _tx("500.00", debit="100.00")]
    with pytest.raises(ReconciliationError) as info:
        reconcile_result(_result(rows, totals=("0", "100.00")))
    assert info.value.row_index == 1


def test_reconcile_result_raises_on_totals_break() -> None:
    rows = [_tx(None, credit="100.00")]
    with pytest.raises(ReconciliationError, match="credits"):
        reconcile_result(_result(rows, totals=("999.00", "0")))


@pytest.mark.parametrize(("bank", "path"), fixture_params())
def test_reconcile_result_per_fixture(bank: str, path: Path) -> None:
    assert reconcile_result(parsed(bank, path)).reconciliation == RECONCILIATION[bank]


def test_reconcile_result_returns_reconciled_type() -> None:
    checked = reconcile_result(_result([_tx("1000.00"), _tx("800.00", debit="200.00")]))
    assert isinstance(checked, ReconciledParseResult)
    assert checked.report == ReconciliationReport(totals="not_available", row_wise="passed")


def test_reconciled_result_requires_report() -> None:
    with pytest.raises(ValueError, match="needs a reconciliation report"):
        ReconciledParseResult(transactions=[], format_version="synthetic")
