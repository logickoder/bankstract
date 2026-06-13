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

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .._layout import (
    NAIRA_TOK,
    Word,
    classify,
    from_pdfplumber_words,
    group_by_baseline,
)
from .._pdfplumber import open_doc
from ..schema import ParseError, ParseResult, Transaction
from . import register
from .base import Parser

HEADER_MARKERS: tuple[str, ...] = ("PalmPay", "Palmpay", "PALMPAY")

FORMAT_VERSION = "palmpay-2026-01"

ROW_TOL = 4.0


def _parse_amount(token: str) -> Decimal:
    return Decimal(token.replace(",", "").lstrip("₦"))


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
            total_in = _parse_amount(amt)
        elif "Total Money Out" in joined:
            total_out = _parse_amount(amt)
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

    date_str = row[date_idx].text
    amount_token = row[amt_idx].text

    narration_start = date_idx + 1
    while narration_start < amt_idx and classes[narration_start] in ("time", "ampm"):
        narration_start += 1
    narration_tokens = [w.text for w in row[narration_start:amt_idx]]

    txid = next(
        (row[i].text for i in range(amt_idx + 1, len(row)) if classes[i] == "alnum"),
        None,
    )
    return date_str, narration_tokens, amount_token, txid


def _continuation_tokens(row: list[Word]) -> list[str]:
    classes = [classify(w.text) for w in row]
    return [row[i].text for i, c in enumerate(classes) if c == "text" and len(row[i].text) > 1]


def _build_transaction(
    date_str: str,
    narration_tokens: list[str],
    amount_token: str,
    txid: str | None,
    continuation_tokens: list[str],
) -> Transaction:
    parsed_dt = datetime.strptime(date_str, "%m/%d/%Y")
    amount = _parse_amount(amount_token)
    debit = -amount if amount < 0 else Decimal("0")
    credit = amount if amount > 0 else Decimal("0")
    narration = " ".join(narration_tokens + continuation_tokens).strip()
    return Transaction(
        date=parsed_dt.date(),
        narration=narration,
        debit=debit,
        credit=credit,
        balance=None,
        reference=txid,
    )


class PalmPayParser(Parser):
    bank = "palmpay"

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
        )


register(PalmPayParser())
