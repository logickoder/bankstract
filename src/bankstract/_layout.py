"""
Shared PDF-layout primitives used by both the parser and redactor stacks.

A `Word` is the canonical typed token. pymupdf returns word tuples; pdfplumber
returns dicts. Both are converted to `Word` at the boundary so downstream code
stays strictly typed.

`classify` and `group_by_baseline` are intentionally bank-agnostic — they
operate on shapes, not vocabulary. Bank-specific dictionaries
(NARRATION_PHRASES, HEADER_LABELS, etc.) live with their consuming module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

TokenKind = Literal["blank", "date", "time", "ampm", "amount", "alnum", "text"]

DATE_TOK = re.compile(r"\d{2}/\d{2}/\d{4}")
TIME_TOK = re.compile(r"\d{2}:\d{2}:\d{2}")
AMOUNT_TOK = re.compile(r"[+-]?\d[\d,]*\.\d{2}")
NAIRA_TOK = re.compile(r"₦\d[\d,]*\.\d{2}")
TXID_TOK = re.compile(r"[A-Za-z0-9_]{6,}")


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float


def classify(text: str) -> TokenKind:
    if not text:
        return "blank"
    if DATE_TOK.fullmatch(text):
        return "date"
    if TIME_TOK.fullmatch(text):
        return "time"
    if text in ("AM", "PM"):
        return "ampm"
    if AMOUNT_TOK.fullmatch(text) or NAIRA_TOK.fullmatch(text):
        return "amount"
    if TXID_TOK.fullmatch(text) and any(c.isdigit() for c in text):
        return "alnum"
    return "text"


def group_by_baseline(words: list[Word], tol: float) -> list[list[Word]]:
    """Group words sharing a visual baseline. PalmPay and similar layouts
    place a row's date / narration / txid columns at slightly offset
    y-coordinates (txid often sits ~4 pt above the date baseline), so the
    `top` value drifts WITHIN a single visual row. We compare each candidate
    word against the LAST appended word's top, not the first — otherwise a
    row whose first word is at the high edge of the drift will split off
    the tokens at the low edge."""
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda x: (round(x.top / tol) * tol, x.x0)):
        if rows and abs(rows[-1][-1].top - w.top) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda x: x.x0)
    return rows


def from_pymupdf_words(raw: Any) -> list[Word]:
    """Adapt pymupdf's (x0, y0, x1, y1, text, block, line, word_no) tuples."""
    return [
        Word(text=str(w[4]), x0=float(w[0]), top=float(w[1]), x1=float(w[2]), bottom=float(w[3]))
        for w in raw
    ]


def from_pdfplumber_words(raw: Any) -> list[Word]:
    """Adapt pdfplumber's word dicts."""
    return [
        Word(
            text=str(w["text"]),
            x0=float(w["x0"]),
            top=float(w["top"]),
            x1=float(w["x1"]),
            bottom=float(w["bottom"]),
        )
        for w in raw
    ]
