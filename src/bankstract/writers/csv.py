import csv
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO, TypedDict

from ..schema import Transaction

FIELDNAMES = ["date", "narration", "debit", "credit", "balance", "reference", "currency"]


class _Row(TypedDict):
    date: str
    narration: str
    debit: str
    credit: str
    balance: str
    reference: str
    currency: str


def _row(tx: Transaction) -> _Row:
    return {
        "date": tx.date.isoformat(),
        "narration": tx.narration,
        "debit": str(tx.debit),
        "credit": str(tx.credit),
        "balance": "" if tx.balance is None else str(tx.balance),
        "reference": tx.reference or "",
        "currency": tx.currency,
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


class _Failure(TypedDict, total=False):
    block_number: int
    reason: str
    raw_text: str


def log_unparseable(failures: list[_Failure], log_path: Path) -> None:
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("bankstract — unparseable blocks\n")
        f.write("=" * 60 + "\n")
        f.write(f"Total failed blocks: {len(failures)}\n\n")
        for failure in failures:
            f.write(f"Block #{failure.get('block_number', '?')}\n")
            f.write(f"Reason : {failure.get('reason', 'unknown')}\n")
            f.write("Raw text:\n")
            for line in str(failure.get("raw_text", "")).splitlines():
                f.write(f" {line}\n")
            f.write("-" * 60 + "\n\n")
