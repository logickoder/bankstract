import inspect
import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from typing import get_args

import pytest

import bankstract
from bankstract import OutputFormat

from ._fixtures import fixture_params, parsed

PALMPAY_SAMPLE = Path(__file__).parent / "palmpay" / "fixtures" / "sample.pdf"
FBN_SAMPLE = Path(__file__).parent / "fbn" / "fixtures" / "sample.pdf"
ZENITH_SAMPLE = Path(__file__).parent / "zenith" / "fixtures" / "sample.pdf"

# Committed samples only: CI must run the CLI byte-identity contract without
# raw fixtures, and every bank + format in FIXTURES joins it automatically.
_SAMPLES = fixture_params(committed_only=True)


def test_public_surface_exports() -> None:
    # Exact set: any addition or removal here is a semver-relevant change.
    assert set(bankstract.__all__) == {
        "CheckStatus",
        "EmptyStatementError",
        "EncryptedSourceError",
        "Format",
        "LayoutDriftError",
        "OutputFormat",
        "Parser",
        "ParseError",
        "ParseResult",
        "ReconciledParseResult",
        "ProgressCallback",
        "ProgressEvent",
        "ReconciliationError",
        "ReconciliationReport",
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
        "convert",
        "reconcile_result",
        "redact",
        "serialize",
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


def test_convert_csv_returns_bytes() -> None:
    data = bankstract.convert(PALMPAY_SAMPLE, format="csv")
    assert isinstance(data, bytes)
    assert len(data) > 0
    # Canonical CSV header is fixed; first line never drifts.
    assert data.startswith(b"date,narration,debit,credit,balance,reference,currency,has_time\r\n")


def test_convert_csv_has_time_column() -> None:
    # fbn prints date only. Every row must say so instead of passing the
    # padded 00:00:00 off as a real time.
    rows = bankstract.convert(FBN_SAMPLE, format="csv").decode().splitlines()[1:]
    assert rows
    assert all(row.endswith(",false") for row in rows)


def test_convert_json_returns_bytes() -> None:
    data = bankstract.convert(ZENITH_SAMPLE, format="json")
    assert isinstance(data, bytes)
    payload = json.loads(data)
    assert "transactions" in payload
    assert len(payload["transactions"]) > 0
    assert payload["metadata"]["bank"] == "zenith"
    assert "reconciliation" in payload


@pytest.mark.parametrize("fmt", get_args(OutputFormat))
def test_serialize_matches_convert(fmt: OutputFormat) -> None:
    # convert() is parse + reconcile_result + serialize. Doing the steps by
    # hand must give the same bytes.
    result = bankstract.reconcile_result(parsed("zenith", ZENITH_SAMPLE))
    assert bankstract.serialize(result, fmt) == bankstract.convert(
        ZENITH_SAMPLE, format=fmt, bank="zenith"
    )


def test_parse_sets_bank_when_detected() -> None:
    assert bankstract.parse(ZENITH_SAMPLE).bank == "zenith"


def test_parse_error_carries_matched_bank() -> None:
    # Forcing the wrong parser fails inside a matched parser, so the error
    # names it.
    with pytest.raises(bankstract.ParseError) as info:
        bankstract.parse(ZENITH_SAMPLE, bank="palmpay")
    assert info.value.bank == "palmpay"


def test_serialize_unknown_format_raises() -> None:
    result = parsed("zenith", ZENITH_SAMPLE)
    with pytest.raises(ValueError, match="unsupported output format"):
        bankstract.serialize(result, "xml")  # pyright: ignore[reportArgumentType]


def test_convert_json_omits_reconciliation_when_skipped() -> None:
    payload = json.loads(bankstract.convert(ZENITH_SAMPLE, format="json", reconcile=False))
    assert "reconciliation" not in payload


def test_convert_default_format_is_csv() -> None:
    csv_bytes = bankstract.convert(PALMPAY_SAMPLE)
    explicit = bankstract.convert(PALMPAY_SAMPLE, format="csv")
    assert csv_bytes == explicit


@pytest.mark.parametrize(("bank", "fixture"), _SAMPLES)
@pytest.mark.parametrize("fmt", get_args(OutputFormat))
def test_convert_byte_identical_to_cli(bank: str, fixture: Path, fmt: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "bankstract", bank, str(fixture), "-o", "-", "-f", fmt],
        capture_output=True,
        check=True,
    )
    lib_bytes = bankstract.convert(fixture, format=fmt, bank=bank)  # pyright: ignore[reportArgumentType]
    assert proc.stdout == lib_bytes, (
        f"CLI stdout diverged from convert bytes ({bank}/{fmt}). "
        f"CLI={len(proc.stdout)} lib={len(lib_bytes)}"
    )


def test_convert_line_endings_pinned_csv() -> None:
    data = bankstract.convert(PALMPAY_SAMPLE, format="csv")
    # csv module emits \r\n per RFC 4180. No double-translated \r\r\n must
    # leak through (Windows text-mode regression guard).
    assert b"\r\r\n" not in data
    assert b"\r\n" in data


def test_convert_utf8_roundtrip() -> None:
    # PalmPay narrations contain the Naira sign ₦ — verify utf-8 clean.
    data = bankstract.convert(PALMPAY_SAMPLE, format="json")
    decoded = data.decode("utf-8")
    assert json.loads(decoded)  # round-trips


def test_convert_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="unsupported output format"):
        bankstract.convert(PALMPAY_SAMPLE, format="xml")  # pyright: ignore[reportArgumentType]


def test_convert_reconcile_false_skips_invariant() -> None:
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
    )

    import bankstract._api as api

    orig = api.parse
    api.parse = lambda *_a, **_k: bad  # type: ignore[assignment]
    try:
        with pytest.raises(bankstract.ReconciliationError):
            bankstract.convert(PALMPAY_SAMPLE, reconcile=True)
        # reconcile=False bypasses the invariant — returns bytes despite the break.
        data = bankstract.convert(PALMPAY_SAMPLE, reconcile=False)
        assert b"bad" in data
    finally:
        api.parse = orig


def test_convert_writes_no_tempfiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    before = set(tmp_path.iterdir())
    bankstract.convert(PALMPAY_SAMPLE, format="csv")
    after = set(tmp_path.iterdir())
    assert before == after, f"leaked files: {after - before}"


def test_convert_empty_result_csv_has_header_only() -> None:
    # Synthetic empty ParseResult should serialize to header-only CSV — not a
    # zero-byte payload. Critical: silent zero-byte writes look like
    # parser success to downstream pipelines. reconcile=False because an empty
    # result carries no evidence and would raise before serializing.
    from bankstract.schema import ParseResult

    empty = ParseResult(transactions=[], format_version="empty")

    import bankstract._api as api

    orig = api.parse
    api.parse = lambda *_a, **_k: empty  # type: ignore[assignment]
    try:
        data = bankstract.convert(PALMPAY_SAMPLE, format="csv", reconcile=False)
        assert data == b"date,narration,debit,credit,balance,reference,currency,has_time\r\n"
    finally:
        api.parse = orig


def test_convert_empty_result_json_has_empty_transactions() -> None:
    from bankstract.schema import ParseResult

    empty = ParseResult(transactions=[], format_version="empty")

    import bankstract._api as api

    orig = api.parse
    api.parse = lambda *_a, **_k: empty  # type: ignore[assignment]
    try:
        data = bankstract.convert(PALMPAY_SAMPLE, format="json", reconcile=False)
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


@pytest.mark.parametrize(("expected", "fixture"), _SAMPLES)
def test_detect_picks_correct_parser(expected: str, fixture: Path) -> None:
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
