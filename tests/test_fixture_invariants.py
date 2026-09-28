from datetime import time
from pathlib import Path
from typing import Literal

import pytest

from ._fixtures import fixture_params, parsed

# none: date-only statement. all: every row timestamped. some: the parser falls
# back to date-only on rows that omit the time.
_Precision = Literal["none", "all", "some"]
_PRECISION: dict[str, _Precision] = {
    "fbn": "none",
    "zenith": "none",
    "opay": "all",
    "palmpay": "some",
}


@pytest.mark.parametrize(("bank", "path"), fixture_params())
def test_no_zero_amount_rows(bank: str, path: Path) -> None:
    # Informational lines (e.g. "balance brought forward") must not leak out as
    # transactions. If a new layout adds one, the parser should skip it.
    txs = parsed(bank, path).transactions
    assert [i for i, t in enumerate(txs) if t.debit == 0 and t.credit == 0] == []


@pytest.mark.parametrize(("bank", "path"), fixture_params())
def test_has_time_matches_bank_precision(bank: str, path: Path) -> None:
    precision = _PRECISION[bank]
    txs = parsed(bank, path).transactions
    flagged = [t.has_time for t in txs]
    assert all(t.date.time() == time(0, 0) for t in txs if not t.has_time)
    if precision == "none":
        assert not any(flagged)
    elif precision == "all":
        assert all(flagged)
    else:
        assert any(flagged)


@pytest.mark.parametrize(("bank", "path"), fixture_params())
def test_parser_leaves_reconciliation_unset(bank: str, path: Path) -> None:
    # Only reconcile_result may set it. A parser-set value would make the JSON
    # claim checks that never ran.
    assert parsed(bank, path).reconciliation is None
