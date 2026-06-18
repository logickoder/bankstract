# bankstract

Convert Nigerian bank PDF statements into structured CSV. Plugin architecture — one parser per bank.

```bash
pip install bankstract

bankstract palmpay statement.pdf -o out.csv
bankstract auto unknown.pdf -o out.csv
bankstract list
```

## Status

| Bank       | Status        |
| ---------- | ------------- |
| PalmPay    | v0.7 — alpha  |
| First Bank | v0.7 — alpha  |
| Zenith     | v0.7 — alpha  |

## Install

```bash
pip install bankstract
```

Optional extras:

```bash
pip install "bankstract[ocr]"      # pytesseract for scanned PDFs
pip install "bankstract[camelot]"  # camelot lattice fallback
```

## Develop

Project uses [uv](https://docs.astral.sh/uv/) for dependency + venv management.

```bash
uv sync --all-extras       # create .venv, install deps + extras from uv.lock
uv run pre-commit install  # one-time: enable the pre-commit hook
uv run pytest              # run tests
uv run ruff check src tests
uv run pyright src tests   # strict type check (see CLAUDE.md directive 8)
uv run bankstract list     # invoke CLI
```

Add a dependency with `uv add <pkg>` (dev: `uv add --dev <pkg>`). Commit `uv.lock`.

The pre-commit hook runs `ruff check`, `ruff format --check`, `pyright` (strict), and `pytest` before every commit. Bypass only in genuine emergencies with `git commit --no-verify`; the same checks run again in CI.

### Releasing

CI publishes to PyPI automatically on push to `main` via `.github/workflows/publish.yml`. The workflow runs the full gate (ruff + pyright + pytest), and if the current `pyproject.toml` version already exists on PyPI it auto-bumps the minor component and commits the bump before publishing. PyPI auth uses OIDC trusted publishing — no token in repo or CI secrets.

To prepare a release locally:

```bash
scripts/bump-version.sh                 # patch bump
scripts/bump-version.sh minor           # 0.2.x -> 0.3.0
scripts/bump-version.sh major           # 0.x.x -> 1.0.0
scripts/bump-version.sh 0.3.0           # exact set
uv build                                # dist/*.whl + dist/*.tar.gz
uv publish dist/*                       # only if not using the GH workflow; needs --token or UV_PUBLISH_TOKEN
```

Trusted-publisher setup (one-time, owner only): create a publisher at <https://pypi.org/manage/account/publishing/> with workflow `publish.yml`, repo `logickoder/bankstract`.

## Usage

```bash
bankstract <bank> <pdf> -o <out>               # explicit parser
bankstract auto <pdf> -o <out>                 # auto-detect via Parser.detect_confidence()
bankstract list                                # show registered parsers
bankstract <bank> <pdf> -o out.json -f json    # JSON instead of CSV
cat statement.pdf | bankstract auto - -o -     # stdin / stdout pipeline
```

Pass `-` as the PDF arg to read from stdin, or `-` to `-o` to write to stdout. When stdout is the data sink, informational messages go to stderr so the data stream stays clean.

Unparseable blocks are written to a `.log` sidecar next to the output file.

## Python API

```python
import bankstract

bankstract.list_parsers()           # ['fbn', 'palmpay', 'zenith']
bankstract.detect("statement.pdf")  # 'palmpay' | None

result = bankstract.parse("statement.pdf")            # auto-detect
result = bankstract.parse(fp, bank="fbn")             # explicit; fp is BytesIO

result.metadata.account_holder
result.metadata.statement_period_start
result.transactions[0].balance
result.format_version
```

### Public surface (semver-locked)

Only the names re-exported from `bankstract` are part of the semver contract:

| Name                  | Kind          | Purpose                                             |
| --------------------- | ------------- | --------------------------------------------------- |
| `parse`               | function      | `parse(source, *, bank=None) -> ParseResult`        |
| `detect`              | function      | `detect(source) -> str \| None` (max-score bank)    |
| `list_parsers`        | function      | sorted bank names                                   |
| `Parser`              | ABC           | base class for new parsers                          |
| `Transaction`         | pydantic      | row schema                                          |
| `StatementMetadata`   | dataclass     | account holder / period / opening + closing balance |
| `ParseResult`         | dataclass     | `transactions[]`, totals, `format_version`, metadata |
| `ParseError`          | exception     | layout mismatch                                     |
| `ReconciliationError` | exception     | invariant break                                     |
| `__version__`         | str           | package version                                     |

`source` accepts `pathlib.Path`, a string path (treated as a path), or a seekable binary stream (e.g. `io.BytesIO`). Auto-detection picks the parser with the highest `detect_confidence` score — ties resolve to registration order. Anything imported from a submodule prefixed with `_` (`bankstract._api`, `bankstract._pdfplumber`, `bankstract._layout`) is internal and may change in any release.

## Reconciliation invariant

Two complementary checks; the CLI picks whichever applies per bank.

- **Row-wise** (banks that print a running balance): `prev.balance ± debit/credit == curr.balance`. Mismatch raises `ReconciliationError` with the row index.
- **Totals-based** (banks like PalmPay that omit a balance column): the parser reads `Total Money In` / `Total Money Out` from the statement header and the CLI asserts that the sum of parsed credits/debits equals those totals.

Both modes exist to catch silently-dropped rows — the failure mode of naive PDF parsers.

## Contributing a bank parser

1. Copy `src/bankstract/parsers/palmpay.py` to `src/bankstract/parsers/<bank>.py`.
2. Implement `detect()` and `parse() -> ParseResult` from `parsers/base.py`. Populate `total_credit` / `total_debit` if the statement only ships header totals.
3. Add a `Redactor` subclass under `src/bankstract/redactors/<bank>.py` for the fixture pipeline.
4. Drop the raw statement at `tests/<bank>/fixtures/_local/` (gitignored), then `uv run bankstract redact <bank> <raw> tests/<bank>/fixtures/sample.pdf` to produce the committable fixture.
5. Add tests under `tests/<bank>/test_parser.py` and `tests/<bank>/test_redactor.py`.

CI runs `ruff` + `pyright` (strict) + `pytest`. All three must pass clean. Reconciliation invariant must hold on every fixture.

Fixture PDFs must be redacted: account numbers, names, addresses, transaction IDs scrubbed. Never commit unredacted statements.

## License

MIT. Author: [logickoder](https://github.com/logickoder).
