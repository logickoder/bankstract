# bankstract

Nigerian bank PDF + XLSX statements into structured CSV or JSON. One parser per bank. Each parser declares the formats it handles.

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
| PalmPay    | PDF       | v0.15, alpha  |
| First Bank | PDF       | v0.15, alpha  |
| Zenith     | PDF       | v0.15, alpha  |
| OPay       | PDF, XLSX | v0.15, alpha  |

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

The pre-commit hook runs `ruff check`, `ruff format --check`, `pyright` (strict), and `pytest` before every commit. Bypass only when a hook is broken, with `git commit --no-verify`. The same checks run in CI.

### Releasing

CI publishes to PyPI on push to `main` via `.github/workflows/publish.yml`. The workflow runs the full gate (ruff + pyright + pytest). If the current `pyproject.toml` version already exists on PyPI, it auto-bumps the minor and commits the bump before publishing. PyPI auth uses OIDC trusted publishing. No token in repo or CI secrets.

To prepare a release locally:

```bash
scripts/bump-version.sh                 # patch bump
scripts/bump-version.sh minor           # 0.2.x -> 0.3.0
scripts/bump-version.sh major           # 0.x.x -> 1.0.0
scripts/bump-version.sh 0.3.0           # exact set
uv build                                # dist/*.whl + dist/*.tar.gz
uv publish dist/*                       # skip if using the GH workflow. Needs --token or UV_PUBLISH_TOKEN
```

Trusted-publisher setup (one-time, owner only): create a publisher at <https://pypi.org/manage/account/publishing/> with workflow `publish.yml`, repo `logickoder/bankstract`.

## Usage

```bash
bankstract <bank> <pdf> -o <out>               # explicit parser
bankstract auto <pdf> -o <out>                 # auto-detect via Parser.detect_confidence()
bankstract list                                # show registered parsers
bankstract <bank> <pdf> -o out.json -f json    # JSON instead of CSV
cat statement.pdf | bankstract auto - -o -     # stdin / stdout pipeline
bankstract <bank> <pdf> -o <out> -q            # suppress the stderr progress bar
```

A throttled per-stage progress bar prints to stderr when stderr is a TTY. Pipes and file output suppress it without a flag. Pass `-q/--quiet` to force-suppress.

Pass `-` as the PDF arg to read from stdin, or `-` to `-o` to write to stdout. When stdout carries the data, informational messages go to stderr so the data stream stays clean.

Unparseable blocks land in a `.log` sidecar next to the output file.

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

# Parse + serialize in one call. Byte-identical to the CLI's output.
csv_bytes  = bankstract.parse_to("statement.pdf")                   # default format="csv"
json_bytes = bankstract.parse_to(fp, format="json", bank="opay")    # explicit
debug_bytes = bankstract.parse_to(fp, reconcile=False)              # skip invariant

# Low-level writers. Use when you already hold a ParseResult.
from pathlib import Path
bankstract.write_csv(result.transactions, Path("out.csv"))
bankstract.write_json(result, Path("out.json"))

# Redact PII in-memory (no disk write). `.data` carries the redacted file bytes.
redacted = bankstract.redact("statement.pdf")         # auto-detect bank
redacted = bankstract.redact(fp, bank="opay")         # explicit, stream input
redacted.data                                         # bytes. Stream to HTTP / write to disk.
redacted.report.redactions                            # count

# Progress hooks. Drive a UI or log a phase timeline.
def on_progress(ev: bankstract.ProgressEvent) -> None:
    print(f"{ev.stage}: {ev.current}/{ev.total}")

bankstract.parse_to(fp, progress_callback=on_progress)

