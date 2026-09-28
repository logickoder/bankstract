from functools import cache
from pathlib import Path

import pytest

import bankstract
from bankstract.schema import ParseResult, ReconciliationReport

TESTS_ROOT = Path(__file__).parent

# Every committed sample plus its gitignored raw counterpart, per bank. One
# table so a new bank or fixture lands in every cross-bank test at once.
FIXTURES: dict[str, list[str]] = {
    "fbn": ["sample.pdf", "_local/statement.pdf"],
    "zenith": ["sample.pdf", "_local/statement.pdf"],
    "palmpay": ["sample.pdf", "_local/statement.pdf"],
    "opay": ["sample.pdf", "sample.xlsx", "_local/statement.pdf", "_local/statement.xlsx"],
}


# What reconcile_result must report per bank. Shared by the cross-fixture
# test and each bank's own parser test.
RECONCILIATION: dict[str, ReconciliationReport] = {
    "fbn": ReconciliationReport(totals="passed", row_wise="passed"),
    "zenith": ReconciliationReport(totals="not_available", row_wise="passed"),
    "palmpay": ReconciliationReport(totals="passed", row_wise="not_available"),
    "opay": ReconciliationReport(totals="passed", row_wise="disabled"),
}


def fixture_params(*, committed_only: bool = False) -> list[object]:
    params: list[object] = []
    for bank, rels in FIXTURES.items():
        for rel in rels:
            if committed_only and rel.startswith("_local/"):
                continue
            path = TESTS_ROOT / bank / "fixtures" / rel
            marks = (
                [pytest.mark.skipif(not path.exists(), reason="raw fixture absent")]
                if rel.startswith("_local/")
                else []
            )
            params.append(pytest.param(bank, path, id=f"{bank}-{rel}", marks=marks))
    return params


# Fixture PDFs take 0.3-4s each to parse. Tests only read the result, so one
# parse per (bank, path) per session is safe.
@cache
def parsed(bank: str, path: Path) -> ParseResult:
    return bankstract.parse(path, bank=bank)
