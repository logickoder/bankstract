import inspect
import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest

import bankstract

PALMPAY_SAMPLE = Path(__file__).parent / "palmpay" / "fixtures" / "sample.pdf"
FBN_SAMPLE = Path(__file__).parent / "fbn" / "fixtures" / "sample.pdf"
ZENITH_SAMPLE = Path(__file__).parent / "zenith" / "fixtures" / "sample.pdf"
OPAY_PDF = Path(__file__).parent / "opay" / "fixtures" / "sample.pdf"

_ALL_PDF_FIXTURES = [
    pytest.param(PALMPAY_SAMPLE, "palmpay", id="palmpay"),
    pytest.param(FBN_SAMPLE, "fbn", id="fbn"),
    pytest.param(ZENITH_SAMPLE, "zenith", id="zenith"),
    pytest.param(OPAY_PDF, "opay", id="opay"),
]


def test_public_surface_exports() -> None:
    # Exact set: any addition or removal here is a semver-relevant change.
    assert set(bankstract.__all__) == {
        "EmptyStatementError",
        "EncryptedSourceError",
        "Format",
        "LayoutDriftError",
        "Parser",
        "ParseError",
        "ParseResult",
        "ProgressCallback",
        "ProgressEvent",
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
        "parse_to",
        "redact",
        "throttle",
        "write_csv",
        "write_json",
    }


def test_parse_signature_unchanged() -> None:
    # Snapshot the public `parse` signature. Drift here is a semver event —
    # bump the expected string deliberately, never silently.
    assert str(inspect.signature(bankstract.parse)) == (
        "(source: 'SourceLike', *, bank: 'str | None' = None, "
        "progress_callback: 'ProgressCallback | None' = None) -> 'ParseResult'"
    )


def test_parse_to_csv_returns_bytes() -> None:
    data = bankstract.parse_to(PALMPAY_SAMPLE, format="csv")
    assert isinstance(data, bytes)
    assert len(data) > 0
    # Canonical CSV header is fixed; first line never drifts.
    assert data.startswith(b"date,narration,debit,credit,balance,reference,currency")


def test_parse_to_json_returns_bytes() -> None:
    data = bankstract.parse_to(ZENITH_SAMPLE, format="json")
    assert isinstance(data, bytes)
    payload = json.loads(data)
    assert "transactions" in payload
    assert len(payload["transactions"]) > 0
    assert payload["metadata"]["bank"] == "zenith"


def test_parse_to_default_format_is_csv() -> None:
    csv_bytes = bankstract.parse_to(PALMPAY_SAMPLE)
    explicit = bankstract.parse_to(PALMPAY_SAMPLE, format="csv")
    assert csv_bytes == explicit


@pytest.mark.parametrize("fixture,bank", _ALL_PDF_FIXTURES)
@pytest.mark.parametrize("fmt", ["csv", "json"])
def test_parse_to_byte_identical_to_cli(fixture: Path, bank: str, fmt: str) -> None:
    if not fixture.exists():
        pytest.skip(f"fixture absent: {fixture}")
    proc = subprocess.run(
        [sys.executable, "-m", "bankstract", bank, str(fixture), "-o", "-", "-f", fmt],
        capture_output=True,
        check=True,
    )
    lib_bytes = bankstract.parse_to(fixture, format=fmt, bank=bank)  # pyright: ignore[reportArgumentType]
    assert proc.stdout == lib_bytes, (
        f"CLI stdout diverged from parse_to bytes ({bank}/{fmt}). "
        f"CLI={len(proc.stdout)} lib={len(lib_bytes)}"
    )


def test_parse_to_line_endings_pinned_csv() -> None:
    data = bankstract.parse_to(PALMPAY_SAMPLE, format="csv")
    # csv module emits \r\n per RFC 4180. No double-translated \r\r\n must
    # leak through (Windows text-mode regression guard).
    assert b"\r\r\n" not in data
    assert b"\r\n" in data


