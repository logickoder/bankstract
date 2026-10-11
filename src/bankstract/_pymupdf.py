"""
Typed facade over pymupdf.

pymupdf ships no stubs, so every `pymupdf.X` access pattern in body code
trips strict type checkers (CLI tools silence this via the project config,
but VS Code Pylance can override it). Funnelling all access through this
module restricts the untyped surface to one file.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import chain
from typing import Any, cast

import pymupdf as _pymupdf  # type: ignore[import-untyped]

from ._source import Source, read_bytes, rewind

# cast bypasses pyright's reportAttributeAccessIssue since pymupdf has no stubs.
PDF_REDACT_IMAGE_NONE: Any = cast(Any, _pymupdf).PDF_REDACT_IMAGE_NONE


def open_doc(source: Source) -> Any:
    """Open a PDF from a Path or seekable binary stream. The redactor
    needs both — Path for the CLI, BytesIO for the lib API + Cloud
    worker which never touches disk."""
    read = getattr(source, "read", None)
    if read is not None:
        rewind(source)
        return _pymupdf.open(stream=read(), filetype="pdf")
    return _pymupdf.open(str(source))


def rect(x0: float, y0: float, x1: float, y1: float) -> Any:
    return _pymupdf.Rect(x0, y0, x1, y1)


def new_doc() -> Any:
    return _pymupdf.open()


BBox = tuple[float, float, float, float]

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_FIRST_PAGE_SECTION = re.compile(rb"startxref\s+0(?!\d)")
_HEX_STRING = re.compile(r"<([0-9A-Fa-f]*)>")
# Decoded content stream of one page. Real statement pages top out near 36 KB. A
# crafted page of 400k one-glyph runs is 14 MB and costs 700 MB to extract, about
# 680 times the file. Checked before extraction: a cap on runs applied after it
# comes too late.
_MAX_PAGE_CONTENT = 2 * 1024 * 1024


@dataclass(frozen=True)
class PdfSpan:
    page: int  # 1-based
    text: str
    font: str
    size: float
    bbox: BBox
    seqno: int
    # Boxes of the visible glyphs. A cover that hides one digit leaves the run's
    # own box mostly uncovered, so the cover check works glyph by glyph.
    glyphs: tuple[BBox, ...] = ()


@dataclass(frozen=True)
class PdfFill:
    page: int  # 1-based
    bbox: BBox
    opacity: float
    seqno: int


@dataclass(frozen=True)
class PdfForensics:
    producer: str
    creation_date: str
    mod_date: str
    # Linearized PDFs carry a second startxref section by design. It is
    # subtracted here.
    revisions: int
    spans: tuple[PdfSpan, ...]
    fills: tuple[PdfFill, ...]
    # Text runs and fills left out for coordinates that are not finite numbers.
    unreadable: int = 0
    # Pages whose content was too large to extract. 1-based.
    oversized: tuple[int, ...] = ()
    # The trailer /ID pair as lowercase hex, or None when absent or not two hex strings.
    id_halves: tuple[str, str] | None = None

    @property
    def fonts(self) -> frozenset[str]:
        return frozenset(s.font for s in self.spans)


def _revisions(raw: bytes) -> int:
    """Revisions in a PDF file: the number of `startxref` keywords. Not
    `startxref <offset>`: PDF reads a comment as whitespace, so
    `startxref %c` then the offset is a section a pattern for digits misses.
    A bare "%%EOF" can sit in a string, and a forger can leave it off. The
    `/Prev` chain would miss a revision written without a `/Prev`.

    Every keyword counts, including one inside an uncompressed attachment.
    Skipping sections "inside a stream body" would trust the file's own
    `/Length`, which a forger sets. A reader finds the last `startxref` from
    the end of the file and ignores stream boundaries, so a forged tail can
    sit inside a fake stream and vanish from the count. The cost is a loud
    false positive on a statement that embeds an uncompressed PDF.

    A linearized file writes a first-page section at the top, `startxref 0`.
    Only that section is discounted, and only with `/Linearized` beside it.
    The marker alone cancels nothing, so a forged one hides no revision."""
    revisions = raw.count(b"startxref")
    head = raw[:1024]
    if b"/Linearized" in head and _FIRST_PAGE_SECTION.search(head):
        revisions -= 1
    return revisions


def _finite_run(glyphs: tuple[BBox, ...], size: float) -> bool:
    # One sum for the run: NaN or infinity anywhere makes the total non-finite.
    # The values come from float32 (at most 3.4e38), so a sum of them cannot overflow
    # a double. A per-value `isfinite` is exact too and measured 6x slower here.
    return math.isfinite(sum(chain.from_iterable(glyphs)) + size)


def _finite(box: BBox) -> bool:
    # A crafted file can place text or a fill at NaN or infinity. Rounding and
    # comparing those downstream raises or misleads, so they never leave here.
    return all(math.isfinite(c) for c in box)


def pdf_forensics(source: Source) -> PdfForensics:
    """Metadata, revision count, text runs and fills with draw order. Fonts
    lose their subset prefix (`ABCDEF+Name` becomes `Name`)."""
    raw = read_bytes(source)
    revisions = _revisions(raw)

    doc: Any = _pymupdf.open(stream=raw, filetype="pdf")
    try:
        meta: dict[str, str] = doc.metadata or {}
        halves = _HEX_STRING.findall(doc.xref_get_key(-1, "ID")[1])
        id_halves = (halves[0].lower(), halves[1].lower()) if len(halves) == 2 else None
        spans: list[PdfSpan] = []
        fills: list[PdfFill] = []
        unreadable = 0
        oversized: list[int] = []
        for page in doc:
            number: int = page.number + 1
            if len(page.read_contents()) > _MAX_PAGE_CONTENT:
                oversized.append(number)
                continue
            for run in page.get_texttrace():
                # The redactor blanks removed glyphs to spaces inside the run.
                # The run's own bbox spans them, so box only what is visible.
                visible = [c for c in run["chars"] if chr(c[0]).strip()]
                if not visible:
                    continue
                glyphs: tuple[BBox, ...] = tuple(c[3] for c in visible)
                box: BBox = (
                    min(g[0] for g in glyphs),
                    min(g[1] for g in glyphs),
                    max(g[2] for g in glyphs),
                    max(g[3] for g in glyphs),
                )
                size = float(run["size"])
                if not _finite_run(glyphs, size):
                    unreadable += 1
                    continue
                spans.append(
                    PdfSpan(
                        page=number,
                        text="".join(chr(c[0]) for c in run["chars"]),
                        font=_SUBSET_PREFIX.sub("", run["font"]),
                        size=size,
                        bbox=box,
                        seqno=int(run["seqno"]),
                        glyphs=glyphs,
                    )
                )
            # The c-variant returns plain tuples, not a Rect per path. Same keys.
            for path in page.get_cdrawings():
                if path.get("fill") is None:
                    continue
                rect: BBox = path["rect"]
                if not _finite(rect):
                    unreadable += 1
                    continue
                fills.append(
                    PdfFill(
                        page=number,
                        bbox=rect,
                        opacity=float(path.get("fill_opacity") or 1.0),
                        seqno=int(path["seqno"]),
                    )
                )
    finally:
        doc.close()
    return PdfForensics(
        producer=meta.get("producer") or "",
        creation_date=meta.get("creationDate") or "",
        mod_date=meta.get("modDate") or "",
        revisions=revisions,
        spans=tuple(spans),
        fills=tuple(fills),
        unreadable=unreadable,
        oversized=tuple(oversized),
        id_halves=id_halves,
    )
