"""
First Bank of Nigeria (FBN) statement parser.

FBN statements use a 7-column tabular layout with a running balance per row,
so reconciliation falls through to the row-wise check in `reconcile.reconcile`
(no totals fallback needed).

Columns (x0 ranges, observed at 612pt page width):

    | Trans Date | Ref. # | Transaction Details | Value Date | DR | CR | Balance |
    | 50..100    | 100..155 | 155..310          | 310..365   | 365..420 | 420..480 | 480..560 |

Narration sometimes wraps onto the next visual row (~6pt below). The parser
treats any row that lacks a date in the date column as a continuation row and
appends its detail-column tokens to the previous transaction's narration.

`Opening Balance` and `Closing Balance` rows have a balance but no date — they
fall into the "partial" bucket and are skipped by the tx loop.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .._layout import (
    Word,
    classify,
    from_pdfplumber_words,
    group_by_baseline,
)
from .._pdfplumber import open_doc
from ..schema import ParseError, ParseResult, Transaction
from . import register
from .base import Parser

HEADER_MARKERS: tuple[str, ...] = (
    "First Bank",
    "FirstBank",
    "FBN",
    "firstbanknigeria",
)

FORMAT_VERSION = "fbn-2026-01"

ROW_TOL = 4.0

# Column boundaries (x0). Tuned against the observed FBN layout. A small slack
# on each side absorbs minor font drift between PDF revisions.
COL_DATE = (45.0, 100.0)
COL_REF = (100.0, 155.0)
COL_DETAIL = (155.0, 310.0)
COL_VALUE_DATE = (310.0, 365.0)
COL_WITHDRAWAL = (365.0, 420.0)
COL_DEPOSIT = (420.0, 480.0)
COL_BALANCE = (480.0, 565.0)


def _column_of(word: Word) -> str | None:
    x = word.x0
    if COL_DATE[0] <= x < COL_DATE[1]:
        return "date"
    if COL_REF[0] <= x < COL_REF[1]:
        return "ref"
    if COL_DETAIL[0] <= x < COL_DETAIL[1]:
        return "detail"
    if COL_VALUE_DATE[0] <= x < COL_VALUE_DATE[1]:
        return "value_date"
    if COL_WITHDRAWAL[0] <= x < COL_WITHDRAWAL[1]:
        return "withdrawal"
    if COL_DEPOSIT[0] <= x < COL_DEPOSIT[1]:
        return "deposit"
    if COL_BALANCE[0] <= x < COL_BALANCE[1]:
        return "balance"
    return None


def _parse_amount(token: str) -> Decimal:
    return Decimal(token.replace(",", ""))


def _row_columns(row: list[Word]) -> dict[str, list[Word]]:
    out: dict[str, list[Word]] = {}
    for w in row:
        col = _column_of(w)
        if col is None:
            continue
        out.setdefault(col, []).append(w)
    return out


# Tokens that mark page chrome (page header repeated each page, footer
# disclaimer, opening/closing balance summary). When seen, we stop appending
# to the pending transaction's narration.
CHROME_MARKERS: frozenset[str] = frozenset(
    {
        "Please",
        "FirstContact",
        "firstbanknigeria.com",
        "Page",
        "Trans",
        "Closing",
        "Opening",
    }
)


def _is_chrome_row(row: list[Word]) -> bool:
    return any(w.text in CHROME_MARKERS for w in row)


def _is_tx_row(cols: dict[str, list[Word]]) -> bool:
    """Has both a Trans-Date token and a Balance token — the minimum signature
    of a transaction row in this format."""
    if "date" not in cols or "balance" not in cols:
        return False
    if not any(classify(w.text) == "date" for w in cols["date"]):
        return False
    if not any(classify(w.text) == "amount" for w in cols["balance"]):
        return False
    return True


def _build_transaction(
    cols: dict[str, list[Word]],
    continuation_tokens: list[str],
) -> Transaction:
    date_word = next(w for w in cols["date"] if classify(w.text) == "date")
    balance_word = next(w for w in cols["balance"] if classify(w.text) == "amount")

    detail_tokens = [w.text for w in cols.get("detail", [])]
    narration = " ".join(detail_tokens + continuation_tokens).strip()

    ref_token = next((w.text for w in cols.get("ref", [])), None)

    debit = Decimal("0")
    credit = Decimal("0")
    for w in cols.get("withdrawal", []):
        if classify(w.text) == "amount":
            amt = _parse_amount(w.text)
            if amt != 0:
                debit = amt
            break
    for w in cols.get("deposit", []):
        if classify(w.text) == "amount":
            amt = _parse_amount(w.text)
            if amt != 0:
                credit = amt
            break

    parsed_dt = datetime.strptime(date_word.text, "%d-%b-%Y")
    return Transaction(
        date=parsed_dt.date(),
        narration=narration,
        debit=debit,
        credit=credit,
        balance=_parse_amount(balance_word.text),
        reference=ref_token,
    )


def _extract_totals(
    words_per_page: list[list[Word]],
) -> tuple[Decimal | None, Decimal | None]:
    """Read Total Credit / Total Debit from the page-1 header."""
    if not words_per_page:
        return (None, None)
    rows = group_by_baseline(words_per_page[0], ROW_TOL)

    total_credit: Decimal | None = None
    total_debit: Decimal | None = None
    for row in rows:
        line = " ".join(w.text for w in row)
        amt = next((w.text for w in reversed(row) if classify(w.text) == "amount"), None)
        if amt is None:
            continue
        if "Total Credit" in line:
            total_credit = _parse_amount(amt)
        elif "Total Debit" in line:
            total_debit = _parse_amount(amt)
    return (total_credit, total_debit)


class FBNParser(Parser):
    bank = "fbn"

    def detect(self, pdf_path: Path) -> bool:
        try:
            with open_doc(pdf_path) as pdf:
                pages: list[Any] = pdf.pages
                if not pages:
                    return False
                first_page_text: str = pages[0].extract_text() or ""
        except Exception:
            return False
        return any(marker in first_page_text for marker in HEADER_MARKERS)

    def parse(self, pdf_path: Path) -> ParseResult:
        with open_doc(pdf_path) as pdf:
            words_per_page: list[list[Word]] = [
                from_pdfplumber_words(page.extract_words()) for page in pdf.pages
            ]

        if not words_per_page:
            raise ParseError("empty PDF", format_version=FORMAT_VERSION)

        total_credit, total_debit = _extract_totals(words_per_page)

        transactions: list[Transaction] = []
        pending_cols: dict[str, list[Word]] | None = None
        pending_tail: list[str] = []

        def flush() -> None:
            nonlocal pending_cols, pending_tail
            if pending_cols is None:
                return
            transactions.append(_build_transaction(pending_cols, pending_tail))
            pending_cols = None
            pending_tail = []

        for page_words in words_per_page:
            for row in group_by_baseline(page_words, ROW_TOL):
                if _is_chrome_row(row):
                    flush()
                    continue
                cols = _row_columns(row)
                if _is_tx_row(cols):
                    flush()
                    pending_cols = cols
                elif pending_cols is not None and "detail" in cols:
                    # Continuation row — append detail-column text to pending narration.
                    pending_tail.extend(w.text for w in cols["detail"])
        flush()

        if not transactions:
            raise ParseError(
                "no transactions parsed — layout mismatch or empty statement",
                format_version=FORMAT_VERSION,
            )

        return ParseResult(
            transactions=transactions,
            total_credit=total_credit,
            total_debit=total_debit,
            format_version=FORMAT_VERSION,
        )


register(FBNParser())
