import csv
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict

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


def write_csv(transactions: Iterable[Transaction], out_path: Path) -> int:
    rows = list(transactions)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for tx in rows:
            row: _Row = {
                "date": tx.date.isoformat(),
                "narration": tx.narration,
                "debit": str(tx.debit),
                "credit": str(tx.credit),
                "balance": "" if tx.balance is None else str(tx.balance),
                "reference": tx.reference or "",
                "currency": tx.currency,
            }
            writer.writerow(row)
    return len(rows)


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
