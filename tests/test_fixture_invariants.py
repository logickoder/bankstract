from datetime import time
from pathlib import Path
from typing import Literal

import pytest

import bankstract

_TESTS_ROOT = Path(__file__).parent

# none: date-only statement. all: every row timestamped. some: the parser falls
# back to date-only on rows that omit the time.
_Precision = Literal["none", "all", "some"]
_BANKS: dict[str, tuple[_Precision, list[str]]] = {
    "fbn": ("none", ["sample.pdf", "_local/statement.pdf"]),
    "zenith": ("none", ["sample.pdf", "_local/statement.pdf"]),
    "palmpay": ("some", ["sample.pdf", "_local/statement.pdf"]),
    "opay": (
        "all",
        ["sample.pdf", "sample.xlsx", "_local/statement.pdf", "_local/statement.xlsx"],
    ),
}


def _params() -> list[object]:
    params: list[object] = []
    for bank, (precision, rels) in _BANKS.items():
        for rel in rels:
            path = _TESTS_ROOT / bank / "fixtures" / rel
            marks = (
                [pytest.mark.skipif(not path.exists(), reason="raw fixture absent")]
                if rel.startswith("_local/")
                else []
            )
            params.append(pytest.param(bank, path, precision, id=f"{bank}-{rel}", marks=marks))
    return params


@pytest.mark.parametrize(("bank", "path", "precision"), _params())
def test_no_zero_amount_rows(bank: str, path: Path, precision: _Precision) -> None:
    # Informational lines (e.g. "balance brought forward") must not leak out as
    # transactions. If a new layout adds one, the parser should skip it.
    txs = bankstract.parse(path, bank=bank).transactions
    assert [i for i, t in enumerate(txs) if t.debit == 0 and t.credit == 0] == []


@pytest.mark.parametrize(("bank", "path", "precision"), _params())
def test_has_time_matches_bank_precision(bank: str, path: Path, precision: _Precision) -> None:
    txs = bankstract.parse(path, bank=bank).transactions
    flagged = [t.has_time for t in txs]
    assert all(t.date.time() == time(0, 0) for t in txs if not t.has_time)
    if precision == "none":
        assert not any(flagged)
    elif precision == "all":
        assert all(flagged)
    else:
        assert any(flagged)
