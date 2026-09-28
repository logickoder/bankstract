import csv
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO, TypedDict

from ..schema import Transaction

# Append new columns at the end so positional consumers keep the first seven.
FIELDNAMES = [
    "date",
    "narration",
    "debit",
    "credit",
    "balance",
    "reference",
    "currency",
    "has_time",
]


class _Row(TypedDict):
    date: str
    narration: str
    debit: str
    credit: str
    balance: str
    reference: str
    currency: str
    has_time: str


def _row(tx: Transaction) -> _Row:
    return {
        "date": tx.date.isoformat(),
        "narration": tx.narration,
        "debit": str(tx.debit),
        "credit": str(tx.credit),
        "balance": "" if tx.balance is None else str(tx.balance),
        "reference": tx.reference or "",
        "currency": tx.currency,
        "has_time": "true" if tx.has_time else "false",
    }


def write_csv(transactions: Iterable[Transaction], target: Path | TextIO) -> int:
    rows = list(transactions)
    if isinstance(target, Path):
        with open(target, "w", newline="", encoding="utf-8") as f:
            _write(rows, f)
    else:
        _write(rows, target)
    return len(rows)


def _write(rows: list[Transaction], stream: TextIO) -> None:
    writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
    writer.writeheader()
    for tx in rows:
        writer.writerow(_row(tx))
