"""Run one call in a child process with a time limit and, where the OS allows,
a memory limit. A crafted PDF can cost gigabytes inside one mupdf call, and no
in-process code can interrupt that call. A child can be killed.

On Linux and macOS each child is forked from a server that already imported
bankstract, so a call costs about 0.02s once the server is up. A spawned child
re-imports the package and costs about 0.35s, which is what Windows gets."""

from __future__ import annotations

import importlib
import multiprocessing as mp
import pickle
import sys
import time
from collections.abc import Callable
from contextlib import nullcontext
from functools import cache
from io import BytesIO
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any, TypeVar

from ._progress import ProgressCallback, ProgressEvent, progress_scope
from ._source import Source, read_bytes
from .schema import ResourceLimitError

_T = TypeVar("_T")

# What every `isolate=True` entry point defaults to.
DEFAULT_TIMEOUT = 60.0
DEFAULT_MEMORY_MB = 2048

# Largest single message the parent will read from the child, a result or one
# event. recv() has no deadline once a message starts, so an unbounded one could
# hold the parent past its timeout. The biggest genuine result is a redacted
# copy of the input, never near this.
_MAX_MESSAGE = 512 * 1024 * 1024


def payload_of(source: Source) -> Path | bytes:
    """A source the child can open. A stream cannot cross the process boundary,
    so its bytes do. A path crosses as is and the child reads it."""
    return source if isinstance(source, Path) else read_bytes(source)


def source_of(payload: Path | bytes) -> Source:
    return BytesIO(payload) if isinstance(payload, bytes) else payload


@cache
def _context() -> Any:
    # Typed Any: typeshed has no ForkServerContext on Windows and names the pipe
    # class differently there, so one precise type fits neither platform.
    if sys.platform == "win32":
        return mp.get_context("spawn")
    ctx = mp.get_context("forkserver")
    # Set once, before the first child starts the server. The server imports the
    # package then, and every child forks from that warm state.
    ctx.set_forkserver_preload(["bankstract"])
    return ctx


def _apply_memory_limit(
    memory_mb: int | None, *, platform: str = sys.platform, res: Any = None
) -> None:
    """Cap the child's address space at `memory_mb`, or at the hard limit if that
    is lower, so a container's own limit cannot make the call fail. macOS refuses
    the cap and keeps the time limit alone. Anywhere else a refusal raises: a
    silent one would leave the call unbounded while the caller believes otherwise."""
    if not memory_mb or platform == "win32":
        return
    res = importlib.import_module("resource") if res is None else res
    limit = memory_mb * 1024 * 1024
    _, hard = res.getrlimit(res.RLIMIT_AS)
    if hard != res.RLIM_INFINITY:
        limit = min(limit, hard)
    try:
        res.setrlimit(res.RLIMIT_AS, (limit, limit))
    except (ValueError, OSError):
        if platform != "darwin":
            raise


def _child(
    conn: Connection,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    memory_mb: int | None,
    forward: bool,
) -> None:
    def send_event(event: ProgressEvent) -> None:
        conn.send(("progress", event))

    outcome: tuple[str, Any]
    try:
        _apply_memory_limit(memory_mb)
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


def _importable(path: str) -> bool:
    """Whether a child can re-import `__main__` from `path`: a file, or a module
    inside a zip archive. A Windows console script (`pytest.exe`,
    `bankstract.exe`) runs `__main__` from inside the .exe, which is a zip, so
    the path itself is not a file but a parent is."""
    p = Path(path)
    return p.exists() or any(parent.is_file() for parent in p.parents)


def _check_main_importable() -> None:
    """A child re-imports `__main__` from its file. A script piped on stdin names
    `<stdin>`, which does not exist, so the child would die and the caller would
    see only a crash. Say so before anything starts. `python -c`, a REPL and a
    notebook have no file and work."""
    path = getattr(sys.modules.get("__main__"), "__file__", None)
    if path and not _importable(path):
        raise RuntimeError(
            f"Cannot start a worker. This script ({path}) cannot be re-imported by a "
            'child process. Save it to a file and run that, under an `if __name__ == "__main__":` '
            "guard. Nothing was checked."
        )


