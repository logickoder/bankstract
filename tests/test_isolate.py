"""Isolation: a child process the parent can kill."""

import operator
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from bankstract._isolate import run_isolated
from bankstract._pymupdf import new_doc
from bankstract.integrity import inspect
from bankstract.schema import EncryptedSourceError, ResourceLimitError

from ._fixtures import parsed
from ._forge import ZENITH


def _hog() -> int:
    return len(bytearray(1024 * 1024 * 1024))


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
        run_isolated(_hog, timeout=60, memory_mb=300)


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
    doc: Any = new_doc()
    doc.new_page()
    locked = tmp_path / "locked.pdf"
    doc.save(str(locked), encryption=3, user_pw="x", owner_pw="y")
    doc.close()
    with pytest.raises(EncryptedSourceError):
        inspect(locked, bank="zenith", isolate=True)


def _form_page(tmp_path: Path, runs: int) -> Path:
    """A page of 62 bytes that invokes a form holding `runs` text runs. The
    content-size gate reads the page stream only, so it never trips."""
    body = b"\n".join(
        b"BT /helv 6 Tf %d %d Td (x) Tj ET" % (10 + i % 500, 10 + (i // 500) % 700)
        for i in range(runs)
    )
    doc: Any = new_doc()
    page = doc.new_page()
    page.insert_text((10, 10), "a", fontsize=6)
    font = page.get_fonts()[0][0]
    form = doc.get_new_xref()
    doc.update_object(
        form,
        f"<< /Type /XObject /Subtype /Form /BBox [0 0 612 842] "
        f"/Resources << /Font << /helv {font} 0 R >> >> >>",
    )
    doc.update_stream(form, body)
    doc.xref_set_key(
        page.xref, "Resources", f"<< /Font << /helv {font} 0 R >> /XObject << /Fm0 {form} 0 R >> >>"
    )
    xref = page.get_contents()[0]
    doc.update_stream(xref, doc.xref_stream(xref) + b"\nq /Fm0 Do Q\n")
    out = tmp_path / "form.pdf"
    doc.save(str(out))
    doc.close()
    return out


def test_a_runaway_form_page_is_cut_off_not_read(tmp_path: Path) -> None:
    # 100k runs in a form take about 4s and 180 MB to extract in process, and the
    # size gate cannot see them. Isolated, the worker is killed at the limit.
    crafted = _form_page(tmp_path, 100_000)
    start = time.perf_counter()
    with pytest.raises(ResourceLimitError, match="stopped after 1s"):
        inspect(crafted, bank="zenith", isolate=True, timeout=1)
    assert time.perf_counter() - start < 15
