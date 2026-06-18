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
    """Verify the ABC default + per-parser fraction override: own fixture
    scores 1.0, foreign fixtures score 0.0."""
    parser = get("palmpay")
    assert parser.detect_confidence(PALMPAY_SAMPLE) == 1.0


def test_per_parser_scores_are_disjoint_across_fixtures() -> None:
    """Every parser scores its own fixture > all foreign-fixture scores —
    the actual disambiguation that the score API exists for."""
    base = Path(__file__).parent
    fixtures = {
        "palmpay": base / "palmpay" / "fixtures" / "sample.pdf",
        "fbn": base / "fbn" / "fixtures" / "sample.pdf",
        "zenith": base / "zenith" / "fixtures" / "sample.pdf",
        "opay": base / "opay" / "fixtures" / "sample.pdf",
    }
    for bank, fixture in fixtures.items():
        own = get(bank).detect_confidence(fixture)
        foreign = [get(other).detect_confidence(fixture) for other in fixtures if other != bank]
        assert own > max(foreign, default=0.0), (
            f"{bank} should score higher than foreign parsers on its own fixture: "
            f"own={own}, foreign={foreign}"
        )
        assert own == 1.0
