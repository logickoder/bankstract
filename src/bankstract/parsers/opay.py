"""
OPay statement parser.

8-column tabular layout with a running balance — reconciliation runs
row-wise (`reconcile.reconcile`). OPay statements DO carry header totals
("Total Debit" / "Total Credit") + opening/closing balance values, so
metadata is rich and totals reconcile too.

Columns (x0 ranges, observed at 612pt page width):

    | Trans. Time | Value Date | Description | Debit(₦) | Credit(₦) | Balance After(₦) | Channel | Transaction Reference |
    | 65..128     | 128..175   | 175..300    | 300..340 | 340..378  | 378..420         | 420..475 | 475..560              |

Notes:
- Date format is "DD Mon YYYY HH:MM:SS" (4 tokens stitched from the date
  column). Value date format is "DD Mon YYYY" (3 tokens).
- The description column carries narration that wraps across MULTIPLE
  rows — typically one row above the data row (counterparty / type) and
  one row below (account fragment / item). Distance-based attribution
  pins each non-tx desc row to the nearest tx row within the same page
  (rather than walk_rows-style append-to-pending, which would mis-attach
  the pre-row to the previous tx).
- A debit-only row has "--" in the credit column; vice versa.
- The reference column carries one long digit string per tx (sometimes
  echoed on the post-row); take the longest seen for the bucket.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from .._layout import Word, classify, group_by_baseline
from .._pdfplumber import PdfSource
from ..schema import ParseError, ParseResult, StatementMetadata, Transaction
from . import register
from ._common import extract_words_per_page, first_page_text
from .base import Parser

HEADER_MARKERS: tuple[str, ...] = (
    "Wallet Account",
    "Balance After",
    "Debit(₦)",
    "Credit(₦)",
)

FORMAT_VERSION = "opay-2026-01"

ROW_TOL = 4.0

# Column x0 ranges. OPay's print engine shifts everything by up to ~10pt
# between statements (compact vs full-history layouts both observed in the
# wild), so ranges are widened to cover both. Section 2 (Savings Account)
# uses a further-shifted layout but the parser truncates before reaching
# it; the redactor (which DOES touch section 2) uses a wider REF_ZONE that
# covers both.
COL_DATE = (60.0, 130.0)
COL_VALUE_DATE = (130.0, 180.0)
COL_DESC = (180.0, 290.0)
COL_DEBIT = (290.0, 325.0)
COL_CREDIT = (325.0, 365.0)
COL_BALANCE = (365.0, 410.0)
COL_CHANNEL = (410.0, 470.0)
COL_REF = (470.0, 565.0)

# Months OPay prints (English short form).
_MONTHS = {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"}

_DAY_TOK = re.compile(r"\d{2}")
_YEAR_TOK = re.compile(r"\d{4}")


def _parse_amount(token: str) -> Decimal:
    return Decimal(token.replace(",", "").lstrip("₦"))


def _col_words(row: list[Word], col: tuple[float, float]) -> list[Word]:
    lo, hi = col
    return [w for w in row if lo <= w.x0 < hi]


def _is_tx_row(row: list[Word]) -> bool:
    """A tx row has the 4-token date stamp in COL_DATE and an amount in
    COL_BALANCE. Chrome rows (column header, page-1 summary) miss one or
    both signatures."""
    date_words = _col_words(row, COL_DATE)
    if len(date_words) < 4:
        return False
    if not _DAY_TOK.fullmatch(date_words[0].text):
        return False
    if date_words[1].text not in _MONTHS:
        return False
    if not _YEAR_TOK.fullmatch(date_words[2].text):
        return False
    if classify(date_words[3].text) != "time":
        return False
    return any(classify(w.text) == "amount" for w in _col_words(row, COL_BALANCE))


def _parse_tx_datetime(date_words: list[Word]) -> datetime:
    parts = " ".join(w.text for w in date_words[:4])
    return datetime.strptime(parts, "%d %b %Y %H:%M:%S")


def _amount_from_col(row: list[Word], col: tuple[float, float]) -> Decimal:
    for w in _col_words(row, col):
        if classify(w.text) == "amount":
            return _parse_amount(w.text)
    return Decimal("0")


def _longest_ref(words: list[Word]) -> str | None:
    if not words:
        return None
    return max((w.text for w in words), key=len)


def _process_page(
    rows: list[list[Word]],
    *,
    skip_header_chrome: bool,
) -> tuple[list[Transaction], bool]:
    """Return (page_txs, hit_section_end). The statement is multi-section:
    a "Wallet Account" block (the actual current-account statement) is
    followed by a "Savings Account" block (OWealth sub-account, different
    layout). We only parse the first section — the second's column ranges
    drift left and it's effectively a separate statement."""
    if skip_header_chrome:
        # Column header row anchors the start of the tx body. Everything
        # above is page-1 chrome (Account Statement, Wallet Account
        # Period:, Opening/Closing Balance summary).
        anchor = next(
            (i for i, r in enumerate(rows) if any(w.text == "Trans." for w in r)),
            None,
        )
        if anchor is None:
            return ([], False)
        rows = rows[anchor + 1 :]

    # Trim at the section boundary if present on this page.
    hit_section_end = False
    section_end = next(
        (
            i
            for i, r in enumerate(rows)
            if any(w.text == "Savings" for w in r) and any(w.text == "Account" for w in r)
        ),
        None,
    )
    if section_end is not None:
        rows = rows[:section_end]
        hit_section_end = True

    marked = [(r, _is_tx_row(r)) for r in rows]
    tx_indices = [i for i, (_, t) in enumerate(marked) if t]
    if not tx_indices:
        return ([], hit_section_end)

    # Distance-based attribution: each non-tx row that has tokens in the
    # description column belongs to the closest tx row (top distance).
    bucket_desc: dict[int, list[Word]] = {ti: [] for ti in tx_indices}
    bucket_ref: dict[int, list[Word]] = {ti: [] for ti in tx_indices}

    for row, is_tx in marked:
        if is_tx:
            continue
        desc_words = _col_words(row, COL_DESC)
        ref_words = [w for w in _col_words(row, COL_REF) if classify(w.text) == "alnum"]
        if not desc_words and not ref_words:
            continue
        top = row[0].top
        closest = min(tx_indices, key=lambda ti: abs(marked[ti][0][0].top - top))
        bucket_desc[closest].extend(desc_words)
        bucket_ref[closest].extend(ref_words)

    out: list[Transaction] = []
    for ti in tx_indices:
        row = marked[ti][0]
        date_words = _col_words(row, COL_DATE)
        same_row_desc = _col_words(row, COL_DESC)
        same_row_ref = [w for w in _col_words(row, COL_REF) if classify(w.text) == "alnum"]

        desc_words = same_row_desc + bucket_desc[ti]
        ref_words = same_row_ref + bucket_ref[ti]

        narration = " ".join(w.text for w in desc_words).strip()
        balance_word = next(w for w in _col_words(row, COL_BALANCE) if classify(w.text) == "amount")

        out.append(
            Transaction(
                date=_parse_tx_datetime(date_words),
                narration=narration,
                debit=_amount_from_col(row, COL_DEBIT),
                credit=_amount_from_col(row, COL_CREDIT),
                balance=_parse_amount(balance_word.text),
                reference=_longest_ref(ref_words),
            )
        )
    return (out, hit_section_end)


