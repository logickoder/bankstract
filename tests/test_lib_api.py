from io import BytesIO
from pathlib import Path

import pytest

import bankstract

PALMPAY_SAMPLE = Path(__file__).parent / "palmpay" / "fixtures" / "sample.pdf"
FBN_SAMPLE = Path(__file__).parent / "fbn" / "fixtures" / "sample.pdf"
ZENITH_SAMPLE = Path(__file__).parent / "zenith" / "fixtures" / "sample.pdf"


def test_public_surface_exports() -> None:
    # Exact set: any addition or removal here is a semver-relevant change.
    assert set(bankstract.__all__) == {
        "Parser",
        "ParseError",
        "ParseResult",
        "ReconciliationError",
        "StatementMetadata",
        "Transaction",
        "__version__",
        "detect",
        "list_parsers",
        "parse",
    }


def test_list_parsers_returns_sorted() -> None:
    names = bankstract.list_parsers()
    assert names == sorted(names)
    assert "palmpay" in names
    assert "fbn" in names
    assert "zenith" in names


@pytest.mark.parametrize(
    "fixture,expected",
    [
        (PALMPAY_SAMPLE, "palmpay"),
        (FBN_SAMPLE, "fbn"),
        (ZENITH_SAMPLE, "zenith"),
    ],
)
def test_detect_picks_correct_parser(fixture: Path, expected: str) -> None:
    assert bankstract.detect(fixture) == expected
    assert bankstract.detect(str(fixture)) == expected


def test_parse_auto_detects() -> None:
    result = bankstract.parse(PALMPAY_SAMPLE)
    assert result.format_version == "palmpay-2026-01"
    assert result.metadata is not None and result.metadata.bank == "palmpay"
    assert len(result.transactions) > 0


def test_parse_with_explicit_bank() -> None:
    result = bankstract.parse(FBN_SAMPLE, bank="fbn")
    assert result.format_version == "fbn-2026-01"


def test_parse_accepts_bytesio() -> None:
    buf = BytesIO(ZENITH_SAMPLE.read_bytes())
    result = bankstract.parse(buf)
    assert result.metadata is not None and result.metadata.bank == "zenith"
    assert len(result.transactions) > 0


def test_parse_unknown_bank_raises() -> None:
    with pytest.raises(KeyError):
        bankstract.parse(PALMPAY_SAMPLE, bank="not-a-bank")


def test_parse_undetectable_raises(tmp_path: Path) -> None:
    not_a_statement = tmp_path / "junk.pdf"
    not_a_statement.write_bytes(b"%PDF-1.4\n%not really\n")
    with pytest.raises(bankstract.ParseError):
        bankstract.parse(not_a_statement)
