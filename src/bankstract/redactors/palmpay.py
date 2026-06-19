"""
PalmPay statement redactor.

Phrase-based, NOT keyword-based. PalmPay narration vocabulary overlaps with
counterparty business names (e.g. `POS`, `TOP`, `CARD`), so a keyword allowlist
leaks PII fragments. This pass instead:

1. Label-anchors header fields (Name / Address) by bbox geometry.
2. For each visual row:
     a. Static regex sweep for phone / account-number / email.
     b. If the row has a date+amount, slice the narration column (tokens
        between AM/PM and amount). If that text exactly matches a known
        transaction-type phrase, keep it. If it begins with an anchor
        ("Send to" / "Received from"), keep the anchor and blank everything
        after. Otherwise blank the whole narration column.
     c. If the row has no date+amount, treat it as continuation or page
        chrome: blank text tokens unless they're in HEADER_CHROME.
"""

from __future__ import annotations

import re
from typing import Any

from .._layout import classify, from_pymupdf_words, group_by_baseline
from .._pymupdf import rect as _rect
from . import register
from ._shared import (
    EMAIL_RE,
    EMAIL_REPLACEMENT,
    PHONE_RE,
    PHONE_REPLACEMENT,
    redact_range,
    redact_word,
    shape_preserve,
)
from .base import Redactor

HEADER_LABELS: dict[str, str] = {
    "Name": "TEST USER",
    "Address": "Test Address",
}

ACCT_SPACED_RE = re.compile(r"\b\d{3}\s\d{3}\s\d{4}\b")

NARRATION_PHRASES: frozenset[str] = frozenset(
    s.lower()
    for s in {
        "CashBox Interest",
        "CashBox Auto Save",
        "Stamp Duty",
        "Card Payment-WEB",
        "Card Payment-POS",
        "Buy Data bundle",
        "Card Top up",
        "Card Top-up",
    }
)

ANCHOR_PHRASES: tuple[str, ...] = ("Send to", "Received from")

HEADER_CHROME: frozenset[str] = frozenset(
    {
        "TOTAL",
        "MONEY",
        "IN",
        "OUT",
        "STATEMENT",
        "PERIOD",
        "PRINT",
        "TIME",
        "TRANSACTION",
        "DETAIL",
        "DATE",
        "ID",
        "PAGE",
        "OF",
        "NGN",
        "NAME",
        "PHONE",
        "NUMBER",
        "ACCOUNT",
        "ADDRESS",
        "PALMPAY",
        "PALM",
        "PAY",
        "REDACTED",
        "PARTY",
        "TEST",
        "USER",
    }
)

ROW_TOL = 4.0


def _narration_span(classes: list[str]) -> tuple[int, int] | None:
    """Return [start, end) row indices of the narration column for a tx row."""
    try:
        date_idx = classes.index("date")
    except ValueError:
        return None
    try:
        amt_idx = next(i for i, c in enumerate(classes) if c == "amount" and i > date_idx)
    except StopIteration:
        return None
    start = date_idx + 1
    while start < amt_idx and classes[start] in ("time", "ampm"):
        start += 1
    return (start, amt_idx)


class PalmPayRedactor(Redactor):
    bank = "palmpay"

    def redact_header(
        self,
        page: Any,
        pending_text: list[tuple[Any, str]],
        audit: list[str],
    ) -> None:
        page_rect = page.rect
        for label, replacement in HEADER_LABELS.items():
            for hit in page.search_for(label):
                target = _rect(hit.x1 + 2, hit.y0, page_rect.x1 - 20, hit.y1 + 2)
                page.add_redact_annot(target, fill=(1, 1, 1))
                pending_text.append((target, replacement))
                audit.append(f"header[{label}] -> {replacement!r}")
                if label == "Address":
                    wrap = _rect(hit.x0, hit.y1, page_rect.x1 - 20, hit.y1 + 14)
                    page.add_redact_annot(wrap, fill=(1, 1, 1))
                    audit.append("header[Address-wrap] -> (blank)")

    def redact_body(
        self,
        page: Any,
        pending_text: list[tuple[Any, str]],
        audit: list[str],
    ) -> None:
        rows = group_by_baseline(from_pymupdf_words(page.get_text("words")), ROW_TOL)

        for row in rows:
            line_text = " ".join(w.text for w in row)
            covered: set[int] = set()

            for regex, replacement, label in (
                (PHONE_RE, PHONE_REPLACEMENT, "phone"),
                (ACCT_SPACED_RE, "000 000 0000", "acct-spaced"),
                (EMAIL_RE, EMAIL_REPLACEMENT, "email"),
            ):
                for m in regex.finditer(line_text):
                    redact_range(page, row, m.start(), m.end(), replacement, covered, pending_text)
                    audit.append(f"{label}: {m.group(0)!r} -> {replacement!r}")

            classes = [classify(w.text) for w in row]

            # Shape-preserving redaction of every alnum token (transaction IDs
            # and the long internal references on stamp-duty rows). Opaque
            # tokens combined with date+amount could correlate back to a real
            # transaction via the bank's support channel.
            for idx, w in enumerate(row):
                if idx in covered or classes[idx] != "alnum":
                    continue
                redact_word(page, w, shape_preserve(w.text), pending_text)
                covered.add(idx)
                audit.append(f"txid: {w.text!r} -> {shape_preserve(w.text)!r}")

            span = _narration_span(classes)

            if span is not None:
                start, end = span
                narration_text = " ".join(w.text for w in row[start:end]).strip()
                normalized = re.sub(r"\s+", " ", narration_text).lower()

                if normalized in NARRATION_PHRASES:
                    continue

                anchor = next((a for a in ANCHOR_PHRASES if normalized.startswith(a.lower())), None)
                if anchor:
                    skip = start + len(anchor.split())
                    for idx in range(skip, end):
                        if idx in covered:
                            continue
                        redact_word(page, row[idx], "", pending_text)
                        covered.add(idx)
                        audit.append(f"anchor-tail: {row[idx].text!r}")
                else:
                    for idx in range(start, end):
                        if idx in covered:
                            continue
                        redact_word(page, row[idx], "", pending_text)
                        covered.add(idx)
                        audit.append(f"unknown-narration: {row[idx].text!r}")
                continue

            # No date+amount → continuation row or page chrome.
            for idx, w in enumerate(row):
                if idx in covered or classes[idx] != "text" or len(w.text) <= 1:
                    continue
                stripped = re.sub(r"[-_.,;:'/&()\[\]{}\"]+", "", w.text).upper()
                if stripped in HEADER_CHROME:
                    continue
                redact_word(page, w, "", pending_text)
                covered.add(idx)
                audit.append(f"continuation: {w.text!r}")


register(PalmPayRedactor())
