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
    def __init__(self, message: str, *, format_version: str | None = None) -> None:
        super().__init__(message)
        self.format_version = format_version


class ReconciliationError(Exception):
    def __init__(self, message: str, *, row_index: int | None = None) -> None:
        super().__init__(message)
        self.row_index = row_index
