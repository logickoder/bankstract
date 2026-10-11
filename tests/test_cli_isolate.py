"""`--isolate` on the parse commands: same bytes, and a worker that cannot finish exits 2."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from bankstract._progress import ProgressEvent
from bankstract.cli import main

from ._forge import ZENITH, blank_pdf


@pytest.mark.parametrize("command", [["zenith"], ["auto"]])
def test_isolated_output_matches_in_process(command: list[str]) -> None:
    args = [*command, str(ZENITH), "-o", "-"]
    plain = CliRunner().invoke(main, args)
    isolated = CliRunner().invoke(main, [*args, "--isolate"])
    assert isolated.exit_code == 0, isolated.output
    assert isolated.stdout_bytes == plain.stdout_bytes


@pytest.mark.parametrize("command", [["zenith"], ["auto"]])
def test_a_worker_that_cannot_finish_exits_two_with_no_output(command: list[str]) -> None:
    # Forking a warm worker takes about 0.02s and the parse takes longer, so this
    # limit cannot be met.
    args = [*command, str(ZENITH), "-o", "-", "--isolate", "--timeout", "0.01"]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error: Worker stopped after 0.01s.")


def test_auto_detects_in_a_worker_when_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    # detect() reads the file, so an isolated auto must hand it to a worker.
    seen: dict[str, object] = {}

    def spy(source: object, **kwargs: object) -> str:
        seen.update(kwargs)
        return "zenith"

    monkeypatch.setattr("bankstract.cli.detect", spy)
    result = CliRunner().invoke(main, ["auto", str(ZENITH), "-o", "-", "--isolate"])
    assert result.exit_code == 0, result.output
    assert seen["isolate"] is True
    assert "detected: zenith" in result.stderr


def test_auto_says_the_same_thing_isolated_or_not_when_nothing_matches(tmp_path: Path) -> None:
    blank = blank_pdf(tmp_path)
    plain = CliRunner().invoke(main, ["auto", str(blank), "-o", "-"])
    isolated = CliRunner().invoke(main, ["auto", str(blank), "-o", "-", "--isolate"])
    assert plain.exit_code == isolated.exit_code != 0
    assert plain.stderr == isolated.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["zenith", str(ZENITH), "-o", "-"],
        ["auto", str(ZENITH), "-o", "-"],
        ["inspect", str(ZENITH)],
        ["redact", "zenith", str(ZENITH), "-"],
    ],
    ids=["bank", "auto", "inspect", "redact"],
)
def test_timeout_without_isolate_is_refused_not_ignored(args: list[str]) -> None:
    # Nothing enforces a limit without --isolate, so a --timeout would only mislead.
    result = CliRunner().invoke(main, [*args, "--timeout", "5"])
    assert result.exit_code == 1
    assert "--timeout needs --isolate" in result.stderr
    assert result.stdout == ""


def test_a_missing_file_is_still_a_clean_cli_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main, ["zenith", str(tmp_path / "nope.pdf"), "-o", "-", "--isolate"]
    )
    assert result.exit_code != 0
    assert "file not found" in result.output


def test_isolated_redact_writes_the_same_report(tmp_path: Path) -> None:
    plain_out, isolated_out = tmp_path / "plain.pdf", tmp_path / "isolated.pdf"
    plain = CliRunner().invoke(main, ["redact", "zenith", str(ZENITH), str(plain_out), "-q"])
    isolated = CliRunner().invoke(
        main, ["redact", "zenith", str(ZENITH), str(isolated_out), "--isolate"]
    )
    assert isolated.exit_code == 0, isolated.output
    assert isolated_out.stat().st_size > 0
    assert isolated.stderr == plain.stderr


def test_a_redact_worker_that_cannot_finish_exits_two_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    args = ["redact", "zenith", str(ZENITH), str(out), "--isolate", "--timeout", "0.01"]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 2
    assert result.stderr.startswith("error: Worker stopped after 0.01s.")
    assert not out.exists()


@pytest.mark.parametrize(
    "args",
    [["zenith", str(ZENITH), "-o", "-"], ["redact", "zenith", str(ZENITH), "-"]],
    ids=["parse", "redact"],
)
def test_the_progress_bar_works_under_isolate(
    args: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[ProgressEvent] = []
    monkeypatch.setattr("bankstract.cli._progress_callback", lambda quiet: events.append)
    result = CliRunner().invoke(main, [*args, "--isolate"])
    assert result.exit_code == 0, result.output
    assert events
    assert events[-1].stage == "done"
