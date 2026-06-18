import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

from ..schema import ParseResult


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"unserializable: {type(value).__name__}")


def _result_to_dict(result: ParseResult) -> dict[str, Any]:
    bank = result.metadata.bank if result.metadata is not None else None
    return {
        "bank": bank,
        "format_version": result.format_version,
        "metadata": result.metadata,
        "totals": {
            "credit": str(result.total_credit) if result.total_credit is not None else None,
            "debit": str(result.total_debit) if result.total_debit is not None else None,
        },
        "transactions": [tx.model_dump(mode="json") for tx in result.transactions],
    }


def write_json(result: ParseResult, out: Path | TextIO) -> int:
    payload = _result_to_dict(result)
    serialized = json.dumps(payload, default=_encode, indent=2, ensure_ascii=False)
    if isinstance(out, Path):
        out.write_text(serialized, encoding="utf-8")
    else:
        out.write(serialized)
        out.write("\n")
    return len(result.transactions)
