"""
Session-scoped artifact emitter: for every registered parser, write the
parsed sample fixture + raw _local statement (when present) to
`tests/<bank>/fixtures/_local/<stem>.{csv,json}` so the owner can eyeball
output across all supported banks after any test run.

`_local/` is gitignored — these artifacts never leak into the repo. The
fixture runs once per pytest invocation regardless of test selection.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import bankstract
from bankstract.parsers import all_parsers
from bankstract.writers.csv import write_csv
from bankstract.writers.json import write_json

_TESTS_ROOT = Path(__file__).parent


@pytest.fixture(scope="session", autouse=True)
def _emit_local_artifacts() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    for bank in all_parsers():
        fixtures_dir = _TESTS_ROOT / bank / "fixtures"
        if not fixtures_dir.is_dir():
            continue
        local_dir = fixtures_dir / "_local"
        local_dir.mkdir(exist_ok=True)
        candidates: list[Path] = []
        for ext in ("pdf", "xlsx"):
            candidates.append(fixtures_dir / f"sample.{ext}")
            candidates.append(local_dir / f"statement.{ext}")
        for fixture in candidates:
            if not fixture.is_file():
                continue
            try:
                result = bankstract.parse(fixture, bank=bank)
            except Exception:
                # Don't fail the test session on a single bank's parse glitch;
                # the per-bank test will surface it with proper context.
                continue
            stem = f"{fixture.stem}.{fixture.suffix.lstrip('.')}"
            write_csv(result.transactions, local_dir / f"{stem}.csv")
            write_json(result, local_dir / f"{stem}.json")
    yield