# Address field is absent on short-period statements (no transactions →
# no address printed); make it optional so single-period and multi-year
# statements both extract holder + account number cleanly.
_HOLDER_RE = re.compile(
    r"Account Name\s+Account Number(?:\s+Address)?\s*\n([A-Z][A-Z .,'-]+?)\s+\d"
)
_ACCT_RE = re.compile(r"Account Name\s+Account Number(?:\s+Address)?\s*\n[^\n]*?(\d{8,})")
_PERIOD_RE = re.compile(
    r"Wallet Account Period:\s+(\d{2} [A-Z][a-z]{2} \d{4})\s*-\s*(\d{2} [A-Z][a-z]{2} \d{4})"
)
# The page-1 summary block prints labels and values on alternating lines:
#   Opening Balance | Total Debit  | Debit Count
#   ₦{opening}      | ₦{debit}     | {count}
#   Closing Balance | Total Credit | Credit Count
#   ₦{closing}      | ₦{credit}    | {count}
# Capture the full triple in one shot so positional order isn't ambiguous.
_DEBIT_BLOCK_RE = re.compile(
    r"Opening Balance\s+Total Debit\s+Debit Count\s*\n"
    r"₦([\d,]+\.\d{2})\s+₦([\d,]+\.\d{2})\s+(\d+)"
)
_CREDIT_BLOCK_RE = re.compile(
    r"Closing Balance\s+Total Credit\s+Credit Count\s*\n"
    r"₦([\d,]+\.\d{2})\s+₦([\d,]+\.\d{2})\s+(\d+)"
)


