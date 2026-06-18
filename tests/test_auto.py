"""detect_confidence ranking — a parser scoring higher must win over one
that also detects but with lower confidence."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import bankstract
from bankstract._pdfplumber import PdfSource
from bankstract.parsers import _REGISTRY, get, register
from bankstract.parsers.base import Parser
from bankstract.schema import ParseResult

PALMPAY_SAMPLE = Path(__file__).parent / "palmpay" / "fixtures" / "sample.pdf"

_DUMMY_BANK = "_dummy_always"


class _DummyAlwaysParser(Parser):
    bank = _DUMMY_BANK

    def __init__(self, score: float) -> None:
        self._score = score

    def detect(self, source: PdfSource) -> bool:
        del source
        return True

    def detect_confidence(self, source: PdfSource) -> float:
        del source
        return self._score

    def parse(self, source: PdfSource) -> ParseResult:
        del source
        return ParseResult(transactions=[], format_version="dummy")


@pytest.fixture(autouse=True)
def _cleanup_dummy() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    _REGISTRY.pop(_DUMMY_BANK, None)


def test_higher_confidence_wins() -> None:
    register(_DummyAlwaysParser(score=2.0))
    assert bankstract.detect(PALMPAY_SAMPLE) == _DUMMY_BANK


def test_lower_confidence_loses() -> None:
    register(_DummyAlwaysParser(score=0.1))
    assert bankstract.detect(PALMPAY_SAMPLE) == "palmpay"


def test_zero_confidence_returns_none(tmp_path: Path) -> None:
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"%PDF-1.4\nnot real")
    assert bankstract.detect(junk) is None


def test_default_detect_confidence_mirrors_detect() -> None:
    """Verify the ABC default: 1.0 if detect() else 0.0."""
    parser = get("palmpay")
    assert parser.detect_confidence(PALMPAY_SAMPLE) == 1.0
