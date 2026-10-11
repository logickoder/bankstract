"""Run one call in a child process with a time limit and, where the OS allows,
a memory limit. A crafted PDF can cost gigabytes inside one mupdf call, and no
in-process code can interrupt that call. A child can be killed."""

from __future__ import annotations

import multiprocessing as mp
import sys
import time
from collections.abc import Callable
from contextlib import nullcontext
from io import BytesIO
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, TypeVar

from ._progress import ProgressCallback, ProgressEvent, progress_scope
from ._source import Source, rewind
from .schema import ResourceLimitError

if sys.platform != "win32":
    import resource

_T = TypeVar("_T")

# What every `isolate=True` entry point defaults to.
DEFAULT_TIMEOUT = 60.0
DEFAULT_MEMORY_MB = 2048


def payload_of(source: Source) -> Path | bytes:
    """A source the child can open. A stream cannot cross the process boundary,
    so its bytes do. A path crosses as is and the child reads it."""
    if isinstance(source, Path):
        return source
    rewind(source)
    return source.read()


def source_of(payload: Path | bytes) -> Source:
    return BytesIO(payload) if isinstance(payload, bytes) else payload


def _child(
    conn: Connection,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    limit: int,
    forward: bool,
) -> None:
    def send_event(event: ProgressEvent) -> None:
        conn.send(("progress", event))

    outcome: tuple[str, Any]
    try:
        if limit and sys.platform != "win32":
            try:
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            except (ValueError, OSError):
                # macOS refuses the limit. The time limit still holds.
                pass
        # The scope makes the child fire the events, `done` included, that an
        # in-process call would. `func` is called with no callback of its own.
        with progress_scope(send_event) if forward else nullcontext():
            outcome = ("ok", func(*args))
    except BaseException as exc:  # noqa: BLE001 - the parent re-raises it
        outcome = ("error", exc)
    try:
        conn.send(outcome)
    except Exception as exc:  # noqa: BLE001 - result or exception would not pickle
        conn.send(("error", RuntimeError(f"worker result could not be returned: {exc!r}")))
    finally:
        conn.close()


def run_isolated(
    func: Callable[..., _T],
    *args: Any,
    timeout: float,
    memory_mb: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> _T:
    """Call `func(*args)` in a spawned child. Raises `ResourceLimitError` when
    the child passes `timeout` seconds, runs out of memory or dies without a
    result. An exception `func` raises is re-raised here. `memory_mb` is
    enforced on Linux only: macOS and Windows get the time limit alone.

    `on_progress` receives the child's progress events here, in order, as they
    happen. The timeout counts from the call, not from the last event. An
    exception `on_progress` raises stops the child and propagates."""
    ctx = mp.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    limit = memory_mb * 1024 * 1024 if memory_mb else 0
    proc = ctx.Process(
        target=_child, args=(sender, func, args, limit, on_progress is not None), daemon=True
    )
    deadline = time.monotonic() + timeout
    proc.start()
    sender.close()
    try:
        while True:
            if not receiver.poll(max(0.0, deadline - time.monotonic())):
                raise ResourceLimitError(
                    f"Worker stopped after {timeout:g}s. The file took longer than the limit "
                    "to check. Treat it as untrusted, or raise the timeout for a file you trust."
                )
            try:
                kind, value = receiver.recv()
            except EOFError:
                proc.join(1)
                raise ResourceLimitError(
                    f"Worker ended with exit code {proc.exitcode} and no result. It crashed or "
                    "ran out of memory. Treat the file as untrusted."
                ) from None
            if kind != "progress":
                break
            if on_progress is not None:
                on_progress(value)
    finally:
        receiver.close()
        if proc.is_alive():
            proc.kill()
        proc.join(5)
    if kind == "error":
        if isinstance(value, MemoryError):
            raise ResourceLimitError(
                f"Worker ran out of memory. The file needs more than {memory_mb} MB to "
                "check. Treat it as untrusted, or raise the memory limit for a file you trust."
            ) from value
        raise value
    return value  # type: ignore[no-any-return]
