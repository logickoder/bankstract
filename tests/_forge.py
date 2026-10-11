"""Forgery helpers shared by the integrity tests. Each builds an edit a real
forger could make, from a committed sample."""

import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from bankstract._layout import AMOUNT_TOK
from bankstract._pymupdf import PdfSpan, new_doc, open_doc, pdf_forensics

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


def blank_pdf(tmp_path: Path) -> Path:
    """One page of text no parser claims."""
    doc: Any = new_doc()
    doc.new_page().insert_text((60, 60), "FOO BAR", fontsize=10)
    out = tmp_path / "blank.pdf"
    doc.save(str(out))
    doc.close()
    return out


def locked_pdf(tmp_path: Path) -> Path:
    doc: Any = new_doc()
    doc.new_page()
    out = tmp_path / "locked.pdf"
    doc.save(str(out), encryption=3, user_pw="x", owner_pw="y")
    doc.close()
    return out


def forged_balance_pdf(tmp_path: Path) -> Path:
    """The zenith sample with one balance changed, so the chain breaks."""
    doc: Any = open_doc(ZENITH)
    retype(doc, balance_span())
    out = tmp_path / "forged.pdf"
    doc.save(str(out))
    doc.close()
    return out


def _runs_body(runs: int) -> bytes:
    """`runs` one-glyph text objects. Each becomes its own run."""
    return b"\n".join(
        b"BT /helv 6 Tf %d %d Td (x) Tj ET" % (10 + i % 500, 10 + (i // 500) % 700)
        for i in range(runs)
    )


def runs_page(tmp_path: Path, runs: int) -> Path:
    """A page whose own content stream holds `runs` text runs."""
    doc: Any = new_doc()
    page = doc.new_page()
    page.insert_text((10, 10), "a", fontsize=6)
    xref = page.get_contents()[0]
    doc.update_stream(xref, doc.xref_stream(xref) + b"\n" + _runs_body(runs))
    out = tmp_path / "runs.pdf"
    doc.save(str(out))
    doc.close()
    return out


def form_page(tmp_path: Path, runs: int) -> Path:
    """A page of 62 bytes that invokes a form holding `runs` text runs. The
    content-size gate reads the page stream only, so it never trips."""
    doc: Any = new_doc()
    page = doc.new_page()
    page.insert_text((10, 10), "a", fontsize=6)
    font = page.get_fonts()[0][0]
    form = doc.get_new_xref()
    doc.update_object(
        form,
        f"<< /Type /XObject /Subtype /Form /BBox [0 0 612 842] "
        f"/Resources << /Font << /helv {font} 0 R >> >> >>",
    )
    doc.update_stream(form, _runs_body(runs))
    doc.xref_set_key(
        page.xref, "Resources", f"<< /Font << /helv {font} 0 R >> /XObject << /Fm0 {form} 0 R >> >>"
    )
    xref = page.get_contents()[0]
    doc.update_stream(xref, doc.xref_stream(xref) + b"\nq /Fm0 Do Q\n")
    out = tmp_path / "form.pdf"
    doc.save(str(out))
    doc.close()
    return out


def equal_id_copy(src: Path, out: Path) -> Path:
    """`src` with the second half of its trailer /ID set to the first, as fbn and
    opay write it. Same length, so the file's offsets stay valid."""
    data = src.read_bytes()
    pattern = re.compile(rb"(/ID\s*\[\s*<)([0-9A-Fa-f]+)(>\s*<)([0-9A-Fa-f]+)(>\s*\])")
    match = pattern.search(data)
    assert match, "no hex /ID pair in the sample"
    first = match.group(2)
    out.write_bytes(
        data[: match.start(4)]
        + first.ljust(len(match.group(4)), b"0")[: len(match.group(4))]
        + data[match.end(4) :]
    )
    return out
