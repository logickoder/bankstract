"""Forgery helpers shared by the integrity tests. Each builds an edit a real
forger could make, from a committed sample."""

import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from bankstract._layout import AMOUNT_TOK
from bankstract._pymupdf import PdfSpan, open_doc, pdf_forensics

from ._fixtures import TESTS_ROOT


def sample(bank: str, ext: str = "pdf") -> Path:
    return TESTS_ROOT / bank / "fixtures" / f"sample.{ext}"


ZENITH = sample("zenith")
OPAY_XLSX = sample("opay", "xlsx")


def balance_span(path: Path = ZENITH) -> PdfSpan:
    """A 7pt amount from the middle of the right-most column, the balance.
    Changing a value there breaks the balance chain."""
    amounts = [
        s
        for s in pdf_forensics(path).spans
        if AMOUNT_TOK.fullmatch(s.text.strip()) and abs(s.size - 7.0) < 0.01
    ]
    edge = max(round(s.bbox[2]) for s in amounts)
    column = [s for s in amounts if round(s.bbox[2]) == edge]
    return column[len(column) // 2]


def column_span(path: Path, *, prefix: str) -> PdfSpan:
    """The middle amount of the largest column of amounts starting with `prefix`."""
    columns: dict[int, list[PdfSpan]] = defaultdict(list)
    for span in pdf_forensics(path).spans:
        text = span.text.strip()
        if text.startswith(prefix) and AMOUNT_TOK.fullmatch(text):
            columns[round(span.bbox[2])].append(span)
    largest = max(columns.values(), key=len)
    return largest[len(largest) // 2]


def retype(
    doc: Any,
    span: PdfSpan,
    *,
    cover: bool = False,
    fontsize: float = 7,
    fontname: str = "helv",
) -> None:
    """Replace `span` with 9,999.00, left-aligned. By default the original text
    is removed. `cover=True` draws a white box over it and leaves the text."""
    page: Any = doc[span.page - 1]
    if cover:
        page.draw_rect(span.bbox, color=None, fill=(1, 1, 1))
    else:
        page.add_redact_annot(span.bbox)
        page.apply_redactions()
    page.insert_text(
        (span.bbox[0], span.bbox[3] - 2), "9,999.00", fontsize=fontsize, fontname=fontname
    )


def append_revision(src: Path, out: Path) -> None:
    """Edit `src` as an incremental save: the original bytes stay and a second
    `%%EOF` follows them."""
    shutil.copy(src, out)
    doc: Any = open_doc(out)
    doc[0].insert_text((20, 20), "x", fontsize=6)
    doc.saveIncr()
    doc.close()
