"""Isolation: a child process the parent can kill."""

import operator
import os
import sys
import time
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from bankstract import convert, detect, parse, redact
from bankstract._isolate import (  # pyright: ignore[reportPrivateUsage]
    _apply_memory_limit,
    _context,
    _importable,
    payload_of,
    run_isolated,
    source_of,
)
from bankstract._progress import ProgressEvent, emit
from bankstract.integrity import inspect
from bankstract.schema import (
    EncryptedSourceError,
    ParseError,
    ReconciliationError,
    ResourceLimitError,
)

from ._fixtures import parsed
from ._forge import ZENITH, blank_pdf, forged_balance_pdf, form_page, locked_pdf


def _raise_memory_error() -> None:
    raise MemoryError


def _hog() -> int:
    return len(bytearray(3 * 1024 * 1024 * 1024))


def test_workers_fork_from_a_warm_server_where_the_os_has_one() -> None:
    # A spawned child re-imports the package and costs about 0.35s. A forked one
    # costs about 0.02s. Windows has no fork server and spawns.
    assert _context().get_start_method() == ("spawn" if sys.platform == "win32" else "forkserver")


def test_returns_the_result() -> None:
    assert run_isolated(operator.add, 2, 3, timeout=30) == 5


def test_reraises_what_the_call_raises() -> None:
    with pytest.raises(ValueError, match="invalid literal"):
        run_isolated(int, "x", timeout=30)


def test_kills_a_worker_past_the_timeout() -> None:
    start = time.perf_counter()
    with pytest.raises(ResourceLimitError, match=r"stopped after 1s"):
        run_isolated(time.sleep, 60, timeout=1)
    assert time.perf_counter() - start < 15


def test_a_worker_that_dies_is_not_a_result() -> None:
    with pytest.raises(ResourceLimitError, match=r"exit code 3 and no result"):
        run_isolated(os._exit, 3, timeout=30)


@pytest.mark.skipif(sys.platform != "linux", reason="macOS refuses RLIMIT_AS")
def test_memory_limit_kills_a_hog() -> None:
    with pytest.raises(ResourceLimitError, match="out of memory"):
        run_isolated(_hog, timeout=60, memory_mb=1024)


@pytest.mark.skipif(sys.platform != "linux", reason="macOS refuses RLIMIT_AS")
def test_a_small_job_runs_under_a_real_memory_limit() -> None:
    # The child holds pymupdf and pdfplumber before it starts. A limit below that
    # would kill every call, and the hog test above would pass for the wrong reason.
    assert len(run_isolated(_return_big, 1_000_000, timeout=30, memory_mb=1024)) == 1_000_000


def test_isolated_inspect_matches_in_process() -> None:
    assert inspect(ZENITH, bank="zenith", isolate=True) == inspect(ZENITH, bank="zenith")


def test_isolated_inspect_reads_a_stream() -> None:
    report = inspect(BytesIO(ZENITH.read_bytes()), isolate=True)
    assert report.bank == "zenith"
    assert report.clean


def test_isolated_inspect_takes_a_parsed_result() -> None:
    result = parsed("zenith", ZENITH)
    assert inspect(ZENITH, result=result, isolate=True).clean


def test_errors_cross_the_process_boundary() -> None:
    with pytest.raises(ValueError, match="does not match the result's bank"):
        inspect(ZENITH, bank="fbn", result=parsed("zenith", ZENITH), isolate=True)


def test_encrypted_source_still_raises_when_isolated(tmp_path: Path) -> None:
    with pytest.raises(EncryptedSourceError):
        inspect(locked_pdf(tmp_path), bank="zenith", isolate=True)


def test_isolated_parse_matches_in_process() -> None:
    assert parse(ZENITH, bank="zenith", isolate=True) == parse(ZENITH, bank="zenith")


def test_a_stream_crosses_as_bytes_and_a_path_as_itself() -> None:
    # The stream branch is the same for every entry point, so one spawned test
    # (inspect, above) covers it and the rest need no worker.
    data = ZENITH.read_bytes()
    midway = BytesIO(data)
    midway.read(10)
    assert payload_of(midway) == data  # read from the start, not the cursor
    restored = source_of(payload_of(BytesIO(data)))
    assert isinstance(restored, BytesIO)
    assert restored.read() == data
    assert payload_of(ZENITH) is ZENITH
    assert source_of(ZENITH) is ZENITH