def _mask_account(raw: str) -> str | None:
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    if len(digits) <= 4:
        return "X" * len(digits)
    return "X" * (len(digits) - 4) + digits[-4:]


def _parse_period_date(token: str) -> datetime | None:
    try:
        return datetime.strptime(token, "%d %b %Y")
    except ValueError:
        return None


def _dec(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def _extract_metadata(text: str) -> StatementMetadata:
    holder = _HOLDER_RE.search(text)
    acct = _ACCT_RE.search(text)
    period = _PERIOD_RE.search(text)
    debit_block = _DEBIT_BLOCK_RE.search(text)
    credit_block = _CREDIT_BLOCK_RE.search(text)
    return StatementMetadata(
        bank="opay",
        account_holder=holder.group(1).strip() if holder else None,
        account_number_masked=_mask_account(acct.group(1)) if acct else None,
        statement_period_start=_parse_period_date(period.group(1)) if period else None,
        statement_period_end=_parse_period_date(period.group(2)) if period else None,
        opening_balance=_dec(debit_block.group(1)) if debit_block else None,
        closing_balance=_dec(credit_block.group(1)) if credit_block else None,
    )


def _extract_totals(text: str) -> tuple[Decimal | None, Decimal | None]:
    debit_block = _DEBIT_BLOCK_RE.search(text)
    credit_block = _CREDIT_BLOCK_RE.search(text)
    return (
        _dec(credit_block.group(2)) if credit_block else None,
        _dec(debit_block.group(2)) if debit_block else None,
    )


class OPayParser(Parser):
    bank = "opay"

    def detect(self, source: PdfSource) -> bool:
        text = first_page_text(source)
        return all(marker in text for marker in HEADER_MARKERS)

    def detect_confidence(self, source: PdfSource) -> float:
        text = first_page_text(source)
        return sum(1 for m in HEADER_MARKERS if m in text) / len(HEADER_MARKERS)

    def parse(self, source: PdfSource) -> ParseResult:
        words_per_page = extract_words_per_page(source)
        if not words_per_page:
            raise ParseError("empty PDF", format_version=FORMAT_VERSION)

        transactions: list[Transaction] = []
        for page_idx, page_words in enumerate(words_per_page):
            rows = group_by_baseline(page_words, ROW_TOL)
            page_txs, hit_section_end = _process_page(rows, skip_header_chrome=(page_idx == 0))
            transactions.extend(page_txs)
            if hit_section_end:
                break

        if not transactions:
            raise ParseError(
                "no transactions parsed — layout mismatch or empty statement",
                format_version=FORMAT_VERSION,
            )

        text = first_page_text(source)
        total_credit, total_debit = _extract_totals(text)
        return ParseResult(
            transactions=transactions,
            total_credit=total_credit,
            total_debit=total_debit,
            format_version=FORMAT_VERSION,
            metadata=_extract_metadata(text),
            # Wallet balance column doesn't reflect OWealth implicit
            # auto-save/withdrawal side-effects: a debit-to-external can land
            # with bal=0 prev → bal=0 curr because the matching OWealth
            # withdrawal happens atomically but is logged on a subsequent row.
            # Row-wise reconcile would false-fail on every such pair; we rely
            # on verify_totals against the header-printed Total Debit/Credit.
            row_wise_reconcilable=False,
        )


register(OPayParser())
