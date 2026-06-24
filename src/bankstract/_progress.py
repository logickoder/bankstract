"""
Progress hooks. Engine fires lifecycle events through `emit()`; consumers
opt into them via the `progress_callback` kwarg on `parse / parse_to /
redact`. Callback delivery is contextvar-scoped so concurrent calls don't
cross-contaminate and parsers stay free of the kwarg.

Stage strings (`ProgressEvent.stage`) are intentionally `str`, not Enum or
Literal — adding new stages later is non-breaking. Documented stages today:

    detect       — fires once from `_api` post-detect (current=1, total=1)
    open         — fires once from `_api` post-open (current=1, total=1)
    extract_page — fires N times from `_common.extract_words_per_page`
    walk_page    — fires N times from each parser's outer page loop
    reconcile    — fires once from `_api.parse_to` post-reconcile
    redact_page  — fires N times from `redactors/base.Redactor.redact`
    done         — fires once before the function returns successfully

Engine `emit()` does no deduplication. Consumers that want a throttled UI
stream (CLI bar, browser SSE) wrap their callback in `throttle()` before
passing it in; consumers that want every event (Cloud telemetry) pass the
raw callback.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    current: int
    total: int


ProgressCallback = Callable[[ProgressEvent], None]


_callback: ContextVar[ProgressCallback | None] = ContextVar(
    "bankstract_progress_callback", default=None
)


def emit(stage: str, current: int, total: int) -> None:
    """Fire a ProgressEvent to the contextvar-scoped callback, if any.
    Zero-overhead path when no callback is set (one contextvar get + None
    check)."""
    cb = _callback.get()
    if cb is not None:
        cb(ProgressEvent(stage, current, total))


@contextmanager
def progress_scope(callback: ProgressCallback | None) -> Generator[None]:
    """Install `callback` for the duration of the `with` block. Resets on
    exit (success or exception) so contextvar state never leaks between
    `_api` calls or threads.

    `callback=None` is a no-op (does NOT clobber an outer scope's callback).
    This lets `parse_to()` set the scope once and call `parse()` without
    suppressing events on the inner call."""
    if callback is None:
        yield
        return
    token: Token[ProgressCallback | None] = _callback.set(callback)
    try:
        yield
    finally:
        _callback.reset(token)


def throttle(
    callback: ProgressCallback,
    *,
    min_interval_ms: int = 100,
) -> ProgressCallback:
    """Wrap `callback` so rapid-fire same-stage events are dropped.

    Rules:
    - Same (stage, current) as last fire → drop unless terminal.
    - Less than `min_interval_ms` since last same-stage fire → drop unless
      terminal or stage transition.
    - Terminal (current >= total) and stage-transition events always fire,
      so consumers see start-of-stage + end-of-stage even on a busy stream.

    For CLI bars; Cloud telemetry should use the raw callback."""
    last: dict[str, tuple[float, int]] = {}
    seen_stage: list[str] = []

    def wrapped(ev: ProgressEvent) -> None:
        now_ms = time.monotonic() * 1000
        terminal = ev.current >= ev.total
        stage_changed = not seen_stage or seen_stage[0] != ev.stage
        prev = last.get(ev.stage)

        if prev is not None and prev[1] == ev.current and not terminal:
            return
        if not (terminal or stage_changed):
            if prev is not None and (now_ms - prev[0]) < min_interval_ms:
                return

        last[ev.stage] = (now_ms, ev.current)
        if stage_changed:
            seen_stage[:] = [ev.stage]
        callback(ev)

    return wrapped