# CLI bar pattern. Throttle to <=10 events/sec. Stage transitions and terminal
# events always pass.
cb = bankstract.throttle(on_progress, min_interval_ms=100)
bankstract.parse_to(fp, progress_callback=cb)
```

### Progress events

| Stage          | Fires                                                                | `current`/`total`           |
| -------------- | -------------------------------------------------------------------- | --------------------------- |
| `detect`       | once per `parse / parse_to / redact` (post-detection)                | `(1, 1)`                    |
| `open`         | once after the parser/redactor opens the source                      | `(1, 1)`                    |
| `extract_page` | per page during pdfplumber word extraction (the slowest stage)       | `(i, n_pages)`              |
| `walk_page`    | per page during the parser's row walk; XLSX path emits `(1, 1)` once | `(i, n_pages)` or `(1, 1)`  |
| `reconcile`    | once from `parse_to` after the invariant runs                        | `(1, 1)`                    |
| `redact_page`  | per page from `redact()`; opay XLSX fires per sheet                  | `(i, n_pages_or_n_sheets)`  |
| `done`         | once before each top-level call returns                              | `(1, 1)`                    |

`ProgressEvent.stage` is `str`. Adding stages later is non-breaking. Wrap with `bankstract.throttle(cb, min_interval_ms=100)` for a UI bar. Pass the raw callback for full-fidelity telemetry (Cloud workers, distributed tracing).

### Public surface (semver-locked)

Only the names re-exported from `bankstract` are part of the semver contract:

| Name                  | Kind          | Purpose                                             |
| --------------------- | ------------- | --------------------------------------------------- |
| `parse`               | function      | `parse(source, *, bank=None) -> ParseResult`        |
| `parse_to`            | function      | `parse_to(source, *, format="csv", bank=None, reconcile=True, progress_callback=None) -> bytes`. Byte-identical to CLI. |
| `detect`              | function      | `detect(source) -> str \| None` (max-score bank)    |
| `list_parsers`        | function      | sorted bank names (parsers)                         |
| `write_csv`           | function      | `write_csv(transactions, target: Path \| TextIO) -> int` |
| `write_json`          | function      | `write_json(result, target: Path \| TextIO) -> int` |
| `redact`              | function      | `redact(source, *, bank=None) -> RedactResult`. In-memory bytes. |
| `list_redactors`      | function      | sorted bank names (redactors)                       |
| `Parser`              | ABC           | base class for new parsers                          |
| `Redactor`            | ABC           | base class for new redactors                        |
| `Transaction`         | pydantic      | row schema                                          |
| `StatementMetadata`   | dataclass     | account holder / period / opening + closing balance |
| `ParseResult`         | dataclass     | `transactions[]`, totals, `format_version`, metadata |
| `RedactResult`        | dataclass     | `data: bytes`, `bank`, `format`, `format_version`, `report` |
| `RedactReport`        | dataclass     | `bank`, `pages`, `redactions`, `audit`              |
| `Format`              | type alias    | `Literal["pdf", "xlsx"]`                            |
| `ParseError`          | exception     | base. Undiagnosable parse failure.                  |
| `EncryptedSourceError`| exception     | source PDF / XLSX is password-protected             |
| `EmptyStatementError` | exception     | parser ran clean, zero rows. `.marker_coverage` field. |
| `LayoutDriftError`    | exception     | anchor missing / column shifted post-detect         |
| `ReconciliationError` | exception     | invariant break                                     |
| `ProgressEvent`       | dataclass     | `stage: str`, `current: int`, `total: int`          |
| `ProgressCallback`    | type alias    | `Callable[[ProgressEvent], None]`                   |
| `throttle`            | function      | `throttle(callback, *, min_interval_ms=100) -> ProgressCallback` |
| `__version__`         | str           | package version                                     |

`source` accepts `pathlib.Path`, a string path (treated as a path), or a seekable binary stream (e.g. `io.BytesIO`). Auto-detection picks the parser / redactor with the highest `detect_confidence` score. Ties resolve to registration order. `redact()` returns bytes in-memory. No tempfile, no disk write. Stream the payload straight to HTTP responses, archives, or `Path.write_bytes()`. Anything imported from a submodule prefixed with `_` (`bankstract._api`, `bankstract._pdfplumber`, `bankstract._xlsx`, `bankstract._layout`) is internal and changes between releases.

## Reconciliation invariant

Two checks. The CLI picks whichever applies per bank.

- **Row-wise** (banks that print a running balance): `prev.balance ± debit/credit == curr.balance`. Mismatch raises `ReconciliationError` with the row index.
- **Totals-based** (banks like PalmPay that omit a balance column): the parser reads `Total Money In` / `Total Money Out` from the statement header. The CLI asserts that the sum of parsed credits/debits equals those totals.

Both modes exist to catch silently-dropped rows. That's the failure mode of naive PDF parsers.

## Contributing a bank parser

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full checklist: gate setup, shared helpers (`parsers/_money.py`, `parsers/_columnar.py`, `_xlsx.py`), `supported_formats` declaration, XLSX redactor dispatch, dual-fixture testing rule, fixture privacy, Conventional Commits release gate.

Quick form: copy `parsers/palmpay.py` (PDF-only) or `parsers/opay.py` (PDF + XLSX) as the template. Reuse shared helpers. Declare `supported_formats`. Drop the raw statement at `tests/<bank>/fixtures/_local/statement.{pdf,xlsx}` (gitignored). Redact into `sample.{pdf,xlsx}`. Commit only the redacted sample.

CI runs `ruff` + `pyright` (strict) + `pytest`. All three must pass clean. Reconciliation invariant holds on every fixture (or the parser opts out via `ParseResult.row_wise_reconcilable=False` and supplies header totals for `verify_totals`).

Fixtures must be redacted. Account numbers, names, addresses, transaction IDs all scrubbed. Never commit unredacted statements.

## License

MIT. Author: [logickoder](https://github.com/logickoder).
