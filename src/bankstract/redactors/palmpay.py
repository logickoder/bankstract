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
3. Replacement text is written via insert_text AFTER apply_redactions, so it
   becomes real PDF text content, not an [Image #N] stamp.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .._layout import (
    Word,
    classify,
    from_pymupdf_words,
    group_by_baseline,
)
from .._pymupdf import PDF_REDACT_IMAGE_NONE, open_doc
from .._pymupdf import rect as _rect
from . import register
from .base import Redactor, RedactReport

# Header fields without a regex-detectable pattern. Phone Number / Account
# Number values are caught by PHONE_RE / ACCT_SPACED_RE in the body pass.
HEADER_LABELS: dict[str, str] = {
    "Name": "TEST USER",
    "Address": "Test Address",
}

PHONE_RE = re.compile(r"\b0\d{2}\s?\d{4}\s?\d{4}\b")
ACCT_SPACED_RE = re.compile(r"\b\d{3}\s\d{3}\s\d{4}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

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


def _redact_word(
    page: Any,
    word: Word,
    replacement: str,
    pending_text: list[tuple[Any, str]],
) -> None:
    r = _rect(word.x0, word.top, word.x1, word.bottom)
    page.add_redact_annot(r, fill=(1, 1, 1))
    if replacement:
        pending_text.append((r, replacement))


def _redact_range(
    page: Any,
    row: list[Word],
    char_start: int,
    char_end: int,
    replacement: str,
    covered: set[int],
    pending_text: list[tuple[Any, str]],
) -> None:
    cursor = 0
    covering: list[Word] = []
    covering_idx: list[int] = []
    for idx, w in enumerate(row):
        word_end = cursor + len(w.text)
        if word_end > char_start and cursor < char_end and idx not in covered:
            covering.append(w)
            covering_idx.append(idx)
        cursor = word_end + 1
        if cursor > char_end:
            break
    if not covering:
        return
    r = _rect(
        min(w.x0 for w in covering),
        min(w.top for w in covering),
        max(w.x1 for w in covering),
        max(w.bottom for w in covering),
    )
    page.add_redact_annot(r, fill=(1, 1, 1))
    if replacement:
        pending_text.append((r, replacement))
    covered.update(covering_idx)


def _redact_header(
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


def _shape_preserve(text: str) -> str:
    """Replace digits with '0' and ascii letters with 'x'; keep everything else.

    Output keeps the original length and stays alphanumeric, so the parser's
    txid classifier still recognises it after redaction.
    """
    out: list[str] = []
    for ch in text:
        if ch.isdigit():
            out.append("0")
        elif ch.isascii() and ch.isalpha():
            out.append("x")
        else:
            out.append(ch)
    return "".join(out)


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


def _redact_body(
    page: Any,
    pending_text: list[tuple[Any, str]],
    audit: list[str],
) -> None:
    rows = group_by_baseline(from_pymupdf_words(page.get_text("words")), ROW_TOL)

    for row in rows:
        line_text = " ".join(w.text for w in row)
        covered: set[int] = set()

        for regex, replacement, label in (
            (PHONE_RE, "0800000000", "phone"),
            (ACCT_SPACED_RE, "000 000 0000", "acct-spaced"),
            (EMAIL_RE, "test@example.com", "email"),
        ):
            for m in regex.finditer(line_text):
                _redact_range(page, row, m.start(), m.end(), replacement, covered, pending_text)
                audit.append(f"{label}: {m.group(0)!r} -> {replacement!r}")

        classes = [classify(w.text) for w in row]

        # Shape-preserving redaction of every alnum token (transaction IDs and
        # the long internal references on stamp-duty rows). Opaque tokens are
        # not direct PII, but combined with date+amount they could correlate
        # back to a specific real transaction via the bank's support channel.
        for idx, w in enumerate(row):
            if idx in covered or classes[idx] != "alnum":
                continue
            _redact_word(page, w, _shape_preserve(w.text), pending_text)
            covered.add(idx)
            audit.append(f"txid: {w.text!r} -> {_shape_preserve(w.text)!r}")

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
                    _redact_word(page, row[idx], "", pending_text)
                    covered.add(idx)
                    audit.append(f"anchor-tail: {row[idx].text!r}")
            else:
                for idx in range(start, end):
                    if idx in covered:
                        continue
                    _redact_word(page, row[idx], "", pending_text)
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
            _redact_word(page, w, "", pending_text)
            covered.add(idx)
            audit.append(f"continuation: {w.text!r}")


class PalmPayRedactor(Redactor):
    bank = "palmpay"

    def redact(self, src: Path, dst: Path) -> RedactReport:
        report = RedactReport(bank=self.bank)
        doc = open_doc(src)
        try:
            for i in range(1, doc.page_count + 1):
                page = doc[i - 1]
                pending_text: list[tuple[Any, str]] = []
                page_audit: list[str] = []

                _redact_header(page, pending_text, page_audit)
                _redact_body(page, pending_text, page_audit)

                page.apply_redactions(images=PDF_REDACT_IMAGE_NONE)
                for r, text in pending_text:
                    page.insert_text(
                        (r.x0, r.y1 - 2),
                        text,
                        fontsize=8,
                        fontname="helv",
                        color=(0, 0, 0),
                    )

                report.pages += 1
                report.redactions += len(page_audit)
                report.audit.append((i, page_audit))

            doc.save(str(dst), garbage=4, deflate=True, clean=True)
        finally:
            doc.close()

        return report


register(PalmPayRedactor())
