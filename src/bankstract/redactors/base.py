from abc import ABC, abstractmethod
from typing import Any

from .._progress import emit
from .._pymupdf import PDF_REDACT_IMAGE_NONE, open_doc
from .._source import Source
from ..schema import Format, RedactReport, RedactResult


class Redactor(ABC):
    """Template-method base for PDF redactors: subclasses implement per-page
    header and body passes; the open/apply/save/insert-text plumbing lives
    here once. Redactors that support additional formats (e.g. XLSX) should
    add `supported_formats` and override `redact()` to dispatch by sniffed
    format before falling through to this PDF template path.

    `redact()` returns a `RedactResult` carrying the in-memory bytes — the
    CLI wrapper is responsible for writing those bytes to disk. The lib
    API hands them straight to streaming callers (HTTP responses, etc.)
    without ever touching the filesystem.
    """

    bank: str
    supported_formats: tuple[Format, ...] = ("pdf",)
    # Format version for the PDF redaction path. Subclasses that also
    # handle XLSX override `redact()` and stamp their own per-format value.
    format_version: str = ""

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

    def redact(self, source: Source) -> RedactResult:
        report = RedactReport(bank=self.bank)
        doc = open_doc(source)
        try:
            total = doc.page_count
            for i in range(1, total + 1):
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
                emit("redact_page", i, total)

            data: bytes = doc.write(garbage=4, deflate=True, clean=True)
        finally:
            doc.close()
        return RedactResult(
            data=data,
            bank=self.bank,
            format="pdf",
            format_version=self.format_version or f"{self.bank}-pdf-unknown",
            report=report,
        )
