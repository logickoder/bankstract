"""
PalmPay statement parser.

Uses pdfplumber word extraction with Y-baseline row grouping (shared
primitives in `bankstract._layout`). PalmPay statements do NOT carry a
running-balance column; the parser instead reads the header's
`Total Money In` / `Total Money Out` values into ParseResult.total_credit /
total_debit so reconciliation falls back to a sum-based check
(`bankstract.reconcile.verify_totals`).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from .._layout import (
    NAIRA_TOK,
    Word,
    classify,
    group_by_baseline,
)
from .._source import Source
from ..schema import ParseError, ParseResult, StatementMetadata, Transaction
from . import register
from ._common import extract_words_per_page, first_page_text
from ._money import mask_account_number, parse_amount
from .base import Parser

# Structural markers, not brand strings — the brand name doesn't always
# survive fixture redaction, and substring "PalmPay" was previously a
# false-positive surface. Both `Total Money In/Out` lines are unique to the
# PalmPay statement layout we've observed.
HEADER_MARKERS: tuple[str, ...] = (
    "Total Money In",
    "Total Money Out",
    "Money In (NGN)",
    "Money Out (NGN)",
)

FORMAT_VERSION = "palmpay-2026-01"

ROW_TOL = 4.0


def _extract_totals(
    words_per_page: list[list[Word]],
) -> tuple[Decimal | None, Decimal | None]:
    if not words_per_page:
        return (None, None)
    rows = group_by_baseline(words_per_page[0], ROW_TOL)

    total_in: Decimal | None = None
    total_out: Decimal | None = None
    for row in rows:
        joined = " ".join(w.text for w in row)
        amt = next((w.text for w in row if NAIRA_TOK.fullmatch(w.text)), None)
        if amt is None:
            continue
        if "Total Money In" in joined:
            total_in = parse_amount(amt)
        elif "Total Money Out" in joined:
            total_out = parse_amount(amt)
    return (total_in, total_out)


def _row_kind(classes: list[str]) -> str:
    has_date = "date" in classes
    has_amount = "amount" in classes
    if has_date and has_amount:
        return "tx"
    if has_date or has_amount:
        return "partial"
    return "continuation"


def _parse_row(row: list[Word]) -> tuple[str, list[str], str, str | None] | None:
    classes = [classify(w.text) for w in row]
    try:
        date_idx = classes.index("date")
    except ValueError:
        return None
    try:
        amt_idx = next(i for i, c in enumerate(classes) if c == "amount" and i > date_idx)
    except StopIteration:
        return None

    # Stitch date + time + AM/PM tokens into one datetime string so the full
    # PalmPay timestamp survives into Transaction.date.
    dt_parts = [row[date_idx].text]
    narration_start = date_idx + 1
    while narration_start < amt_idx and classes[narration_start] in ("time", "ampm"):
        dt_parts.append(row[narration_start].text)
        narration_start += 1
    datetime_str = " ".join(dt_parts)
    amount_token = row[amt_idx].text
    narration_tokens = [w.text for w in row[narration_start:amt_idx]]

    txid = next(
        (row[i].text for i in range(amt_idx + 1, len(row)) if classes[i] == "alnum"),
        None,
    )
    return datetime_str, narration_tokens, amount_token, txid


def _continuation_tokens(row: list[Word]) -> list[str]:
    classes = [classify(w.text) for w in row]
    return [row[i].text for i, c in enumerate(classes) if c == "text" and len(row[i].text) > 1]


def _build_transaction(
    datetime_str: str,
    narration_tokens: list[str],
    amount_token: str,
    txid: str | None,
    continuation_tokens: list[str],
) -> Transaction:
    # PalmPay row carries full timestamp ("MM/DD/YYYY HH:MM:SS AM/PM").
    # Falls back to date-only when the row lacks time tokens.
    try:
        parsed_dt = datetime.strptime(datetime_str, "%m/%d/%Y %I:%M:%S %p")
    except ValueError:
        parsed_dt = datetime.strptime(datetime_str.split()[0], "%m/%d/%Y")
    amount = parse_amount(amount_token)
    debit = -amount if amount < 0 else Decimal("0")
    credit = amount if amount > 0 else Decimal("0")
    narration = " ".join(narration_tokens + continuation_tokens).strip()
    return Transaction(
        date=parsed_dt,
        narration=narration,
        debit=debit,
        credit=credit,
        balance=None,
        reference=txid,
    )


_NAME_RE = re.compile(r"^Name\s*(.+?)\s*$", re.MULTILINE)
_ACCT_RE = re.compile(r"Account Number\s+([\d\s]+?)(?:\s*$|\s{2,})", re.MULTILINE)
_PERIOD_RE = re.compile(r"Statement Period\s+(\d{2}/\d{2}/\d{4})\s*[-–]\s*(\d{2}/\d{2}/\d{4})")


def _parse_period_date(token: str) -> datetime | None:
    try:
        return datetime.strptime(token, "%m/%d/%Y")
    except ValueError:
        return None


def _extract_metadata(text: str) -> StatementMetadata:
    name_match = _NAME_RE.search(text)
    acct_match = _ACCT_RE.search(text)
    period_match = _PERIOD_RE.search(text)
    return StatementMetadata(
        bank="palmpay",
        account_holder=name_match.group(1).strip() if name_match else None,
        account_number_masked=mask_account_number(acct_match.group(1)) if acct_match else None,
        statement_period_start=_parse_period_date(period_match.group(1)) if period_match else None,
        statement_period_end=_parse_period_date(period_match.group(2)) if period_match else None,
        opening_balance=None,
        closing_balance=None,
    )


class PalmPayParser(Parser):
    bank = "palmpay"

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

        total_in, total_out = _extract_totals(words_per_page)
        # PalmPay has no per-row balance column, so reconciliation depends
        # entirely on these header totals. If we can't read them, fail loud
        # rather than silently downgrade to a no-op check.
        if total_in is None or total_out is None:
            raise ParseError(
                "header totals (Total Money In/Out) not found — layout drift?",
                format_version=FORMAT_VERSION,
            )

        transactions: list[Transaction] = []
        pending: tuple[str, list[str], str, str | None] | None = None
        pending_tail: list[str] = []

        def flush() -> None:
            nonlocal pending, pending_tail
            if pending is None:
                return
            date_str, narr, amt, txid = pending
            transactions.append(_build_transaction(date_str, narr, amt, txid, pending_tail))
            pending = None
            pending_tail = []

        for page_words in words_per_page:
            for row in group_by_baseline(page_words, ROW_TOL):
                classes = [classify(w.text) for w in row]
                kind = _row_kind(classes)
                if kind == "tx":
                    flush()
                    parsed = _parse_row(row)
                    if parsed is not None:
                        pending = parsed
                elif kind == "continuation" and pending is not None:
                    pending_tail.extend(_continuation_tokens(row))
        flush()

        if not transactions:
            raise ParseError(
                "no transactions parsed — layout mismatch or empty statement",
                format_version=FORMAT_VERSION,
            )

        return ParseResult(
            transactions=transactions,
            total_credit=total_in,
            total_debit=total_out,
            format_version=FORMAT_VERSION,
            metadata=_extract_metadata(first_page_text(source)),
        )


register(PalmPayParser())
