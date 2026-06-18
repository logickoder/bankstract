from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .._pymupdf import PDF_REDACT_IMAGE_NONE, open_doc
from .._xlsx import Format


@dataclass
class RedactReport:
    bank: str
    pages: int = 0
    redactions: int = 0
    audit: list[tuple[int, list[str]]] = field(default_factory=list)


class Redactor(ABC):
    """Template-method base for PDF redactors: subclasses implement per-page
    header and body passes; the open/apply/save/insert-text plumbing lives
    here once. Redactors that support additional formats (e.g. XLSX) should
    add `supported_formats` and override `redact()` to dispatch by file
    extension before falling through to the PDF template path."""

    bank: str
    supported_formats: tuple[Format, ...] = ("pdf",)

    @abstractmethod
    def redact_header(
        self,
        page: Any,
        pending_text: list[tuple[Any, str]],
        audit: list[str],
    ) -> None: ...

    @abstractmethod
    def redact_body(
        self,
        page: Any,
        pending_text: list[tuple[Any, str]],
        audit: list[str],
    ) -> None: ...

    def redact(self, src: Path, dst: Path) -> RedactReport:
        report = RedactReport(bank=self.bank)
        doc = open_doc(src)
        try:
            for i in range(1, doc.page_count + 1):
                page = doc[i - 1]
                pending_text: list[tuple[Any, str]] = []
                page_audit: list[str] = []

                self.redact_header(page, pending_text, page_audit)
                self.redact_body(page, pending_text, page_audit)

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
