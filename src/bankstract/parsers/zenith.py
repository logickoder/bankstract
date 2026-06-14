"""
Zenith Bank statement parser.

6-column tabular layout with a running balance — reconciliation falls
through to `reconcile.reconcile`. The statement TOTALS row sums to the
closing balance net (credit - debit equals the final balance), so the
credit column rolls in the opening balance and is NOT a clean period
sum — we rely on the row-wise balance check and don't populate
ParseResult totals.

Columns (x0 ranges, observed at 612pt page width):

    | Trans Date | Description | Debit | Credit | Value Date | Balance |
    | 45..105    | 105..260    | 260..335 | 335..410 | 410..470 | 470..560 |

Notes:
- Date format is DD/MM/YYYY; no time component (padded with 00:00:00).
- The first row "Opening Balance 0.00 0.00 <bal>" has no date and is
  matched as chrome.
- Narrations wrap onto continuation rows (counterparty name on the next
  line, or text like "TBILLS 2025040339854/ 20270422").
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .._layout import Word, classify
from ..schema import ParseError, ParseResult, Transaction
from . import register
from ._columnar import (
    ColumnSpec,
    has_date_and_balance,
    walk_rows,
)
from ._common import extract_words_per_page, first_page_text
from .base import Parser

HEADER_MARKERS: tuple[str, ...] = (
    "ZENITH BANK",
    "zenithbank.com",
)

FORMAT_VERSION = "zenith-2026-01"

ROW_TOL = 4.0

COL_DATE = (45.0, 105.0)
COL_DESC = (105.0, 260.0)
COL_DEBIT = (260.0, 335.0)
COL_CREDIT = (335.0, 410.0)
COL_VALUE_DATE = (410.0, 470.0)
COL_BALANCE = (470.0, 565.0)

COLUMNS: ColumnSpec = {
    "date": COL_DATE,
    "desc": COL_DESC,
    "debit": COL_DEBIT,
    "credit": COL_CREDIT,
    "value_date": COL_VALUE_DATE,
    "balance": COL_BALANCE,
}


def _parse_amount(token: str) -> Decimal:
    return Decimal(token.replace(",", ""))


_is_tx_row = has_date_and_balance("date", "balance")


def _is_chrome_row(row: list[Word]) -> bool:
    """Non-transaction structural rows: column header, opening balance,
    totals footer, marketing footer, page-number footer. Matched
    structurally rather than by single-word vocab because narrations like
    `CAPITALIZED INTEREST CREDIT` legitimately contain words such as
    `CREDIT`/`DEBIT`/`BALANCE` and must not be misclassified."""
    texts = [w.text for w in row]
    if not texts:
        return False
    text_set = set(texts)
    if "TOTALS" in text_set or "ALERTZ" in text_set:
        return True
    if "DATE" in text_set and "DESCRIPTION" in text_set:
        return True
    if "Opening" in text_set and "Balance" in text_set:
        return True
    if "TOTAL" in text_set and "(CLEARED" in text_set:
        return True
    if texts[0] == "Page":
        return True
    return False


def _amount_in(cols: dict[str, list[Word]], key: str) -> Decimal:
    for w in cols.get(key, []):
        if classify(w.text) == "amount":
            amt = _parse_amount(w.text)
            if amt != 0:
                return amt
            break
    return Decimal("0")


def _build_transaction(
    cols: dict[str, list[Word]],
    continuation_tokens: list[str],
) -> Transaction:
    date_word = next(w for w in cols["date"] if classify(w.text) == "date")
    balance_word = next(w for w in cols["balance"] if classify(w.text) == "amount")
    desc_tokens = [w.text for w in cols.get("desc", [])]
    return Transaction(
        date=datetime.strptime(date_word.text, "%d/%m/%Y"),
        narration=" ".join(desc_tokens + continuation_tokens).strip(),
        debit=_amount_in(cols, "debit"),
        credit=_amount_in(cols, "credit"),
        balance=_parse_amount(balance_word.text),
    )


class ZenithParser(Parser):
    bank = "zenith"

    def detect(self, pdf_path: Path) -> bool:
        text = first_page_text(pdf_path)
        return any(marker in text for marker in HEADER_MARKERS)

    def parse(self, pdf_path: Path) -> ParseResult:
        words_per_page = extract_words_per_page(pdf_path)
        if not words_per_page:
            raise ParseError("empty PDF", format_version=FORMAT_VERSION)

        transactions = walk_rows(
            words_per_page,
            spec=COLUMNS,
            is_chrome=_is_chrome_row,
            is_tx=_is_tx_row,
            build_tx=_build_transaction,
            continuation_col="desc",
            row_tol=ROW_TOL,
        )

        if not transactions:
            raise ParseError(
                "no transactions parsed — layout mismatch or empty statement",
                format_version=FORMAT_VERSION,
            )

        return ParseResult(transactions=transactions, format_version=FORMAT_VERSION)


register(ZenithParser())
