"""
Typed facade over pymupdf.

pymupdf ships no stubs, so every `pymupdf.X` access pattern in body code
trips strict type checkers (CLI tools silence this via the project config,
but VS Code Pylance can override it). Funnelling all access through this
module restricts the untyped surface to one file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pymupdf as _pymupdf  # type: ignore[import-untyped]

from ._source import Source, rewind

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


@dataclass(frozen=True)
class PdfSpan:
    page: int  # 1-based
    text: str
    font: str
    size: float
    bbox: BBox
    seqno: int


@dataclass(frozen=True)
class PdfFill:
    page: int  # 1-based
    bbox: BBox
    color: tuple[float, ...]
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

    @property
    def fonts(self) -> frozenset[str]:
        return frozenset(s.font for s in self.spans)


def _raw_bytes(source: Source) -> bytes:
    if isinstance(source, Path):
        return source.read_bytes()
    rewind(source)
    return source.read()


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


def _bbox(raw: Any) -> BBox:
    return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))


def pdf_forensics(source: Source) -> PdfForensics:
    """Metadata, revision count, text runs and fills with draw order. Fonts
    lose their subset prefix (`ABCDEF+Name` becomes `Name`)."""
    raw = _raw_bytes(source)
    revisions = _revisions(raw)

    doc: Any = _pymupdf.open(stream=raw, filetype="pdf")
    try:
        meta: dict[str, str] = doc.metadata or {}
        spans: list[PdfSpan] = []
        fills: list[PdfFill] = []
        for page in doc:
            number: int = page.number + 1
            for run in page.get_texttrace():
                # The redactor blanks removed glyphs to spaces inside the run.
                # The run's own bbox spans them, so box only what is visible.
                visible = [c for c in run["chars"] if chr(c[0]).strip()]
                if not visible:
                    continue
                spans.append(
                    PdfSpan(
                        page=number,
                        text="".join(chr(c[0]) for c in run["chars"]),
                        font=_SUBSET_PREFIX.sub("", run["font"]),
                        size=float(run["size"]),
                        bbox=(
                            min(float(c[3][0]) for c in visible),
                            min(float(c[3][1]) for c in visible),
                            max(float(c[3][2]) for c in visible),
                            max(float(c[3][3]) for c in visible),
                        ),
                        seqno=int(run["seqno"]),
                    )
                )
            for path in page.get_drawings():
                fill = path.get("fill")
                if fill is None:
                    continue
                fills.append(
                    PdfFill(
                        page=number,
                        bbox=_bbox(path["rect"]),
                        color=tuple(float(c) for c in fill),
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
    )
