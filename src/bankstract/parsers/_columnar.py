"""
Column-bucket table walker, shared by parsers whose statement layout fits
a fixed set of x0-bounded columns (FBN, Zenith). The walker handles row
grouping, chrome/tx/continuation classification, and the pending-tx flush
state machine; per-bank modules supply the column map and predicates.

PalmPay's layout is token-stream-shaped (no fixed columns; date and txid
top-coordinates drift within a row) and is parsed separately.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from .._layout import Word, classify, group_by_baseline
from .._progress import emit
from ..schema import Transaction
from ._money import parse_amount

ColumnSpec = dict[str, tuple[float, float]]

ChromePredicate = Callable[[list[Word]], bool]
TxPredicate = Callable[[dict[str, list[Word]]], bool]
TxBuilder = Callable[[dict[str, list[Word]], list[str]], Transaction]


def column_of(word: Word, spec: ColumnSpec) -> str | None:
    x = word.x0
    for name, (lo, hi) in spec.items():
        if lo <= x < hi:
            return name
    return None


def row_columns(row: list[Word], spec: ColumnSpec) -> dict[str, list[Word]]:
    out: dict[str, list[Word]] = {}
    for w in row:
        col = column_of(w, spec)
        if col is None:
            continue
        out.setdefault(col, []).append(w)
    return out


def amount_in(cols: dict[str, list[Word]], key: str) -> Decimal:
    """First non-zero amount in `cols[key]`, or Decimal(0) if none.

    Banks that put debit/credit/withdrawal/deposit on a single column and
    expect a zero-or-one-amount cell per row (FBN, Zenith) read it this way.
    """
    for w in cols.get(key, []):
        if classify(w.text) == "amount":
            amt = parse_amount(w.text)
            if amt != 0:
                return amt
            break
    return Decimal("0")


def has_date_and_balance(date_col: str, balance_col: str) -> TxPredicate:
    """Return a tx-row predicate: True iff `cols` carries a date in
    `date_col` and an amount in `balance_col` — the minimum signature of a
    running-balance bank statement row."""

    def _check(cols: dict[str, list[Word]]) -> bool:
        if date_col not in cols or balance_col not in cols:
            return False
        if not any(classify(w.text) == "date" for w in cols[date_col]):
            return False
        if not any(classify(w.text) == "amount" for w in cols[balance_col]):
            return False
        return True

    return _check


def walk_rows(
    words_per_page: list[list[Word]],
    *,
    spec: ColumnSpec,
    is_chrome: ChromePredicate,
    is_tx: TxPredicate,
    build_tx: TxBuilder,
    continuation_col: str,
    row_tol: float,
) -> list[Transaction]:
    """Iterate the document row-by-row and emit Transactions.

    State machine: chrome rows flush the pending tx; tx rows flush then
    take their place; non-chrome non-tx rows that carry tokens in the
    `continuation_col` get appended to the pending tx's narration tail.
    The final pending tx is flushed at EOF."""
    transactions: list[Transaction] = []
    pending_cols: dict[str, list[Word]] | None = None
    pending_tail: list[str] = []

    def flush() -> None:
        nonlocal pending_cols, pending_tail
        if pending_cols is None:
            return
        transactions.append(build_tx(pending_cols, pending_tail))
        pending_cols = None
        pending_tail = []

    total = len(words_per_page)
    for i, page_words in enumerate(words_per_page, 1):
        for row in group_by_baseline(page_words, row_tol):
            if is_chrome(row):
                flush()
                continue
            cols = row_columns(row, spec)
            if is_tx(cols):
                flush()
                pending_cols = cols
            elif pending_cols is not None and continuation_col in cols:
                pending_tail.extend(w.text for w in cols[continuation_col])
        emit("walk_page", i, total)
    flush()
    return transactions