@pytest.mark.parametrize("fmt", ["csv", "json"])
def test_isolated_convert_is_byte_identical(fmt: Any) -> None:
    assert convert(ZENITH, format=fmt, isolate=True) == convert(ZENITH, format=fmt)


def test_parse_errors_keep_their_attributes_across_the_boundary(tmp_path: Path) -> None:
    blank = blank_pdf(tmp_path)
    with pytest.raises(ParseError) as plain:
        parse(blank, bank="zenith")
    with pytest.raises(ParseError) as isolated:
        parse(blank, bank="zenith", isolate=True)
    assert type(isolated.value) is type(plain.value)
    assert isolated.value.bank == plain.value.bank == "zenith"
    assert isolated.value.format_version == plain.value.format_version
    assert str(isolated.value) == str(plain.value)


def test_reconciliation_errors_keep_their_attributes_across_the_boundary(tmp_path: Path) -> None:
    forged = forged_balance_pdf(tmp_path)
    with pytest.raises(ReconciliationError) as plain:
        convert(forged)
    with pytest.raises(ReconciliationError) as isolated:
        convert(forged, isolate=True)
    assert plain.value.row_index is not None
    assert isolated.value.row_index == plain.value.row_index
    assert isolated.value.bank == plain.value.bank == "zenith"
    assert isolated.value.format_version == plain.value.format_version
    assert str(isolated.value) == str(plain.value)


def test_a_resource_limit_is_not_a_parse_error() -> None:
    # `except ParseError` skips files the parser cannot read. A file that stopped
    # the checker must not be skipped with them.
    assert not issubclass(ResourceLimitError, ParseError)
    assert issubclass(ResourceLimitError, Exception)


def test_isolated_detect_matches_in_process() -> None:
    assert detect(ZENITH, isolate=True) == detect(ZENITH) == "zenith"


def test_isolated_redact_matches_in_process() -> None:
    # Redacted bytes differ from run to run, so compare the report and the rows.
    plain = redact(ZENITH, bank="zenith")
    isolated = redact(ZENITH, bank="zenith", isolate=True)
    assert isolated.report == plain.report
    assert (isolated.bank, isolated.format_version) == (plain.bank, plain.format_version)
    assert (
        parse(BytesIO(isolated.data), bank="zenith").transactions
        == parse(BytesIO(plain.data), bank="zenith").transactions
    )


# Jobs for the streaming tests. They run in the child, so they live at module level.
def _emit_slowly() -> str:
    for i in (1, 2, 3):
        emit("step", i, 3)
        time.sleep(0.3)
    return "finished"


def _emit_forever() -> None:
    i = 0
    while True:
        i += 1
        emit("step", i, 10**9)
        time.sleep(0.1)


def _emit_flood() -> None:
    # No sleep: events arrive faster than the parent can handle them.
    while True:
        emit("step", 1, 10**9)


def _return_big(size: int) -> bytes:
    return b"x" * size


def _emit_then_touch(marker: str) -> None:
    emit("step", 1, 2)
    time.sleep(0.5)
    Path(marker).touch()


@pytest.mark.parametrize("call", [parse, convert, redact], ids=["parse", "convert", "redact"])
def test_isolated_progress_matches_in_process(call: Any) -> None:
    plain: list[ProgressEvent] = []
    isolated: list[ProgressEvent] = []
    call(ZENITH, bank="zenith", progress_callback=plain.append)
    call(ZENITH, bank="zenith", progress_callback=isolated.append, isolate=True)
    assert plain, "the in-process call fired no events"
    assert isolated == plain
    assert [e.stage for e in isolated].count("done") == 1
    assert isolated[-1].stage == "done"


def test_events_arrive_while_the_worker_is_still_running() -> None:
    arrivals: list[float] = []
    start = time.perf_counter()
    result = run_isolated(
        _emit_slowly, timeout=60, on_progress=lambda _e: arrivals.append(time.perf_counter())
    )
    finished = time.perf_counter()
    assert result == "finished"
    # Three events 0.3s apart, then the result. Buffered until the end they would
    # all land within a few milliseconds of `finished`.
    assert len(arrivals) == 4  # three steps and `done`
    assert finished - arrivals[0] > 0.5
    assert arrivals[0] - start < finished - start - 0.5


