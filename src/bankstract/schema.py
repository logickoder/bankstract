from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Format = Literal["pdf", "xlsx"]


class Transaction(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    # `datetime`, not `date`, because some banks (PalmPay) include the
    # transaction timestamp. Banks that only emit a date (FBN) populate this
    # with time=00:00:00.
    date: datetime
    narration: str
    debit: Decimal = Field(default=Decimal("0"))
    credit: Decimal = Field(default=Decimal("0"))
    # None for banks (e.g. PalmPay) whose statements omit a running balance
    # column. Such parsers MUST populate ParseResult.total_credit/total_debit
    # so reconciliation can fall back to a totals-based check.
    balance: Decimal | None = None
    reference: str | None = None
    currency: str = "NGN"


@dataclass(frozen=True)
class StatementMetadata:
    bank: str | None = None
    account_holder: str | None = None
    # Mask all but last 4 digits ("XXXXXX1234"). Parsers redact at extract
    # time so the field is safe to log / persist without further scrubbing.
    account_number_masked: str | None = None
    statement_period_start: datetime | None = None
    statement_period_end: datetime | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None


@dataclass
class ParseResult:
    transactions: list[Transaction] = field(default_factory=list)
    total_credit: Decimal | None = None
    total_debit: Decimal | None = None
    format_version: str | None = None
    metadata: StatementMetadata | None = None
    # Set False when the statement's balance column doesn't satisfy
    # `prev.balance ± debit/credit == curr.balance` despite carrying per-row
    # balances (e.g. OPay's wallet column omits implicit OWealth side-effects
    # that move funds between sub-accounts atomically). Parsers that opt out
    # MUST populate total_credit/total_debit so verify_totals still catches
    # silently-dropped rows.
    row_wise_reconcilable: bool = True


@dataclass
class RedactReport:
    bank: str
    pages: int = 0
    redactions: int = 0
    # (page_number, [audit-line, ...]) — surfaces the per-page label of every
    # redaction performed. Cloud consumers log counts; never the entries
    # themselves (they may carry partial PII fragments mid-redaction).
    audit: list[tuple[int, list[str]]] = field(default_factory=list)


@dataclass(frozen=True)
class RedactResult:
    # Raw bytes of the redacted file (PDF or XLSX). In-memory only — the
    # redactor never writes to disk on this path so streaming callers
    # (HTTP responses, archives) get the payload without tempfile cleanup.
    data: bytes
    bank: str
    format: Format
    format_version: str
    report: RedactReport


class ParseError(Exception):
    """Catchall for parse failures. Reserved for genuinely undiagnosable
    causes — every parser-side raise should prefer one of the typed
    subclasses below. A bare ParseError raise inside `parsers/` or
    `_pdfplumber.py` / `_xlsx.py` must be preceded by a `# type-unknown:`
    comment justifying why no subclass fits; an AST audit test in the suite
    fails the PR otherwise."""

    def __init__(self, message: str, *, format_version: str | None = None) -> None:
        super().__init__(message)
        self.format_version = format_version


class EncryptedSourceError(ParseError):
    """Source PDF or XLSX is password-protected. The file is a valid format —
    we just can't read it. Cloud / CLI maps to a 'save unprotected version'
    user message rather than 'file an issue'. Raised only in boundary
    modules (`_pdfplumber.py`, `_xlsx.py`), never inside parsers."""


class EmptyStatementError(ParseError):
    """Parser ran clean, bank was detected, zero transactions were extracted.
    Either the statement legitimately has no rows in the period OR the layout
    drifted in a way that silently skipped every row. `marker_coverage`
    carries the parser's `detect_confidence` at raise time so the caller can
    distinguish: high coverage + 0 rows ≈ legitimately empty; lower coverage
    + 0 rows ≈ silent drift."""

    def __init__(
        self,
        message: str,
        *,
        format_version: str | None = None,
        marker_coverage: float = 0.0,
    ) -> None:
        super().__init__(message, format_version=format_version)
        self.marker_coverage = marker_coverage


class LayoutDriftError(ParseError):
    """Bank was detected (detect_confidence > 0) but row extraction broke —
    expected text anchors missing, column positions shifted, header rows in
    an unexpected order. Almost always means the bank revised the PDF/XLSX
    format. `format_version` carries the version the parser was written for
    so Cloud / CLI can surface 'we saw version X, parser expects different
    structure'."""


class ReconciliationError(Exception):
    def __init__(self, message: str, *, row_index: int | None = None) -> None:
        super().__init__(message)
        self.row_index = row_index
