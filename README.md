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

| Bank       | Formats   | Status |
| ---------- | --------- | ------ |
| PalmPay    | PDF       | alpha  |
| First Bank | PDF       | alpha  |
| Zenith     | PDF       | alpha  |
| OPay       | PDF, XLSX | alpha  |

## Usage

```bash
bankstract <bank> <pdf> -o <out>               # explicit parser
bankstract auto <pdf> -o <out>                 # auto-detect via Parser.detect_confidence()
bankstract list                                # show registered parsers
bankstract <bank> <pdf> -o out.json -f json    # JSON instead of CSV
cat statement.pdf | bankstract auto - -o -     # stdin / stdout pipeline
bankstract <bank> <pdf> -o <out> -q            # suppress the stderr progress bar
```

`-` reads stdin or writes stdout. Messages and the progress bar go to stderr, so piped data stays clean. The bar shows only on a TTY.

### Output

CSV columns: `date,narration,debit,credit,balance,reference,currency,has_time`. `has_time=false` means the time in `date` is padded `00:00:00`. New columns only append.

JSON adds `format_version`, `metadata`, `totals` and `reconciliation`. `reconciliation` is absent under `--no-reconcile`.

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
result.transactions[0].has_time       # False when the statement prints date only
result.format_version

# parse() never reconciles. reconcile_result() returns a checked copy.
result = bankstract.reconcile_result(result)
result.reconciliation.totals          # 'passed' | 'not_available'
result.reconciliation.row_wise        # 'passed' | 'not_available' | 'disabled'

# Parse + serialize in one call. Byte-identical to the CLI's output.
csv_bytes  = bankstract.convert("statement.pdf")                     # default format="csv"
json_bytes = bankstract.convert(fp, format="json", bank="opay")      # explicit
debug_bytes = bankstract.convert(fp, reconcile=False)                # skip invariant

# Low-level writers. Use when you already hold a ParseResult.
from pathlib import Path
bankstract.write_csv(result.transactions, Path("out.csv"))
bankstract.write_json(result, Path("out.json"))   # includes "reconciliation" once checked

# Redact PII in-memory (no disk write). `.data` carries the redacted file bytes.
redacted = bankstract.redact("statement.pdf")         # auto-detect bank
redacted = bankstract.redact(fp, bank="opay")         # explicit, stream input
redacted.data                                         # bytes. Stream to HTTP / write to disk.
redacted.report.redactions                            # count

# Progress hooks. Drive a UI or log a phase timeline.
def on_progress(ev: bankstract.ProgressEvent) -> None:
    print(f"{ev.stage}: {ev.current}/{ev.total}")

bankstract.convert(fp, progress_callback=on_progress)