def test_the_timeout_holds_while_events_keep_arriving() -> None:
    events: list[ProgressEvent] = []
    start = time.perf_counter()
    with pytest.raises(ResourceLimitError, match="stopped after 1s"):
        run_isolated(_emit_forever, timeout=1, on_progress=events.append)
    assert time.perf_counter() - start < 10
    assert len(events) >= 3  # the stream was live, and it still ended at the limit


def test_a_flood_of_events_cannot_outrun_the_timeout() -> None:
    # Past the deadline poll(0) is True whenever the pipe holds anything, so a child
    # that keeps it full used to hold the parent forever.
    events: list[ProgressEvent] = []
    start = time.perf_counter()
    with pytest.raises(ResourceLimitError, match="stopped after 1s"):
        run_isolated(_emit_flood, timeout=1, on_progress=events.append)
    assert time.perf_counter() - start < 10
    assert len(events) > 100  # it really was a flood


def test_a_result_over_the_size_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bankstract._isolate._MAX_MESSAGE", 1_000_000)
    with pytest.raises(ResourceLimitError, match="a result too large to accept"):
        run_isolated(_return_big, 5_000_000, timeout=30)


def test_a_result_under_the_size_cap_comes_back() -> None:
    assert len(run_isolated(_return_big, 2_000_000, timeout=30)) == 2_000_000


def test_a_callback_that_raises_kills_the_worker(tmp_path: Path) -> None:
    marker = tmp_path / "worker-survived"

    def boom(_event: ProgressEvent) -> None:
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        run_isolated(_emit_then_touch, str(marker), timeout=60, on_progress=boom)
    # A live worker would touch the marker 0.5s after its event.
    time.sleep(1.0)
    assert not marker.exists()


