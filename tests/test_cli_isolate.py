"""`--isolate` on the parse commands: same bytes, and a worker that cannot finish exits 2."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from bankstract.cli import main

from ._forge import ZENITH


@pytest.mark.parametrize("command", [["zenith"], ["auto"]])
def test_isolated_output_matches_in_process(command: list[str]) -> None:
    args = [*command, str(ZENITH), "-o", "-"]
    plain = CliRunner().invoke(main, args)
    isolated = CliRunner().invoke(main, [*args, "--isolate"])
    assert isolated.exit_code == 0, isolated.output
    assert isolated.stdout_bytes == plain.stdout_bytes


@pytest.mark.parametrize("command", [["zenith"], ["auto"]])
def test_a_worker_that_cannot_finish_exits_two_with_no_output(command: list[str]) -> None:
    # Startup alone takes about 0.3s, so this limit cannot be met.
    args = [*command, str(ZENITH), "-o", "-", "--isolate", "--timeout", "0.05"]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error: Worker stopped after 0.05s.")


def test_auto_does_not_detect_in_the_parent_when_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    # detect() reads the file. Running it here would defeat the isolation.
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("detect() ran in the parent")

    monkeypatch.setattr("bankstract.cli.detect", fail)
    result = CliRunner().invoke(main, ["auto", str(ZENITH), "-o", "-", "--isolate"])
    assert result.exit_code == 0, result.output


def test_a_missing_file_is_still_a_clean_cli_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main, ["zenith", str(tmp_path / "nope.pdf"), "-o", "-", "--isolate"]
    )
    assert result.exit_code != 0
    assert "file not found" in result.output