def test_parse_to_utf8_roundtrip() -> None:
    # PalmPay narrations contain the Naira sign ₦ — verify utf-8 clean.
    data = bankstract.parse_to(PALMPAY_SAMPLE, format="json")
    decoded = data.decode("utf-8")
    assert json.loads(decoded)  # round-trips


def test_parse_to_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="unsupported output format"):
        bankstract.parse_to(PALMPAY_SAMPLE, format="xml")  # pyright: ignore[reportArgumentType]


def test_parse_to_reconcile_false_skips_invariant() -> None:
    # Build a tiny synthetic ParseResult that would fail row-wise reconcile,
    # patch parse() to return it, ensure reconcile=False skips the check.
    from decimal import Decimal

    from bankstract.schema import ParseResult, Transaction

    bad = ParseResult(
        transactions=[
            Transaction(
                date=__import__("datetime").datetime(2026, 1, 1),
                narration="open",
                balance=Decimal("100"),
            ),
            Transaction(
                date=__import__("datetime").datetime(2026, 1, 2),
                narration="bad",
                debit=Decimal("50"),
                balance=Decimal("999"),  # invariant break: expect 50
            ),
        ],
        format_version="synthetic",
        row_wise_reconcilable=True,
    )

    import bankstract._api as api

    orig = api.parse
    api.parse = lambda *_a, **_k: bad  # type: ignore[assignment]
    try:
        with pytest.raises(bankstract.ReconciliationError):
            bankstract.parse_to(PALMPAY_SAMPLE, reconcile=True)
        # reconcile=False bypasses the invariant — returns bytes despite the break.
        data = bankstract.parse_to(PALMPAY_SAMPLE, reconcile=False)
        assert b"bad" in data
    finally:
        api.parse = orig


def test_parse_to_writes_no_tempfiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    before = set(tmp_path.iterdir())
    bankstract.parse_to(PALMPAY_SAMPLE, format="csv")
    after = set(tmp_path.iterdir())
    assert before == after, f"leaked files: {after - before}"


def test_parse_to_empty_result_csv_has_header_only() -> None:
    # Synthetic empty ParseResult should serialize to header-only CSV — not a
    # zero-byte payload. Critical: silent zero-byte writes look like
    # parser success to downstream pipelines.
    from bankstract.schema import ParseResult

    empty = ParseResult(transactions=[], format_version="empty")

    import bankstract._api as api

    orig = api.parse
    api.parse = lambda *_a, **_k: empty  # type: ignore[assignment]
    try:
        data = bankstract.parse_to(PALMPAY_SAMPLE, format="csv")
        assert data == b"date,narration,debit,credit,balance,reference,currency\r\n"
    finally:
        api.parse = orig


def test_parse_to_empty_result_json_has_empty_transactions() -> None:
    from bankstract.schema import ParseResult

    empty = ParseResult(transactions=[], format_version="empty")

    import bankstract._api as api

    orig = api.parse
    api.parse = lambda *_a, **_k: empty  # type: ignore[assignment]
    try:
        data = bankstract.parse_to(PALMPAY_SAMPLE, format="json")
        payload = json.loads(data)
        assert payload["transactions"] == []
        assert payload["format_version"] == "empty"
    finally:
        api.parse = orig


def test_write_csv_public_export() -> None:
    # `bankstract.write_csv` is a re-export of the internal writer — byte
    # output must match the internal call exactly.
    from io import StringIO

    from bankstract.writers.csv import write_csv as _internal

    result = bankstract.parse(PALMPAY_SAMPLE)
    a, b = StringIO(), StringIO()
    bankstract.write_csv(result.transactions, a)
    _internal(result.transactions, b)
    assert a.getvalue() == b.getvalue()


def test_write_json_public_export() -> None:
    from io import StringIO

    from bankstract.writers.json import write_json as _internal

    result = bankstract.parse(PALMPAY_SAMPLE)
    a, b = StringIO(), StringIO()
    bankstract.write_json(result, a)
    _internal(result, b)
    assert a.getvalue() == b.getvalue()


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
