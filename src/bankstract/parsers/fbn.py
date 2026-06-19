"""
First Bank of Nigeria (FBN) statement parser.

7-column tabular layout with a running balance — reconciliation runs both
row-wise (`reconcile.reconcile`) and totals-based (`verify_totals`)
because the header carries Total Credit / Total Debit.

Columns (x0 ranges, observed at 612pt page width):

    | Trans Date | Ref. # | Transaction Details | Value Date | DR | CR | Balance |
    | 50..100    | 100..155 | 155..310          | 310..365   | 365..420 | 420..480 | 480..560 |

Narration sometimes wraps onto the next visual row (~6pt below); rows
without a date in the date column are treated as continuation rows and
their detail-column tokens append to the pending transaction.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from .._layout import Word, classify, group_by_baseline
from .._source import Source
from ..schema import ParseError, ParseResult, StatementMetadata, Transaction
from . import register
from ._columnar import (
    ColumnSpec,
    amount_in,
    has_date_and_balance,
    walk_rows,
)
from ._common import extract_words_per_page, first_page_text
from ._money import mask_account_number, parse_amount
from .base import Parser

# Structural column header — unique to FBN's statement layout. Substring
# checks like "FBN" used to false-positive on other banks' narrations
# (e.g. Zenith's `CR|FBN|ZIB|...` rows). Requiring BOTH halves of the
# Withdrawal/Deposit column header collapses the false-positive surface
# to zero we've observed.
HEADER_MARKERS: tuple[str, ...] = (
    "Withdrawal(DR)",
    "Deposit(CR)",
)

FORMAT_VERSION = "fbn-2026-01"

ROW_TOL = 4.0

COL_DATE = (45.0, 100.0)
COL_REF = (100.0, 155.0)
COL_DETAIL = (155.0, 310.0)
COL_VALUE_DATE = (310.0, 365.0)
COL_WITHDRAWAL = (365.0, 420.0)
COL_DEPOSIT = (420.0, 480.0)
COL_BALANCE = (480.0, 565.0)

COLUMNS: ColumnSpec = {
    "date": COL_DATE,
    "ref": COL_REF,
    "detail": COL_DETAIL,
    "value_date": COL_VALUE_DATE,
    "withdrawal": COL_WITHDRAWAL,
    "deposit": COL_DEPOSIT,
    "balance": COL_BALANCE,
}

# Tokens that mark page chrome (page header repeated each page, footer
# disclaimer, opening/closing balance summary). When seen, we stop
# appending to the pending transaction's narration.
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


_is_tx_row = has_date_and_balance("date", "balance")


def _is_chrome_row(row: list[Word]) -> bool:
    return any(w.text in CHROME_MARKERS for w in row)


def _build_transaction(
    cols: dict[str, list[Word]],
    continuation_tokens: list[str],
) -> Transaction:
    date_word = next(w for w in cols["date"] if classify(w.text) == "date")
    balance_word = next(w for w in cols["balance"] if classify(w.text) == "amount")
    detail_tokens = [w.text for w in cols.get("detail", [])]
    # FBN ships date-only ("dd-Mon-yyyy") with no time component; store at
    # 00:00:00 so the schema stays datetime across all banks.
    return Transaction(
        date=datetime.strptime(date_word.text, "%d-%b-%Y"),
        narration=" ".join(detail_tokens + continuation_tokens).strip(),
        debit=amount_in(cols, "withdrawal"),
        credit=amount_in(cols, "deposit"),
        balance=parse_amount(balance_word.text),
        reference=next((w.text for w in cols.get("ref", [])), None),
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
            total_credit = parse_amount(amt)
        elif "Total Debit" in line:
            total_debit = parse_amount(amt)
    return (total_credit, total_debit)


_HOLDER_RE = re.compile(r"Account Name\s*:\s*(.+?)\s*$", re.MULTILINE)
_ACCT_RE = re.compile(r"Account No\s*:\s*(\d+)", re.MULTILINE)
_PERIOD_RE = re.compile(r"period:\s+(\d{2}-[A-Z][a-z]{2}-\d{4})\s+To\s+(\d{2}-[A-Z][a-z]{2}-\d{4})")


def _parse_period_date(token: str) -> datetime | None:
    try:
        return datetime.strptime(token, "%d-%b-%Y")
    except ValueError:
        return None


def _extract_metadata(text: str, transactions: list[Transaction]) -> StatementMetadata:
    holder = _HOLDER_RE.search(text)
    acct = _ACCT_RE.search(text)
    period = _PERIOD_RE.search(text)
    opening: Decimal | None = None
    closing: Decimal | None = None
    if transactions:
        first = transactions[0]
        if first.balance is not None:
            opening = first.balance + first.debit - first.credit
        last = transactions[-1]
        closing = last.balance
    return StatementMetadata(
        bank="fbn",
        account_holder=holder.group(1).strip() if holder else None,
        account_number_masked=mask_account_number(acct.group(1)) if acct else None,
        # The "Please find below your bank statement for the period: ..."
        # line is stripped by the FBN redactor (it embeds the account holder's
        # address); raw _local statements still carry it. Test expects None
        # for sample.pdf, real datetimes for _local/statement.pdf.
        statement_period_start=_parse_period_date(period.group(1)) if period else None,
        statement_period_end=_parse_period_date(period.group(2)) if period else None,
        opening_balance=opening,
        closing_balance=closing,
    )


class FBNParser(Parser):
    bank = "fbn"

    def detect(self, source: Source) -> bool:
        text = first_page_text(source)
        return all(marker in text for marker in HEADER_MARKERS)

    def detect_confidence(self, source: Source) -> float:
        text = first_page_text(source)
        return sum(1 for m in HEADER_MARKERS if m in text) / len(HEADER_MARKERS)

    def parse(self, source: Source) -> ParseResult:
        words_per_page = extract_words_per_page(source)
        if not words_per_page:
            raise ParseError("empty PDF", format_version=FORMAT_VERSION)

        total_credit, total_debit = _extract_totals(words_per_page)

        transactions = walk_rows(
            words_per_page,
            spec=COLUMNS,
            is_chrome=_is_chrome_row,
            is_tx=_is_tx_row,
            build_tx=_build_transaction,
            continuation_col="detail",
            row_tol=ROW_TOL,
        )

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
            metadata=_extract_metadata(first_page_text(source), transactions),
        )


register(FBNParser())
