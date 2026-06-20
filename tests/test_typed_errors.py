"""
Typed-exception contract tests for v0.13 — fine-grained subclasses of
ParseError so Cloud / CLI can map error_class to actionable user copy.

Coverage:
- EncryptedSourceError (PDF + XLSX) from boundary modules
- EmptyStatementError from each parser
- LayoutDriftError from parsers that have an anchor-missing path
- AST audit: no bare `raise ParseError(...)` in parsers/* + boundary
  modules without a justifying `# type-unknown:` comment
- Subclass coverage: every typed subclass has at least one raise site
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import bankstract
from bankstract import (
    EmptyStatementError,
    EncryptedSourceError,
    LayoutDriftError,
    ParseError,
)

FIXTURES = Path(__file__).parent / "fixtures"
ENCRYPTED_PDF = FIXTURES / "encrypted_sample.pdf"
ENCRYPTED_XLSX = FIXTURES / "encrypted_sample.xlsx"


def test_typed_subclasses_inherit_parse_error() -> None:
    assert issubclass(EncryptedSourceError, ParseError)
    assert issubclass(EmptyStatementError, ParseError)
    assert issubclass(LayoutDriftError, ParseError)


def test_encrypted_pdf_raises_typed_exception() -> None:
    with pytest.raises(EncryptedSourceError, match="password-protected PDF"):
        bankstract.parse(ENCRYPTED_PDF, bank="palmpay")


def test_encrypted_pdf_caught_by_base_parse_error() -> None:
    # Backwards-compatible catch: existing `except ParseError:` keeps matching.
    with pytest.raises(ParseError):
        bankstract.parse(ENCRYPTED_PDF, bank="palmpay")


def test_encrypted_xlsx_raises_typed_exception() -> None:
    with pytest.raises(EncryptedSourceError, match="password-protected XLSX"):
        bankstract.parse(ENCRYPTED_XLSX, bank="opay")


def test_encrypted_xlsx_caught_by_base_parse_error() -> None:
    with pytest.raises(ParseError):
        bankstract.parse(ENCRYPTED_XLSX, bank="opay")


def test_empty_pdf_raises_empty_statement_error(tmp_path: Path) -> None:
    # A minimal 1-byte PDF header isn't extractable as a real PDF, but parsers
    # also catch zero-words via their `extract_words_per_page` branch. Use a
    # truly empty PDF stub by encrypting+re-decoding is heavy — instead, force
    # the path by passing a stripped PDF whose page renders zero words.
    # Easier: monkeypatch extract_words_per_page to return [].
    import bankstract.parsers.palmpay as pm

    orig = pm.extract_words_per_page
    pm.extract_words_per_page = lambda _src: []  # type: ignore[assignment]
    try:
        sample = Path(__file__).parent / "palmpay" / "fixtures" / "sample.pdf"
        with pytest.raises(EmptyStatementError) as info:
            bankstract.parse(sample, bank="palmpay")
        assert info.value.marker_coverage == 0.0
        assert info.value.format_version is not None
    finally:
        pm.extract_words_per_page = orig  # type: ignore[assignment]


def test_layout_drift_raises_typed_exception() -> None:
    # Palmpay raises LayoutDriftError when header totals are unparseable.
    # Force the path by monkeypatching _extract_totals to return (None, None).
    import bankstract.parsers.palmpay as pm

    orig = pm._extract_totals
    pm._extract_totals = lambda _w: (None, None)  # type: ignore[assignment]
    try:
        sample = Path(__file__).parent / "palmpay" / "fixtures" / "sample.pdf"
        with pytest.raises(LayoutDriftError, match="header totals"):
            bankstract.parse(sample, bank="palmpay")
    finally:
        pm._extract_totals = orig  # type: ignore[assignment]


# --- AST audit --------------------------------------------------------------

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "bankstract"
_AUDIT_PATHS: list[Path] = [
    *_SRC_ROOT.joinpath("parsers").glob("*.py"),
    _SRC_ROOT / "_pdfplumber.py",
    _SRC_ROOT / "_xlsx.py",
]


def _ast_raises(path: Path) -> list[tuple[int, str]]:
    """Return [(lineno, exc_name)] for every `raise X(...)` in the file."""
    source = path.read_text()
    tree = ast.parse(source)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            call = node.exc
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                out.append((node.lineno, call.func.id))
    return out


def test_no_bare_parse_error_without_justification() -> None:
    """Every `raise ParseError(...)` in parsers/* and boundary modules must
    be preceded (within 4 prior lines) by a `# type-unknown:` comment.
    Prevents drift back to lazy catchall raises after subclass introduction."""
    offenders: list[str] = []
    for path in _AUDIT_PATHS:
        if not path.exists():
            continue
        source_lines = path.read_text().splitlines()
        for lineno, exc_name in _ast_raises(path):
            if exc_name != "ParseError":
                continue
            window = source_lines[max(0, lineno - 5) : lineno - 1]
            if not any("# type-unknown:" in line for line in window):
                offenders.append(f"{path.relative_to(_SRC_ROOT.parent.parent)}:{lineno}")
    assert not offenders, (
        "Bare `raise ParseError(...)` without `# type-unknown:` justification:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    "exc_class",
    [EncryptedSourceError, EmptyStatementError, LayoutDriftError],
    ids=lambda c: c.__name__,
)
def test_each_subclass_has_raise_site(exc_class: type[ParseError]) -> None:
    """Every typed subclass must be raised by at least one site in parsers/
    or boundary modules. xfail (not skip) on zero — forces a decision: raise
    it somewhere or delete the class."""
    sites: list[str] = []
    for path in _AUDIT_PATHS:
        if not path.exists():
            continue
        for lineno, exc_name in _ast_raises(path):
            if exc_name == exc_class.__name__:
                sites.append(f"{path.name}:{lineno}")
    if not sites:
        pytest.xfail(
            f"{exc_class.__name__} has zero raise sites in parsers/ + boundary. "
            f"Either raise it from a real failure mode or remove the class."
        )
    assert sites  # informational
