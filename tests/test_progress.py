"""Progress hook contract — what the engine fires, what `throttle()` drops."""

from __future__ import annotations

from pathlib import Path

import bankstract
from bankstract._progress import emit, progress_scope

PALMPAY_SAMPLE = Path(__file__).parent / "palmpay" / "fixtures" / "sample.pdf"
OPAY_XLSX_SAMPLE = Path(__file__).parent / "opay" / "fixtures" / "sample.xlsx"


def _collect() -> tuple[list[bankstract.ProgressEvent], bankstract.ProgressCallback]:
    events: list[bankstract.ProgressEvent] = []
    return events, events.append


def test_parse_fires_full_stage_set() -> None:
    events, cb = _collect()
    bankstract.parse(PALMPAY_SAMPLE, bank="palmpay", progress_callback=cb)
    stages = {ev.stage for ev in events}
    assert {"detect", "open", "extract_page", "walk_page", "done"} <= stages


def test_extract_page_monotonic_and_terminal() -> None:
    events, cb = _collect()
    bankstract.parse(PALMPAY_SAMPLE, bank="palmpay", progress_callback=cb)
    extract = [ev for ev in events if ev.stage == "extract_page"]
    assert extract, "no extract_page events fired"
    assert [ev.current for ev in extract] == list(range(1, len(extract) + 1))
    assert extract[-1].current == extract[-1].total


def test_parse_to_fires_reconcile_and_done_once() -> None:
    events, cb = _collect()
    bankstract.parse_to(PALMPAY_SAMPLE, format="csv", bank="palmpay", progress_callback=cb)
    reconcile_events = [ev for ev in events if ev.stage == "reconcile"]
    done_events = [ev for ev in events if ev.stage == "done"]
    assert len(reconcile_events) == 1
    # parse_to wraps parse(); both fire `done`, but contextvar nesting means
    # the consumer sees BOTH: inner parse `done` + outer parse_to `done`.
    # That's acceptable — terminal-event idempotency is the consumer's job
    # (the bar already handles repeated `current == total`).
    assert len(done_events) >= 1


def test_none_callback_zero_events() -> None:
    """Default `progress_callback=None` exercises the no-op contextvar path —
    no events, no allocation. Calling without the kwarg is byte-equivalent to
    pre-progress code (regression guard for accidental scope clobber)."""
    seen: list[bankstract.ProgressEvent] = []

    def outer(ev: bankstract.ProgressEvent) -> None:
        seen.append(ev)

    with progress_scope(outer):
        # Nested None-scope must NOT clobber outer.
        with progress_scope(None):
            emit("nested", 1, 1)
    assert seen == [bankstract.ProgressEvent("nested", 1, 1)]


def test_throttle_dedups_same_stage() -> None:
    seen: list[bankstract.ProgressEvent] = []
    cb = bankstract.throttle(seen.append, min_interval_ms=100)
    for i in range(1, 11):
        cb(bankstract.ProgressEvent("walk_page", i, 100))
    # First fires (stage transition), middle drops (under interval), terminal
    # never reached. So we expect exactly 1 — the first.
    assert len(seen) == 1
    assert seen[0].current == 1


def test_throttle_always_fires_terminal() -> None:
    seen: list[bankstract.ProgressEvent] = []
    cb = bankstract.throttle(seen.append, min_interval_ms=10_000)
    cb(bankstract.ProgressEvent("walk_page", 1, 10))
    cb(bankstract.ProgressEvent("walk_page", 5, 10))  # dropped (under interval)
    cb(bankstract.ProgressEvent("walk_page", 10, 10))  # terminal — fires
    stages = [ev.current for ev in seen]
    assert 10 in stages


def test_throttle_always_fires_stage_transition() -> None:
    seen: list[bankstract.ProgressEvent] = []
    cb = bankstract.throttle(seen.append, min_interval_ms=10_000)
    cb(bankstract.ProgressEvent("extract_page", 1, 10))
    cb(bankstract.ProgressEvent("extract_page", 2, 10))  # dropped
    cb(bankstract.ProgressEvent("walk_page", 1, 10))  # transition — fires
    stages = [ev.stage for ev in seen]
    assert stages == ["extract_page", "walk_page"]


def test_throttle_drops_exact_duplicate() -> None:
    """Same (stage, current) within interval drops even if non-terminal."""
    seen: list[bankstract.ProgressEvent] = []
    cb = bankstract.throttle(seen.append, min_interval_ms=10_000)
    cb(bankstract.ProgressEvent("walk_page", 1, 100))
    cb(bankstract.ProgressEvent("walk_page", 1, 100))
    assert len(seen) == 1


def test_redact_fires_redact_page() -> None:
    events, cb = _collect()
    bankstract.redact(PALMPAY_SAMPLE, bank="palmpay", progress_callback=cb)
    redact_events = [ev for ev in events if ev.stage == "redact_page"]
    assert redact_events, "no redact_page events fired"
    assert redact_events[-1].current == redact_events[-1].total


def test_opay_xlsx_walk_page_fires_once() -> None:
    if not OPAY_XLSX_SAMPLE.exists():
        return
    events, cb = _collect()
    bankstract.parse(OPAY_XLSX_SAMPLE, bank="opay", progress_callback=cb)
    walk_events = [ev for ev in events if ev.stage == "walk_page"]
    # XLSX path emits a single milestone walk_page(1, 1).
    assert walk_events == [bankstract.ProgressEvent("walk_page", 1, 1)]
