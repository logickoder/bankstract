"""
Session-scoped artifact emitter: for every fixture in `_fixtures.FIXTURES`,
write the parsed sample + raw _local statement (when present) to
`tests/<bank>/fixtures/_local/<stem>.{csv,json}` so the owner can eyeball
output across all supported banks after any test run.

`_local/` is gitignored — these artifacts never leak into the repo. The
fixture runs once per pytest invocation regardless of test selection.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from bankstract.writers.csv import write_csv
from bankstract.writers.json import write_json

from ._fixtures import FIXTURES, TESTS_ROOT, parsed


@pytest.fixture(scope="session", autouse=True)
def _emit_local_artifacts() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    for bank, rels in FIXTURES.items():
        for rel in rels:
            fixture = TESTS_ROOT / bank / "fixtures" / rel
            if not fixture.is_file():
                continue
            try:
                result = parsed(bank, fixture)
            except Exception:
                # Don't fail the test session on a single bank's parse glitch;
                # the per-bank test will surface it with proper context.
                continue
            local_dir = fixture.parent if rel.startswith("_local/") else fixture.parent / "_local"
            local_dir.mkdir(exist_ok=True)
            stem = f"{fixture.stem}.{fixture.suffix.lstrip('.')}"
            write_csv(result.transactions, local_dir / f"{stem}.csv")
            write_json(result, local_dir / f"{stem}.json")
    yield
