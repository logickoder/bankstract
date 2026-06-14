from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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


@dataclass
class ParseResult:
    transactions: list[Transaction] = field(default_factory=list)
    total_credit: Decimal | None = None
    total_debit: Decimal | None = None
    format_version: str | None = None


class ParseError(Exception):
    def __init__(self, message: str, *, format_version: str | None = None) -> None:
        super().__init__(message)
        self.format_version = format_version


class ReconciliationError(Exception):
    def __init__(self, message: str, *, row_index: int | None = None) -> None:
        super().__init__(message)
        self.row_index = row_index
