from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

Format = Literal["pdf", "xlsx"]
OutputFormat = Literal["csv", "json"]


class Transaction(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    # `datetime`, not `date`, because some banks (PalmPay) include the
    # transaction timestamp. Banks that only emit a date (FBN) populate this
    # with time=00:00:00.
    date: datetime
    narration: str
    # Both may be nonzero on one row when the statement prints both. Parsers
    # report them as printed and never net them. Consumers carry both.
    debit: Decimal = Field(default=Decimal("0"))
    credit: Decimal = Field(default=Decimal("0"))
    # None for banks (e.g. PalmPay) whose statements omit a running balance
    # column. Such parsers MUST populate ParseResult.total_credit/total_debit
    # so reconciliation can fall back to a totals-based check.
    balance: Decimal | None = None
    reference: str | None = None
    currency: str = "NGN"
    # True only when the statement printed a time for this row. False means
    # `date` carries a padded 00:00:00, so consumers must not treat the time
    # as real (transfer-pair matching, dedup). Default False so a parser that
    # forgets to set it never overstates precision.
    has_time: bool = False

    # Decimal keeps the sign of zero, so a "-0.00" cell would reach the wire
    # as "-0.00". Adding 0 drops the sign and keeps the exponent.
    @field_validator("debit", "credit", "balance")
    @classmethod
    def _unsigned_zero(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value == 0:
            return value + 0
        return value

    # A debit or credit column already carries the direction, so a sign means
    # the parser misread the column. Raised as LayoutDriftError, not
    # ValueError: pydantic wraps a ValueError into a ValidationError whose
    # message quotes the amount, and that message reaches logs. Pydantic lets
    # any other exception through unwrapped.
    @field_validator("debit", "credit")
    @classmethod
    def _unsigned(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        if value < 0:
            raise LayoutDriftError(
                f"Negative {info.field_name} on a transaction row. "
                "A debit or credit column carries no sign, so the parser misread it. "
                "File an issue with the bank and format version."
            )
        return value


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


# passed: the check ran clean. not_available: the statement lacks the evidence
# (no header totals, or some row has balance=None). disabled: the parser opted
# out of row-wise via `row_wise_disabled`. A failed check raises
# ReconciliationError instead of reporting a status.
CheckStatus = Literal["passed", "not_available", "disabled"]


@dataclass(frozen=True)
class ReconciliationReport:
    totals: CheckStatus
    row_wise: CheckStatus
    # The parser's reason when row_wise is "disabled". Public copy, shown to
    # users as is. None otherwise.
    row_wise_reason: str | None = None


# Frozen: reconcile_result returns a checked copy, and tests share cached
# instances. Nothing may mutate a result in place.
@dataclass(frozen=True)
class ParseResult:
    transactions: list[Transaction] = field(default_factory=list)
    total_credit: Decimal | None = None
    total_debit: Decimal | None = None
    format_version: str | None = None
    metadata: StatementMetadata | None = None
    # Parser opt-out for balances that are present but don't chain
    # (`prev.balance ± debit/credit != curr.balance` by design). None means
    # row-wise can run. A string disables it and is the reason, shown to users
    # through ReconciliationReport.row_wise_reason. Parsers that opt out MUST
    # populate total_credit/total_debit so verify_totals still catches
    # silently-dropped rows.
    row_wise_disabled: str | None = None
    # None until `reconcile_result` returns a checked copy. Parsers never set it.
    reconciliation: ReconciliationReport | None = None

    @property
    def bank(self) -> str | None:
        """The parser that matched. `parse()` always fills `metadata.bank`,
        the one stored copy. None only on a result built by hand."""
        return self.metadata.bank if self.metadata else None


# What reconcile_result returns. A frozen dataclass can't narrow the inherited
# `| None` field, so __post_init__ enforces it and `report` is the narrowed view.
@dataclass(frozen=True)
class ReconciledParseResult(ParseResult):
    def __post_init__(self) -> None:
        if self.reconciliation is None:
            raise ValueError(
                "ReconciledParseResult needs a reconciliation report. "
                "Build one through reconcile_result()."
            )

    @property
    def report(self) -> ReconciliationReport:
        assert self.reconciliation is not None  # guaranteed by __post_init__
        return self.reconciliation


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

    def __init__(
        self,
        message: str,
        *,
        format_version: str | None = None,
        bank: str | None = None,
    ) -> None:
        super().__init__(message)
        self.format_version = format_version
        # Filled in by the engine when the failure came from a matched
        # parser or redactor. None when detection itself failed.
        self.bank = bank


class ResourceLimitError(Exception):
    """A check ran in a worker process and the worker did not finish: it passed
    its time limit, ran out of memory, or died. The file is not known to be
    clean. Treat it as untrusted, never as a pass.

    Not a `ParseError`. A caller who skips files the parser cannot read with
    `except ParseError` must not skip these: the file stopped the checker, and
    that says nothing about its layout."""


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
    """The statement parsed but its numbers don't add up. Not a ParseError:
    callers (the CLI among them) handle the two differently."""

    def __init__(
        self,
        message: str,
        *,
        row_index: int | None = None,
        bank: str | None = None,
        format_version: str | None = None,
    ) -> None:
        super().__init__(message)
        self.row_index = row_index
        # Stamped by reconcile_result from the result it checked.
        self.bank = bank
        self.format_version = format_version
