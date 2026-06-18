import json
from datetime import datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path

from bankstract.schema import ParseResult, StatementMetadata, Transaction
from bankstract.writers.json import write_json


def _sample_result() -> ParseResult:
    return ParseResult(
        transactions=[
            Transaction(
                date=datetime(2026, 6, 1, 12, 0, 0),
                narration="FOO PURCHASE",
                debit=Decimal("100.50"),
                credit=Decimal("0"),
                balance=Decimal("899.50"),
                reference="REF-1",
            ),
            Transaction(
                date=datetime(2026, 6, 2),
                narration="BAR CREDIT",
                debit=Decimal("0"),
                credit=Decimal("250.00"),
                balance=Decimal("1149.50"),
            ),
        ],
        total_credit=Decimal("250.00"),
        total_debit=Decimal("100.50"),
        format_version="acme-2026-01",
        metadata=StatementMetadata(
            bank="acme",
            account_holder="QUUX",
            account_number_masked="XXXXXX1234",
            statement_period_start=datetime(2026, 6, 1),
            statement_period_end=datetime(2026, 6, 30),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1149.50"),
        ),
    )


def test_write_json_to_path(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    count = write_json(_sample_result(), out)
    assert count == 2
    payload = json.loads(out.read_text())
    assert "bank" not in payload  # canonical bank lives at metadata.bank
    assert payload["format_version"] == "acme-2026-01"
    assert payload["metadata"]["bank"] == "acme"
    assert payload["metadata"]["account_holder"] == "QUUX"
    assert payload["metadata"]["account_number_masked"] == "XXXXXX1234"
    assert payload["metadata"]["opening_balance"] == "1000.00"
    assert payload["metadata"]["closing_balance"] == "1149.50"
    assert payload["totals"] == {"credit": "250.00", "debit": "100.50"}
    assert len(payload["transactions"]) == 2
    tx0 = payload["transactions"][0]
    assert tx0["date"] == "2026-06-01T12:00:00"
    # pydantic mode="json" serializes Decimal as string.
    assert tx0["debit"] == "100.50"
    assert tx0["balance"] == "899.50"


def test_write_json_to_stream() -> None:
    buf = StringIO()
    write_json(_sample_result(), buf)
    payload = json.loads(buf.getvalue())
    assert payload["metadata"]["bank"] == "acme"


def test_write_json_handles_none_metadata() -> None:
    result = ParseResult(transactions=[], format_version="fake-v1")
    buf = StringIO()
    write_json(result, buf)
    payload = json.loads(buf.getvalue())
    assert "bank" not in payload
    assert payload["metadata"] is None
    assert payload["totals"] == {"credit": None, "debit": None}
    assert payload["transactions"] == []