# CLI bar pattern. Throttle to <=10 events/sec. Stage transitions and terminal
# events always pass.
cb = bankstract.throttle(on_progress, min_interval_ms=100)
bankstract.convert(fp, progress_callback=cb)
```

### Progress events

| Stage          | Fires                                                                | `current`/`total`           |
| -------------- | -------------------------------------------------------------------- | --------------------------- |
| `detect`       | once per `parse / convert / redact` (post-detection)                | `(1, 1)`                    |
| `open`         | once after the parser/redactor opens the source                      | `(1, 1)`                    |
| `extract_page` | per page during pdfplumber word extraction (the slowest stage)       | `(i, n_pages)`              |
| `walk_page`    | per page during the parser's row walk; XLSX path emits `(1, 1)` once | `(i, n_pages)` or `(1, 1)`  |
| `reconcile`    | once from `reconcile_result` (and so `convert`) after the checks pass | `(1, 1)`                  |
| `redact_page`  | per page from `redact()`; opay XLSX fires per sheet                  | `(i, n_pages_or_n_sheets)`  |
| `done`         | once before each top-level call returns                              | `(1, 1)`                    |

`ProgressEvent.stage` is a `str`, so new stages are non-breaking.

### Public surface (semver-locked)

Only the names re-exported from `bankstract` are part of the semver contract:

| Name                  | Kind          | Purpose                                             |
| --------------------- | ------------- | --------------------------------------------------- |
| `parse`               | function      | `parse(source, *, bank=None) -> ParseResult`        |
| `convert`             | function      | `convert(source, *, format="csv", bank=None, reconcile=True, progress_callback=None) -> bytes`. Byte-identical to CLI. |
| `reconcile_result`    | function      | `reconcile_result(result) -> ParseResult`. Returns a copy with `.reconciliation` set. Raises `ReconciliationError` on a break or when no check can run. |
| `detect`              | function      | `detect(source) -> str \| None` (max-score bank)    |
| `list_parsers`        | function      | sorted bank names (parsers)                         |
| `write_csv`           | function      | `write_csv(transactions, target: Path \| TextIO) -> int` |
| `write_json`          | function      | `write_json(result, target: Path \| TextIO) -> int` |
| `redact`              | function      | `redact(source, *, bank=None) -> RedactResult`. In-memory bytes. |
| `list_redactors`      | function      | sorted bank names (redactors)                       |
| `Parser`              | ABC           | base class for new parsers                          |
| `Redactor`            | ABC           | base class for new redactors                        |
| `Transaction`         | pydantic      | row schema. `has_time` flags a real (not padded) time. |
| `StatementMetadata`   | dataclass     | account holder / period / opening + closing balance |
| `ParseResult`         | dataclass     | `transactions[]`, totals, `format_version`, metadata, `reconciliation` |
| `ReconciliationReport`| dataclass     | `totals`, `row_wise`. Each a `CheckStatus`.         |
| `CheckStatus`         | type alias    | `Literal["passed", "not_available", "disabled"]`    |
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

`source` accepts a `Path`, a string path, or a seekable binary stream. Auto-detection picks the highest `detect_confidence`. Ties go to registration order. Nothing touches disk. Modules prefixed `_` are internal.

## Reconciliation invariant

Two checks. `reconcile_result()` runs each one the statement has evidence for. The CLI and `convert()` call it by default.

- **Row-wise** (banks that print a running balance): `prev.balance ± debit/credit == curr.balance`. Mismatch raises `ReconciliationError` with the row index.
- **Totals-based** (statements with header totals): the sum of parsed credits/debits must equal the printed `Total Money In` / `Total Money Out`.

Both catch silently-dropped rows. The report says what ran: `passed`, `not_available` (no evidence on the statement) or `disabled` (parser opt-out).

| Bank    | `totals`        | `row_wise`      |
| ------- | --------------- | --------------- |
| fbn     | `passed`        | `passed`        |
| zenith  | `not_available` | `passed`        |
| palmpay | `passed`        | `not_available` |
| opay    | `passed`        | `disabled`      |

opay balances skip OWealth auto-save moves, so they don't chain. `ReconciliationError` also fires when no check can run, or when some rows lack a balance and others don't.

## Sponsoring a bank parser

Need a bank that isn't supported yet? Sponsor the implementation.

One-time fee. The parser ships to the MIT engine publicly. You get priority turnaround and a heads-up before format-breaking changes land.

**Banks frequently requested:** GTB, Access, UBA, Stanbic, Wema, Polaris, Sterling, Keystone.

[Open a sponsorship request](https://buy.polar.sh/polar_cl_QcZsf4BqRIPqQZvUW04VQdZ9rP7slrNbroDgG4A799w) or email [jeffery@logickoder.dev](mailto:jeffery@logickoder.dev) with the bank name and a sample statement (redacted).

## Develop

Project uses [uv](https://docs.astral.sh/uv/) for dependency + venv management.

```bash
uv sync --all-extras       # create .venv, install deps + extras from uv.lock
uv run pre-commit install  # one-time: enable the pre-commit hook
uv run pytest              # run tests
uv run ruff check src tests
uv run pyright src tests   # strict type check (see AGENTS.md directive 8)
uv run bankstract list     # invoke CLI
```

The pre-commit hook and CI run the same checks. Releasing and contribution rules live in [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing a bank parser

Follow the checklist in [CONTRIBUTING.md](CONTRIBUTING.md). Commit only redacted fixtures.

## License

MIT. Author: [logickoder](https://github.com/logickoder).
