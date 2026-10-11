"""`bankstract inspect`: report JSON on stdout, signals on stderr, exit 2 on error."""

import json
from pathlib import Path

from click.testing import CliRunner

from bankstract._pymupdf import open_doc
from bankstract.cli import main

from ._forge import ZENITH, append_revision, balance_span, retype, sample


def test_clean_statement_exits_zero() -> None:
    result = CliRunner().invoke(main, ["inspect", str(ZENITH)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["bank"] == "zenith"
    assert payload["clean"] is True
    assert payload["signals"] == []


def test_incremental_save_exits_two(tmp_path: Path) -> None:
    forged = tmp_path / "forged.pdf"
    append_revision(ZENITH, forged)

    result = CliRunner().invoke(main, ["inspect", str(forged), "--bank", "zenith"])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["clean"] is False
    assert [s["code"] for s in payload["signals"]] == ["incremental_update"]
    assert "error: incremental_update" in result.stderr


def test_warning_alone_exits_zero() -> None:
    result = CliRunner().invoke(main, ["inspect", str(sample("opay", "xlsx"))])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["signals"][0]["severity"] == "warn"


def test_stdin_is_read() -> None:
    result = CliRunner().invoke(main, ["inspect", "-"], input=ZENITH.read_bytes())
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["clean"] is True


def test_stderr_carries_no_statement_text(tmp_path: Path) -> None:
    # `detail` quotes amounts. stdout is the caller's own output. stderr is
    # where logs collect, so it gets code and position only.
    span = balance_span()
    forged = tmp_path / "forged.pdf"
    doc = open_doc(ZENITH)
    retype(doc, span, fontsize=9)
    doc.save(str(forged))
    doc.close()

    result = CliRunner().invoke(main, ["inspect", str(forged), "--bank", "zenith"])
    assert result.exit_code == 2
    details = " ".join(s["detail"] for s in json.loads(result.stdout)["signals"])
    assert "9,999.00" in details
    assert "9,999.00" not in result.stderr
    assert span.text.strip() not in result.stderr
    lines = result.stderr.strip().splitlines()
    assert lines[0].startswith("error: reconciliation_failed (row ")
    assert "warn: font_size_outlier (page 1)" in lines


def test_isolated_run_matches_in_process() -> None:
    plain = CliRunner().invoke(main, ["inspect", str(ZENITH)])
    isolated = CliRunner().invoke(main, ["inspect", str(ZENITH), "--isolate"])
    assert isolated.exit_code == 0, isolated.output
    assert json.loads(isolated.stdout) == json.loads(plain.stdout)


def test_a_worker_that_cannot_finish_exits_two_with_no_report() -> None:
    # Forking a warm worker takes about 0.02s and the parse takes longer, so this
    # limit cannot be met.
    result = CliRunner().invoke(main, ["inspect", str(ZENITH), "--isolate", "--timeout", "0.01"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error: Worker stopped after 0.01s.")
