from collections.abc import Iterable
from decimal import Decimal

from .schema import ReconciliationError, Transaction

TOLERANCE = Decimal("0.01")


def reconcile(transactions: Iterable[Transaction]) -> None:
    """Row-wise invariant: prev.balance - debit + credit == curr.balance.

    Skips silently if any transaction has balance=None (statement has no
    running-balance column — the caller MUST then run verify_totals against
    parser-supplied header totals, otherwise reconciliation is being skipped
    entirely, in violation of CLAUDE.md directive 2.
    """
    txs = list(transactions)
    if not txs or any(t.balance is None for t in txs):
        return

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
