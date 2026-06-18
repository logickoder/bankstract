"""
Money + identifier helpers shared by every parser.

Each bank statement prints amounts and account numbers with different
ornamentation (₦ prefix vs none, "--" placeholder vs blank, comma vs
space group-separator). Centralising the coercion + masking here keeps
per-bank parsers focused on layout, not string scrubbing.
"""

from __future__ import annotations

from decimal import Decimal

# Tokens that mean "no value" in an amount column. OPay uses "--"; some
# banks emit blank cells. Caller decides whether absent means zero (debit/
# credit columns) or None (opening/closing balance).
_BLANK_AMOUNTS = frozenset({"", "--", "₦--", "N/A"})


def parse_amount(token: str | object | None) -> Decimal:
    """Coerce a statement amount string to Decimal.

    Strips currency prefix (₦, +), grouping commas, and surrounding
    whitespace. Returns `Decimal('0')` for blank/'--' placeholders so
    debit/credit columns flow naturally. Use `parse_amount_optional` when
    a missing value should propagate as `None` (e.g. metadata fields).
    """
    if token is None:
        return Decimal("0")
    text = str(token).strip()
    if text in _BLANK_AMOUNTS:
        return Decimal("0")
    return Decimal(text.replace(",", "").lstrip("₦").lstrip("+"))


def parse_amount_optional(token: str | object | None) -> Decimal | None:
    """Same as `parse_amount` but returns `None` on a missing value
    instead of zero — for metadata fields where absent ≠ zero."""
    if token is None:
        return None
    text = str(token).strip()
    if text in _BLANK_AMOUNTS:
        return None
    return Decimal(text.replace(",", "").lstrip("₦").lstrip("+"))


def mask_account_number(raw: str, *, keep_tail: int = 4) -> str | None:
    """Mask all but the last `keep_tail` digits of an account number.

    Strips non-digit characters from `raw` before masking. Returns None
    when no digits are present. Statements with shorter-than-`keep_tail`
    numbers are fully masked (safer than partial reveal of a short ID).
    """
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    if len(digits) <= keep_tail:
        return "X" * len(digits)
    return "X" * (len(digits) - keep_tail) + digits[-keep_tail:]
