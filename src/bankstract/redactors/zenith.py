"""
Zenith Bank statement redactor.

Zenith narration carries counterparty names inline (e.g. NIP/CIP transfers
include the originator/beneficiary name as part of the description). A
vocabulary-based keep-list is too leak-prone, so — like FBN — the safe
move is to blank the entire description column wholesale.

Parser tests still work: tx count, debit/credit, and the row-wise reconcile
invariant compare against the balance column, none of which depend on
narration content.

Strategy:
1. Label-anchored header redaction:
   - "ACCOUNT NAME:" → "TEST USER"
   - "ACCOUNT No.:" → "0000000000"
   - the 3 address lines starting at "28A" / following "ACCOUNT NAME:"
2. Body: every word inside the description x0 range (105..260) is blanked.
3. The account number (10 digits) is replaced wherever it appears.
"""

from __future__ import annotations

import re
from typing import Any

from .._pymupdf import rect as _rect
from ..parsers.zenith import COL_DESC
from . import register
from ._shared import RegexSweep, apply_regex_sweeps, page_rows, redact_word
from .base import Redactor

HEADER_LABELS: dict[str, str] = {
    "ACCOUNT NAME:": "TEST USER",
    "ACCOUNT No.:": "0000000000",
}

PHONE_RE = re.compile(r"\b0\d{2}\s?\d{4}\s?\d{4}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

ROW_TOL = 4.0

SWEEPS: tuple[RegexSweep, ...] = (
    (PHONE_RE, "0800000000", "phone"),
    (EMAIL_RE, "test@example.com", "email"),
)


class ZenithRedactor(Redactor):
    bank = "zenith"
    format_version = "zenith-2026-01"

    def redact_header(
        self,
        page: Any,
        pending_text: list[tuple[Any, str]],
        audit: list[str],
    ) -> None:
        page_rect = page.rect

        for label, replacement in HEADER_LABELS.items():
            for hit in page.search_for(label):
                # Right-bound at the half-page mark so the "Account Statement"
                # right-column label isn't blanked by the same row sweep.
                target = _rect(hit.x1 + 2, hit.y0, 240.0, hit.y1 + 2)
                if "No." in label:
                    target = _rect(hit.x1 + 2, hit.y0, page_rect.x1 - 20, hit.y1 + 2)
                page.add_redact_annot(target, fill=(1, 1, 1))
                pending_text.append((target, replacement))
                audit.append(f"header[{label}] -> {replacement!r}")

        # Address block sits in the left column directly under ACCOUNT NAME
        # (three visual rows). Blank the left half of those three rows.
        for hit in page.search_for("ACCOUNT NAME:"):
            for i in range(1, 4):
                addr_line = _rect(
                    40.0,
                    hit.y1 + (i - 1) * 10,
                    240.0,
                    hit.y1 + i * 10 + 2,
                )
                page.add_redact_annot(addr_line, fill=(1, 1, 1))
                if i == 1:
                    pending_text.append((addr_line, "Test Address"))
                audit.append(f"header[Address-line-{i}] -> (blank)")

    def redact_body(
        self,
        page: Any,
        pending_text: list[tuple[Any, str]],
        audit: list[str],
    ) -> None:
        rows = page_rows(page, ROW_TOL)

        # Locate the column-header row ("DATE DESCRIPTION DEBIT ..."). Bank
        # boilerplate above it ("ZENITH BANK PLC", branch address) sits in
        # the desc x range but isn't PII — and the "ZENITH BANK" string is
        # what `ZenithParser.detect()` keys on, so keep it intact. Pages
        # without a repeated header (page 2+) get blanket coverage.
        body_y_min: float = 0.0
        for row in rows:
            texts = {w.text for w in row}
            if "DATE" in texts and "DESCRIPTION" in texts:
                body_y_min = max(w.bottom for w in row)
                break

        for row in rows:
            covered: set[int] = set()
            apply_regex_sweeps(page, row, SWEEPS, pending_text, audit, covered)

            row_top = row[0].top
            for idx, w in enumerate(row):
                if idx in covered:
                    continue
                in_desc = COL_DESC[0] <= w.x0 < COL_DESC[1]
                if in_desc and row_top >= body_y_min:
                    redact_word(page, w, "", pending_text)
                    covered.add(idx)
                    audit.append(f"desc: {w.text!r} -> (blank)")


register(ZenithRedactor())
