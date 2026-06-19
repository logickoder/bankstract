"""
Shared low-level redaction primitives. Every per-bank redactor calls into
these, so the bank-specific files stay focused on what to redact (label
anchors, narration vocab) rather than how to talk to pymupdf.
"""

from __future__ import annotations

import re
from typing import Any

from .._layout import Word, from_pymupdf_words, group_by_baseline
from .._pymupdf import rect as _rect

RegexSweep = tuple[re.Pattern[str], str, str]  # (pattern, replacement, audit label)

# Shared PII regexes + canonical replacements. Every redactor scrubs the same
# phone + email patterns; per-bank files add their own bank-specific sweeps
# (e.g. PalmPay's spaced-account-number pattern) on top.
PHONE_RE = re.compile(r"\b0\d{2}\s?\d{4}\s?\d{4}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_REPLACEMENT = "0800000000"
EMAIL_REPLACEMENT = "test@example.com"

DEFAULT_SWEEPS: tuple[RegexSweep, ...] = (
    (PHONE_RE, PHONE_REPLACEMENT, "phone"),
    (EMAIL_RE, EMAIL_REPLACEMENT, "email"),
)


def shape_preserve(text: str) -> str:
    """Replace digits with '0' and ASCII letters with 'x'; keep everything else.

    Output keeps the original length and stays alphanumeric so the parser's
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


def redact_word(
    page: Any,
    word: Word,
    replacement: str,
    pending_text: list[tuple[Any, str]],
) -> None:
    r = _rect(word.x0, word.top, word.x1, word.bottom)
    page.add_redact_annot(r, fill=(1, 1, 1))
    if replacement:
        pending_text.append((r, replacement))


def page_rows(page: Any, row_tol: float = 4.0) -> list[list[Word]]:
    """Group a pymupdf page's words into visual rows, ready for redaction."""
    return group_by_baseline(from_pymupdf_words(page.get_text("words")), row_tol)


def apply_regex_sweeps(
    page: Any,
    row: list[Word],
    sweeps: tuple[RegexSweep, ...],
    pending_text: list[tuple[Any, str]],
    audit: list[str],
    covered: set[int],
) -> None:
    """Run each (regex, replacement, label) over the row's joined text and
    redact the covering bbox in-place. Marks word indices as `covered` so
    downstream column-blank loops don't double-redact."""
    line_text = " ".join(w.text for w in row)
    for regex, replacement, label in sweeps:
        for m in regex.finditer(line_text):
            redact_range(page, row, m.start(), m.end(), replacement, covered, pending_text)
            audit.append(f"{label}: {m.group(0)!r} -> {replacement!r}")


def redact_range(
    page: Any,
    row: list[Word],
    char_start: int,
    char_end: int,
    replacement: str,
    covered: set[int],
    pending_text: list[tuple[Any, str]],
) -> None:
    """Find every word bbox covering chars [start, end) of the joined-line
    representation of `row` and redact them as a single bbox."""
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
