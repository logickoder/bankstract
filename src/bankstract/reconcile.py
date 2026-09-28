"""Reconciliation checks. `reconcile_result` is the entry point: it picks
which checks apply and raises when none can run. `reconcile()` and
`verify_totals()` are its building blocks. `reconcile()` alone returns False
on a statement without balances, so a caller that ignores the return value
verifies nothing."""

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from ._progress import ProgressCallback, emit, progress_scope
from .schema import (
    CheckStatus,
    ParseResult,
    ReconciledParseResult,
    ReconciliationError,
    ReconciliationReport,
    Transaction,
)

TOLERANCE = Decimal("0.01")


def reconcile(transactions: Iterable[Transaction]) -> bool:
    """Row-wise invariant: prev.balance - debit + credit == curr.balance.

    Returns False without checking when no row has a balance (the statement
    has no balance column), else True once every row checked clean."""
    txs = list(transactions)
    missing = [i for i, t in enumerate(txs) if t.balance is None]
    if not txs or len(missing) == len(txs):
        return False
    # A balance column that's blank on some rows is a parser slip, not a
    # layout without balances. Skipping here would hide it behind totals.
    if missing:
        raise ReconciliationError(
            f"row {missing[0]}: balance missing. {len(missing)} of {len(txs)} rows "
            "have no balance while the rest do. Report the statement layout.",
            row_index=missing[0],
        )

    prev: Transaction | None = None
    for i, tx in enumerate(txs):
        if prev is None:
            prev = tx
            continue
        assert prev.balance is not None and tx.balance is not None  # guarded above
        expected = prev.balance - tx.debit + tx.credit
        diff = (expected - tx.balance).copy_abs()
        if diff > TOLERANCE:
            raise ReconciliationError(
                f"row {i}: expected balance {expected}, got {tx.balance} "
                f"(prev {prev.balance}, debit {tx.debit}, credit {tx.credit})",
                row_index=i,
            )
        prev = tx
    return True


def verify_totals(
    transactions: Iterable[Transaction],
    *,
    total_credit: Decimal,
    total_debit: Decimal,
    tolerance: Decimal = TOLERANCE,
) -> None:
    """Sum-based invariant for statements without a per-row balance column."""
    txs = list(transactions)
    sum_credit = sum((t.credit for t in txs), Decimal("0"))
    sum_debit = sum((t.debit for t in txs), Decimal("0"))

    if (sum_credit - total_credit).copy_abs() > tolerance:
        raise ReconciliationError(
            f"credits sum {sum_credit} does not match stated total {total_credit}"
        )
    if (sum_debit - total_debit).copy_abs() > tolerance:
        raise ReconciliationError(
            f"debits sum {sum_debit} does not match stated total {total_debit}"
        )


def reconcile_result(
    result: ParseResult,
    *,
    progress_callback: ProgressCallback | None = None,
) -> ReconciledParseResult:
    """Run every reconciliation check `result` carries evidence for and return
    a copy with `.reconciliation` set. The input is left untouched.

    Totals run when the parser read header totals. Row-wise runs when every
    row has a balance and the parser didn't opt out. FBN-style statements get
    both: totals catch dropped rows, row-wise catches per-row arithmetic that
    happens to sum out. A failed check raises `ReconciliationError`. So does a
    result with no evidence for either check, since that would otherwise pass
    unverified.

    `progress_callback` receives `reconcile` then `done`. Pass it after a
    separate `parse()` call, whose scope has closed."""
    with progress_scope(progress_callback):
        totals: CheckStatus = "not_available"
        if result.total_credit is not None and result.total_debit is not None:
            verify_totals(
                result.transactions,
                total_credit=result.total_credit,
                total_debit=result.total_debit,
            )
            totals = "passed"

        row_wise: CheckStatus
        if not result.row_wise_reconcilable:
            row_wise = "disabled"
        elif reconcile(result.transactions):
            row_wise = "passed"
        else:
            row_wise = "not_available"

        if totals != "passed" and row_wise != "passed":
            raise ReconciliationError(
                "no reconciliation evidence. Statement has neither header totals "
                "nor a checkable balance column. Report the statement layout."
            )
        emit("reconcile", 1, 1)
        report = ReconciliationReport(totals=totals, row_wise=row_wise)
        values: dict[str, Any] = {**vars(result), "reconciliation": report}
        return ReconciledParseResult(**values)
