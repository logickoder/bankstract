"""
OPay statement redactor.

OPay narration is the largest leak surface: every Transfer line carries the
counterparty's full name + bank + partial account number. A vocabulary
keep-list would leak somewhere, so — like FBN and Zenith — the safe move is
to blank the entire description column wholesale.

Strategy:
1. Header: the row directly beneath "Account Name Account Number Address"
   carries the holder name, account number, and street address as a single
   row. Blank it, restore obviously-fake placeholders.
2. Body: every word inside the description (175..300) or reference
   (475..560) x0 range is blanked. The channel column ("Mobile") is
   structural and stays. Dates, amounts, and the balance column survive so
   parser tests can still assert totals + counts.
"""

from __future__ import annotations

import re
from typing import Any

from .._layout import classify
from .._pymupdf import rect as _rect
from . import register
from ._shared import RegexSweep, apply_regex_sweeps, page_rows, redact_word, shape_preserve
from .base import Redactor

# Column ranges are deliberately WIDER than the parser's COL_* — the parser
# wants precise column attribution, the redactor wants to catch every word
# that could be narration regardless of layout drift between statements.
# Section 1 (Wallet Account) and section 2 (Savings Account) use different
# left-shifts; the unions cover both. The channel token ("Mobile") at
# x0~395-475 has classify()=="text" so it never trips the alnum check.
DESC_ZONE: tuple[float, float] = (170.0, 305.0)
REF_ZONE: tuple[float, float] = (450.0, 565.0)

PHONE_RE = re.compile(r"\b0\d{2}\s?\d{4}\s?\d{4}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

ROW_TOL = 4.0

SWEEPS: tuple[RegexSweep, ...] = (
    (PHONE_RE, "0800000000", "phone"),
    (EMAIL_RE, "test@example.com", "email"),
)


class OPayRedactor(Redactor):
    bank = "opay"

    def redact_header(
        self,
        page: Any,
        pending_text: list[tuple[Any, str]],
        audit: list[str],
    ) -> None:
        # Account holder + account number + address sit on the single line
        # directly below the "Account Name Account Number Address" label
        # row. Blank that whole strip and restore fixed placeholders for
        # each column.
        for hit in page.search_for("Account Name"):
            row_top = hit.y1 + 2
            row_bottom = hit.y1 + 14
            holder_rect = _rect(60.0, row_top, 220.0, row_bottom)
            acct_rect = _rect(220.0, row_top, 380.0, row_bottom)
            addr_rect = _rect(380.0, row_top, page.rect.x1 - 20, row_bottom)
            for r, text, label in (
                (holder_rect, "TEST USER", "Account Name"),
                (acct_rect, "0000000000", "Account Number"),
                (addr_rect, "Test Address", "Address"),
            ):
                page.add_redact_annot(r, fill=(1, 1, 1))
                pending_text.append((r, text))
                audit.append(f"header[{label}] -> {text!r}")

        # "Generated on DD Mon YYYY HH:MM:SS" reveals print time; replace
        # with a fixed placeholder so two runs produce identical fixtures.
        for hit in page.search_for("Generated on"):
            line = _rect(hit.x1 + 2, hit.y0, page.rect.x1 - 20, hit.y1 + 2)
            page.add_redact_annot(line, fill=(1, 1, 1))
            pending_text.append((line, "01 Jan 2026 00:00:00"))
            audit.append("header[Generated on] -> placeholder")

    def redact_body(
        self,
        page: Any,
        pending_text: list[tuple[Any, str]],
        audit: list[str],
    ) -> None:
        rows = page_rows(page, ROW_TOL)

        # Page 1 alone has chrome above the body (Wallet Account header,
        # holder block, period line, balance summary). Anchor on the first
        # "Trans." column header on page 1 to skip past it. On later pages
        # we default body_y_min=0 so the entire page is body; the section-2
        # break on page 35 repeats the column header MID-PAGE, but its
        # surrounding chrome words (Savings/Account/Period:/₦-summary)
        # mostly fall outside the desc + ref x-zones — and anchoring on
        # that mid-page header would skip every section-1 tx above it,
        # leaving their refs un-redacted.
        body_y_min: float = 0.0
        if page.number == 0:
            for row in rows:
                if any(w.text == "Trans." for w in row):
                    body_y_min = max(w.bottom for w in row)
                    break

        for row in rows:
            covered: set[int] = set()
            apply_regex_sweeps(page, row, SWEEPS, pending_text, audit, covered)

            row_top = row[0].top
            if row_top < body_y_min:
                continue
            for idx, w in enumerate(row):
                if idx in covered:
                    continue
                kind = classify(w.text)
                in_desc = DESC_ZONE[0] <= w.x0 < DESC_ZONE[1]
                in_ref = REF_ZONE[0] <= w.x0 < REF_ZONE[1]
                # Preserve "--" debit/credit placeholders even though they
                # sit in the desc x-range on section 2 (which uses a
                # left-shifted layout). Their classify() result is "text"
                # but the literal token has structural meaning the parser
                # needs to round-trip.
                if in_desc and kind in ("text", "alnum") and w.text != "--":
                    redact_word(page, w, "", pending_text)
                    covered.add(idx)
                    audit.append(f"desc: {w.text!r} -> (blank)")
                elif in_ref and kind == "alnum":
                    # Shape-preserve so the parser's alnum classifier still
                    # recognises it after redaction (FBN pattern).
                    shape = shape_preserve(w.text)
                    redact_word(page, w, shape, pending_text)
                    covered.add(idx)
                    audit.append(f"ref: {w.text!r} -> {shape!r}")


register(OPayRedactor())
