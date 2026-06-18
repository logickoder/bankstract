"""CLI `-` sentinel round trip: stdin → parse → stdout (csv + json)."""

import json
from pathlib import Path

from click.testing import CliRunner

from bankstract.cli import main

PALMPAY_SAMPLE = Path(__file__).parent / "palmpay" / "fixtures" / "sample.pdf"


def test_stdin_to_stdout_json_auto() -> None:
    runner = CliRunner()
    pdf_bytes = PALMPAY_SAMPLE.read_bytes()
    result = runner.invoke(main, ["auto", "-", "-o", "-", "-f", "json"], input=pdf_bytes)
    assert result.exit_code == 0, result.output
    # Strip any trailing newline; payload is the only line of stdout.
    payload = json.loads(result.output.splitlines()[0]) if result.output.startswith("{") else None
    if payload is None:
        # CliRunner merges stderr by default — try parsing the JSON block.
        start = result.output.index("{")
        end = result.output.rindex("}") + 1
        payload = json.loads(result.output[start:end])
    assert payload["bank"] == "palmpay"
    assert payload["metadata"]["account_holder"] == "TEST USER"
    assert len(payload["transactions"]) > 0


def test_file_to_stdout_csv() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["palmpay", str(PALMPAY_SAMPLE), "-o", "-"])
    assert result.exit_code == 0, result.output
    # CSV header is the schema FIELDNAMES join.
    assert "date,narration,debit,credit,balance,reference,currency" in result.output


def test_file_to_file_json(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    runner = CliRunner()
    result = runner.invoke(main, ["palmpay", str(PALMPAY_SAMPLE), "-o", str(out), "-f", "json"])
    assert result.exit_code == 0, result.output
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["bank"] == "palmpay"


def test_missing_file_errors() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["palmpay", "/nonexistent.pdf", "-o", "-"])
    assert result.exit_code != 0
    assert "file not found" in result.output
