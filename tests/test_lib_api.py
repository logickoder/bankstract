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
        "Format",
        "Parser",
        "ParseError",
        "ParseResult",
        "ReconciliationError",
        "RedactReport",
        "RedactResult",
        "Redactor",
        "StatementMetadata",
        "Transaction",
        "__version__",
        "detect",
        "list_parsers",
        "list_redactors",
        "parse",
        "redact",
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


def test_list_redactors_returns_sorted() -> None:
    names = bankstract.list_redactors()
    assert names == sorted(names)
    assert "palmpay" in names
    assert "fbn" in names
    assert "zenith" in names
    assert "opay" in names


@pytest.mark.parametrize(
    "fixture,expected_format",
    [
        (PALMPAY_SAMPLE, "pdf"),
        (FBN_SAMPLE, "pdf"),
        (ZENITH_SAMPLE, "pdf"),
    ],
)
def test_redact_returns_in_memory_bytes(fixture: Path, expected_format: str) -> None:
    result = bankstract.redact(fixture)
    assert isinstance(result.data, bytes)
    assert len(result.data) > 0
    assert result.format == expected_format
    assert result.bank in bankstract.list_redactors()
    assert result.report.redactions > 0


def test_redact_explicit_bank() -> None:
    result = bankstract.redact(PALMPAY_SAMPLE, bank="palmpay")
    assert result.bank == "palmpay"
    assert result.format_version.startswith("palmpay")


def test_redact_bytesio_roundtrip() -> None:
    buf = BytesIO(PALMPAY_SAMPLE.read_bytes())
    result = bankstract.redact(buf)
    assert result.bank == "palmpay"
    assert isinstance(result.data, bytes)


def test_redact_writes_no_tempfiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # If a redactor leaks a tempfile, it'll appear here. Point Python's
    # default tempdir at tmp_path so any sneaky NamedTemporaryFile lands
    # somewhere we can audit.
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    before = set(tmp_path.iterdir())
    result = bankstract.redact(PALMPAY_SAMPLE)
    after = set(tmp_path.iterdir())
    assert before == after, f"leaked files: {after - before}"
    assert isinstance(result.data, bytes)


def test_redact_undetectable_raises(tmp_path: Path) -> None:
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"%PDF-1.4\n%not really\n")
    with pytest.raises(bankstract.ParseError):
        bankstract.redact(junk)


def test_redact_unknown_bank_raises() -> None:
    with pytest.raises(KeyError):
        bankstract.redact(PALMPAY_SAMPLE, bank="not-a-bank")