@pytest.fixture(scope="module")
def runaway_page(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # 100k runs in a form take about 4s and 180 MB to extract in process, and the
    # size gate cannot see them. Built once: five tests share it.
    return form_page(tmp_path_factory.mktemp("runaway"), 100_000)


RUNAWAY_CALLS: dict[str, Callable[[Path], object]] = {
    "inspect": lambda p: inspect(p, bank="zenith", isolate=True, timeout=1),
    "parse": lambda p: parse(p, bank="zenith", isolate=True, timeout=1),
    "convert": lambda p: convert(p, bank="zenith", isolate=True, timeout=1),
    "detect": lambda p: detect(p, isolate=True, timeout=1),
}
# Not redact: it does not walk a form's text, so this page costs it 0.85s, not the
# 10s parse and convert pay or the 21s detect pays. Its worker is the same one.


@pytest.mark.parametrize("call", RUNAWAY_CALLS.values(), ids=RUNAWAY_CALLS.keys())
def test_a_runaway_page_is_cut_off_not_read(
    call: Callable[[Path], object], runaway_page: Path
) -> None:
    start = time.perf_counter()
    with pytest.raises(ResourceLimitError, match="stopped after 1s"):
        call(runaway_page)
    assert time.perf_counter() - start < 15


ENTRY_POINTS = [parse, convert, detect, redact]
ENTRY_IDS = ["parse", "convert", "detect", "redact"]


@pytest.mark.parametrize("call", ENTRY_POINTS, ids=ENTRY_IDS)
def test_isolate_true_hands_the_call_to_a_worker(
    call: Callable[..., object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def spy(*_args: Any, **_kwargs: Any) -> str:
        return "ran in a worker"

    monkeypatch.setattr("bankstract._api.run_isolated_call", spy)
    assert call(ZENITH, isolate=True) == "ran in a worker"


@pytest.mark.parametrize("call", ENTRY_POINTS, ids=ENTRY_IDS)
def test_isolate_false_never_starts_a_worker(
    call: Callable[..., object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a worker started without isolate=True")

    monkeypatch.setattr("bankstract._api.run_isolated_call", fail)
    call(ZENITH)


def test_the_out_of_memory_message_does_not_blame_a_limit_that_was_not_set() -> None:
    with pytest.raises(ResourceLimitError) as unset:
        run_isolated(_raise_memory_error, timeout=30, memory_mb=None)
    assert "None" not in str(unset.value)
    assert "raise the memory limit" not in str(unset.value)
    with pytest.raises(ResourceLimitError) as capped:
        run_isolated(_raise_memory_error, timeout=30, memory_mb=512)
    assert "more than 512 MB" in str(capped.value)


class _FakeResource:
    """Stands in for `resource` so the limit logic runs on any platform."""

    RLIMIT_AS = 9
    RLIM_INFINITY = -1

    def __init__(self, hard: int, *, refuse: bool = False) -> None:
        self.hard = hard
        self.refuse = refuse
        self.set_to: tuple[int, int] | None = None

    def getrlimit(self, _which: int) -> tuple[int, int]:
        return (self.hard, self.hard)

    def setrlimit(self, _which: int, limits: tuple[int, int]) -> None:
        if self.refuse:
            raise ValueError("current limit exceeds maximum limit")
        self.set_to = limits


def test_a_limit_above_the_hard_limit_is_clamped_to_it() -> None:
    fake = _FakeResource(hard=500 * 1024 * 1024)
    _apply_memory_limit(2048, platform="linux", res=fake)
    assert fake.set_to == (500 * 1024 * 1024, 500 * 1024 * 1024)


def test_an_unlimited_hard_limit_leaves_the_requested_one() -> None:
    fake = _FakeResource(hard=_FakeResource.RLIM_INFINITY)
    _apply_memory_limit(2048, platform="linux", res=fake)
    assert fake.set_to == (2048 * 1024 * 1024, 2048 * 1024 * 1024)


def test_macos_may_refuse_the_limit_and_the_time_limit_still_holds() -> None:
    _apply_memory_limit(2048, platform="darwin", res=_FakeResource(hard=-1, refuse=True))


def test_linux_refusing_the_limit_is_loud_not_silently_unbounded() -> None:
    with pytest.raises(ValueError, match="exceeds maximum"):
        _apply_memory_limit(2048, platform="linux", res=_FakeResource(hard=-1, refuse=True))


def test_no_memory_limit_asked_for_means_none_is_set() -> None:
    fake = _FakeResource(hard=-1)
    _apply_memory_limit(None, platform="linux", res=fake)
    _apply_memory_limit(0, platform="linux", res=fake)
    assert fake.set_to is None


def test_a_script_that_cannot_be_re_imported_is_refused_before_a_worker_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A script piped on stdin names a main file that does not exist. The child would
    # die and the caller would see a crash. Say what is wrong, and start nothing.
    def no_worker() -> None:
        raise AssertionError("a worker was started")

    monkeypatch.setattr(sys.modules["__main__"], "__file__", "<stdin>", raising=False)
    monkeypatch.setattr("bankstract._isolate._context", no_worker)
    with pytest.raises(RuntimeError, match=r"\(<stdin>\) cannot be re-imported"):
        run_isolated(operator.add, 1, 2, timeout=30)


def test_a_main_with_no_file_still_runs_a_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    # `python -c`, a REPL and a notebook have no main file.
    monkeypatch.delattr(sys.modules["__main__"], "__file__", raising=False)
    assert run_isolated(operator.add, 1, 2, timeout=30) == 3


def test_a_main_inside_a_zip_archive_is_importable(tmp_path: Path) -> None:
    # A Windows console script runs `__main__` from inside the .exe, a zip. The
    # path is not a file, but its parent is, and a child can import it.
    archive = tmp_path / "tool.exe"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("__main__.py", "")
    assert _importable(str(archive / "__main__.py"))


def test_a_real_file_is_importable(tmp_path: Path) -> None:
    script = tmp_path / "run.py"
    script.write_text("")
    assert _importable(str(script))


@pytest.mark.parametrize("name", ["<stdin>", "missing.py"])
def test_a_name_with_no_file_or_archive_behind_it_is_not(tmp_path: Path, name: str) -> None:
    assert not _importable(name)
    assert not _importable(str(tmp_path / name))
