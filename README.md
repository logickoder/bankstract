# bankstract

Convert Nigerian bank PDF + XLSX statements into structured CSV or JSON. Plugin architecture — one parser per bank, formats declared per parser.

```bash
pip install bankstract

bankstract palmpay statement.pdf -o out.csv
bankstract opay statement.xlsx -o out.json -f json
bankstract auto unknown.pdf -o out.csv
bankstract list                                # bank (formats)
```

## Status

| Bank       | Formats   | Status        |
| ---------- | --------- | ------------- |
| PalmPay    | PDF       | v0.11 — alpha  |
| First Bank | PDF       | v0.11 — alpha  |
| Zenith     | PDF       | v0.11 — alpha  |
| OPay       | PDF, XLSX | v0.11 — alpha  |

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

bankstract.list_parsers()             # ['fbn', 'opay', 'palmpay', 'zenith']
bankstract.list_redactors()           # ['fbn', 'opay', 'palmpay', 'zenith']
bankstract.detect("statement.pdf")    # 'palmpay' | None

result = bankstract.parse("statement.pdf")            # auto-detect
result = bankstract.parse(fp, bank="fbn")             # explicit; fp is BytesIO

result.metadata.account_holder
result.metadata.statement_period_start
result.transactions[0].balance
result.format_version

# Redact PII in-memory (no disk write); .data is the redacted file bytes.
redacted = bankstract.redact("statement.pdf")         # auto-detect bank
redacted = bankstract.redact(fp, bank="opay")         # explicit, stream input
redacted.data                                         # bytes — stream to HTTP / write to disk
redacted.report.redactions                            # count
```

### Public surface (semver-locked)

Only the names re-exported from `bankstract` are part of the semver contract:

| Name                  | Kind          | Purpose                                             |
| --------------------- | ------------- | --------------------------------------------------- |
| `parse`               | function      | `parse(source, *, bank=None) -> ParseResult`        |
| `detect`              | function      | `detect(source) -> str \| None` (max-score bank)    |
| `list_parsers`        | function      | sorted bank names (parsers)                         |
| `redact`              | function      | `redact(source, *, bank=None) -> RedactResult` — in-memory bytes |
| `list_redactors`      | function      | sorted bank names (redactors)                       |
| `Parser`              | ABC           | base class for new parsers                          |
| `Redactor`            | ABC           | base class for new redactors                        |
| `Transaction`         | pydantic      | row schema                                          |
| `StatementMetadata`   | dataclass     | account holder / period / opening + closing balance |
| `ParseResult`         | dataclass     | `transactions[]`, totals, `format_version`, metadata |
| `RedactResult`        | dataclass     | `data: bytes`, `bank`, `format`, `format_version`, `report` |
| `RedactReport`        | dataclass     | `bank`, `pages`, `redactions`, `audit`              |
| `Format`              | type alias    | `Literal["pdf", "xlsx"]`                            |
| `ParseError`          | exception     | layout mismatch / undetectable source               |
| `ReconciliationError` | exception     | invariant break                                     |
| `__version__`         | str           | package version                                     |

`source` accepts `pathlib.Path`, a string path (treated as a path), or a seekable binary stream (e.g. `io.BytesIO`). Auto-detection picks the parser / redactor with the highest `detect_confidence` score — ties resolve to registration order. `redact()` returns bytes in-memory: no tempfile, no disk write — callers stream the payload straight to HTTP responses, archives, or `Path.write_bytes()` as needed. Anything imported from a submodule prefixed with `_` (`bankstract._api`, `bankstract._pdfplumber`, `bankstract._xlsx`, `bankstract._layout`) is internal and may change in any release.

## Reconciliation invariant

Two complementary checks; the CLI picks whichever applies per bank.

- **Row-wise** (banks that print a running balance): `prev.balance ± debit/credit == curr.balance`. Mismatch raises `ReconciliationError` with the row index.
- **Totals-based** (banks like PalmPay that omit a balance column): the parser reads `Total Money In` / `Total Money Out` from the statement header and the CLI asserts that the sum of parsed credits/debits equals those totals.

Both modes exist to catch silently-dropped rows — the failure mode of naive PDF parsers.

## Contributing a bank parser

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full checklist: gate setup, shared helpers (`parsers/_money.py`, `parsers/_columnar.py`, `_xlsx.py`), `supported_formats` declaration, XLSX redactor dispatch, dual-fixture testing rule, fixture privacy, and the Conventional Commits release gate.

Quick form: copy `parsers/palmpay.py` (PDF-only) or `parsers/opay.py` (PDF + XLSX) as the template; reuse shared helpers; declare `supported_formats`; drop the raw statement at `tests/<bank>/fixtures/_local/statement.{pdf,xlsx}` (gitignored); redact into `sample.{pdf,xlsx}`; commit only the redacted sample.

CI runs `ruff` + `pyright` (strict) + `pytest`. All three must pass clean. Reconciliation invariant holds on every fixture (or the parser opts out via `ParseResult.row_wise_reconcilable=False` and supplies header totals for `verify_totals`).

Fixtures must be redacted: account numbers, names, addresses, transaction IDs scrubbed. Never commit unredacted statements.

## License

MIT. Author: [logickoder](https://github.com/logickoder).