def _ignore(_event: ProgressEvent) -> None:
    pass


def _next_message(
    receiver: Any, proc: BaseProcess, deadline: float, timeout: float
) -> tuple[str, Any]:
    """One message from the child: `("progress", event)`, `("ok", result)` or
    `("error", exception)`. Raises `ResourceLimitError` past the deadline, on a
    child that died, and on a message over the size cap."""
    # Check the deadline on its own. After it passes, poll(0) is True whenever the
    # pipe holds anything, so a child that keeps it full would never time out.
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not receiver.poll(remaining):
        raise ResourceLimitError(
            f"Worker stopped after {timeout:g}s. The file took longer than the limit "
            "to check. Treat it as untrusted, or raise the timeout for a file you trust."
        )
    try:
        message: tuple[str, Any] = pickle.loads(receiver.recv_bytes(_MAX_MESSAGE))  # noqa: S301
    except EOFError:
        proc.join(1)
        raise ResourceLimitError(
            f"Worker ended with exit code {proc.exitcode} and no result. It crashed, ran out "
            "of memory, or could not re-import your main script: run that from a file, under "
            'an `if __name__ == "__main__":` guard. Treat the file as untrusted.'
        ) from None
    except OSError as exc:
        if "bad message length" not in str(exc):
            raise
        raise ResourceLimitError(
            f"Worker sent back more than {_MAX_MESSAGE / 2**20:g} MB. The file produced "
            "a result too large to accept. Treat it as untrusted."
        ) from exc
    return message


def run_isolated(
    func: Callable[..., _T],
    *args: Any,
    timeout: float,
    memory_mb: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> _T:
    """Call `func(*args)` in a child process. Raises `ResourceLimitError` when
    the child passes `timeout` seconds, runs out of memory or dies without a
    result. An exception `func` raises is re-raised here. `memory_mb` is
    enforced on Linux only: macOS and Windows get the time limit alone.

    `on_progress` receives the child's progress events here, in order, as they
    happen. The timeout counts from the call, not from the last event. An
    exception `on_progress` raises stops the child and propagates."""
    _check_main_importable()
    ctx = _context()
    receiver, sender = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_child, args=(sender, func, args, memory_mb, on_progress is not None), daemon=True
    )
    deliver = on_progress or _ignore
    deadline = time.monotonic() + timeout
    proc.start()
    sender.close()
    try:
        kind, value = _next_message(receiver, proc, deadline, timeout)
        while kind == "progress":
            deliver(value)
            kind, value = _next_message(receiver, proc, deadline, timeout)
    finally:
        receiver.close()
        if proc.is_alive():
            proc.kill()
        proc.join(5)
    if kind == "error":
        if isinstance(value, MemoryError):
            # With no limit set the host itself ran out, so there is none to raise.
            advice = (
                f"The file needs more than {memory_mb} MB to check. Treat it as untrusted, "
                "or raise the memory limit for a file you trust."
                if memory_mb
                else "No limit was set, so the host ran out. Treat the file as untrusted."
            )
            raise ResourceLimitError(f"Worker ran out of memory. {advice}") from value
        raise value
    return value  # type: ignore[no-any-return]


def _call(fn: Callable[..., _T], payload: Path | bytes, kwargs: dict[str, Any]) -> _T:
    # `isolate` is not forwarded, so the child never isolates again.
    return fn(source_of(payload), **kwargs)


def run_isolated_call(
    fn: Callable[..., _T],
    source: Source,
    *,
    timeout: float,
    memory_mb: int | None,
    on_progress: ProgressCallback | None = None,
    **kwargs: Any,
) -> _T:
    """`fn(source, **kwargs)` in a child process: the shape every public entry
    point shares. `fn` crosses as a module-level name, `source` as a path or
    bytes. See `run_isolated` for the limits and the progress stream."""
    return run_isolated(
        _call,
        fn,
        payload_of(source),
        kwargs,
        timeout=timeout,
        memory_mb=memory_mb,
        on_progress=on_progress,
    )
