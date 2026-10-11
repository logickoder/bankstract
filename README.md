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
bankstract inspect <pdf>                       # tamper signals as JSON. Exit 2 on an error signal
bankstract inspect <pdf> --isolate             # untrusted file: child process, 60s limit, exit 2 if it cannot finish
bankstract <bank> <pdf> -o out.json -f json    # JSON instead of CSV
cat statement.pdf | bankstract auto - -o -     # stdin / stdout pipeline
bankstract <bank> <pdf> -o <out> -q            # suppress the stderr progress bar
bankstract auto <pdf> -o <out> --isolate       # untrusted file: child process, 60s limit, exit 2 if it cannot finish
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
result.bank                           # the parser that matched, passed or detected

# parse() never reconciles. reconcile_result() returns a checked copy.
checked = bankstract.reconcile_result(result)  # progress_callback= to see the reconcile stage
checked.report.totals                 # 'passed' | 'not_available'
checked.report.row_wise               # 'passed' | 'not_available' | 'disabled'
checked.report.row_wise_reason        # why, when disabled

# Canonical bytes, identical to the CLI. One path for both formats.
csv_bytes  = bankstract.serialize(checked, "csv")
json_bytes = bankstract.serialize(checked, "json")

# Tamper signals. Evidence, not a verdict. See Integrity checks below.
report = bankstract.inspect("statement.pdf")          # bank= to skip detection
report = bankstract.inspect("statement.pdf", result=result)  # already parsed: skips the second parse
report.clean                          # True when no signal fired
report.errors                         # signals with severity "error"
report.signals[0].code                # e.g. "incremental_update"

# Or all three steps in one call.
csv_bytes  = bankstract.convert("statement.pdf")                     # default format="csv"
json_bytes = bankstract.convert(fp, format="json", bank="opay")      # explicit
debug_bytes = bankstract.convert(fp, reconcile=False)                # skip invariant

# Low-level writers, to a path or text stream.
from pathlib import Path
bankstract.write_csv(checked.transactions, Path("out.csv"))
bankstract.write_json(checked, Path("out.json"))

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
| `parse`               | function      | `parse(source, *, bank=None, progress_callback=None, isolate=False, timeout=60.0, memory_mb=2048) -> ParseResult`. `isolate=True` runs it in a child process. |
| `convert`             | function      | `convert(source, *, format="csv", bank=None, reconcile=True, progress_callback=None, isolate=False, timeout=60.0, memory_mb=2048) -> bytes`. Byte-identical to CLI, isolated or not. |
| `reconcile_result`    | function      | `reconcile_result(result, *, progress_callback=None) -> ReconciledParseResult`. Raises `ReconciliationError` on a break or when no check can run. |
| `serialize`           | function      | `serialize(result, format: OutputFormat) -> bytes`. The canonical bytes `convert` and the CLI emit. |
| `detect`              | function      | `detect(source, *, isolate=False, timeout=60.0, memory_mb=2048) -> str \| None` (max-score bank) |
| `inspect`             | function      | `inspect(source, *, bank=None, result=None, isolate=False, timeout=60.0, memory_mb=2048) -> IntegrityReport`. Pass `result` to skip a second parse. `isolate=True` runs it in a child process. Raises `EncryptedSourceError`, and `ResourceLimitError` when an isolated worker cannot finish. A file the parser rejects is an `unparseable` signal. |
| `list_parsers`        | function      | sorted bank names (parsers)                         |
| `write_csv`           | function      | `write_csv(transactions, target: Path \| TextIO) -> int` |
| `write_json`          | function      | `write_json(result, target: Path \| TextIO) -> int` |
| `redact`              | function      | `redact(source, *, bank=None, progress_callback=None, isolate=False, timeout=60.0, memory_mb=2048) -> RedactResult`. In-memory bytes. |
| `list_redactors`      | function      | sorted bank names (redactors)                       |
| `Parser`              | ABC           | base class for new parsers                          |
| `Redactor`            | ABC           | base class for new redactors                        |
| `Transaction`         | pydantic      | row schema. `has_time` flags a real (not padded) time. |
| `StatementMetadata`   | dataclass     | account holder / period / opening + closing balance |
| `ParseResult`         | dataclass     | `transactions[]`, totals, `format_version`, metadata, `bank`, `row_wise_disabled`, `reconciliation` |
| `ReconciledParseResult` | dataclass   | `ParseResult` with a guaranteed report. `.report` is never `None`. |
| `IntegrityReport`     | dataclass     | `bank`, `format_version`, `signals`, `.errors`, `.clean`, `.to_dict()` (the CLI's JSON) |
| `IntegritySignal`     | dataclass     | `code`, `severity` (`warn` \| `error`), `detail`, `page`, `row` |
| `ReconciliationReport`| dataclass     | `totals`, `row_wise` (each a `CheckStatus`), `row_wise_reason` |
| `CheckStatus`         | type alias    | `Literal["passed", "not_available", "disabled"]`    |
| `RedactResult`        | dataclass     | `data: bytes`, `bank`, `format`, `format_version`, `report` |
| `RedactReport`        | dataclass     | `bank`, `pages`, `redactions`, `audit`              |
| `Format`              | type alias    | `Literal["pdf", "xlsx"]`. Input formats.            |
| `OutputFormat`        | type alias    | `Literal["csv", "json"]`. Output formats.           |
| `ParseError`          | exception     | base. Undiagnosable parse failure. `.bank` names the matched parser. |
| `EncryptedSourceError`| exception     | source PDF / XLSX is password-protected             |
| `EmptyStatementError` | exception     | parser ran clean, zero rows. `.marker_coverage` field. |
| `LayoutDriftError`    | exception     | anchor missing / column shifted post-detect         |
| `ResourceLimitError`  | exception     | an isolated worker passed its time limit, ran out of memory or died. Not a `ParseError`: `except ParseError` must not skip a file that stopped the checker. The file is not known to be clean. |
| `ReconciliationError` | exception     | invariant break. `.bank`, `.format_version`, `.row_index`. Not a `ParseError`. |
| `ProgressEvent`       | dataclass     | `stage: str`, `current: int`, `total: int`          |
| `ProgressCallback`    | type alias    | `Callable[[ProgressEvent], None]`                   |
| `throttle`            | function      | `throttle(callback, *, min_interval_ms=100) -> ProgressCallback` |
| `__version__`         | str           | package version                                     |

`source` accepts a `Path`, a string path, or a seekable binary stream. Auto-detection picks the highest `detect_confidence`. Ties go to registration order. Nothing touches disk. Modules prefixed `_` are internal.

## Reconciliation invariant

Two checks. `reconcile_result()` runs each one the statement has evidence for. The CLI and `convert()` call it by default.

- **Row-wise** (banks that print a running balance): `prev.balance ± debit/credit == curr.balance`. Mismatch raises `ReconciliationError` with the row index.
- **Totals-based** (statements with header totals): the sum of parsed credits/debits must equal the printed `Total Money In` / `Total Money Out`.

Both catch silently-dropped rows. The report says what ran: `passed`, `not_available` (no evidence on the statement) or `disabled` (parser opt-out, with `row_wise_reason`).

| Bank    | `totals`        | `row_wise`      |
| ------- | --------------- | --------------- |
| fbn     | `passed`        | `passed`        |
| zenith  | `not_available` | `passed`        |
| palmpay | `passed`        | `not_available` |
| opay    | `passed`        | `disabled`      |

opay balances skip OWealth auto-save moves, so they don't chain. `ReconciliationError` also fires when no check can run, or when some rows lack a balance and others don't.

## Integrity checks

`inspect()` and `bankstract inspect` look for signs a statement was edited after the bank made it. They report evidence. They never say a statement is forged. Exit code is 2 when any signal is an `error`, else 0. The JSON report goes to stdout. One line per signal goes to stderr, with code and position only.

| Code                    | Severity | Fires when                                                                 |
| ----------------------- | -------- | -------------------------------------------------------------------------- |
| `unparseable`           | error    | The parser rejected the file. File checks still run when the bank is known. |
| `reconciliation_failed` | error    | The balance chain or header totals break. `row` names the row.             |
| `incremental_update`    | error    | More than one revision (`startxref` section). Changes were appended after the bank wrote the file. |
| `overlay_over_text`     | error    | A fill of any colour, drawn after a text run, covers part of a glyph. The visible value may differ. |
| `unexpected_producer`   | warn     | PDF producer or XLSX writer differs from the bank's own export tool.       |
| `modified_after_create` | warn     | PDF creation and modification dates differ.                                |
| `unexpected_font`       | warn     | A font outside the bank's baseline.                                        |
| `id_changed`            | warn     | The two halves of the trailer `/ID` differ, for a bank that writes them equal (fbn, opay). A tool that re-saves the file changes the second half. |
| `font_size_outlier`     | warn     | An amount's size differs from its table column.                            |
| `date_out_of_order`     | warn     | Rows break day order. Same-day order is ignored.                           |
| `date_outside_period`   | warn     | A row falls outside the statement period.                                  |
| `checks_skipped`        | warn     | A check did not run on part of the file: a page holds over 2000 text runs or fills, a page's decoded content passes 2 MB, overlay work passed 20 million comparisons, objects have coordinates that are not numbers, or the file would not open for the file checks. |

`IntegritySignal.detail` quotes the statement: amounts, balances, covered text. It is customer data. Show it to the statement's owner. Never log it. Log `code`, `severity`, `page` and `row` instead.

### Untrusted files

A crafted PDF can cost gigabytes inside one mupdf call, and no in-process code can stop that. A 62-byte page that invokes a form of 100,000 text runs takes 4s and 180 MB. Pass `isolate=True` (CLI `--isolate`) to `parse()`, `convert()`, `detect()`, `redact()` or `inspect()` for any file you did not make. `bankstract redact <bank>` takes `--isolate` and `--timeout` too. `--timeout` without `--isolate` is refused: nothing else enforces a limit. The whole call runs in a child process with a time limit. A child that passes the limit, runs out of memory or dies raises `ResourceLimitError`, and the CLI exits 2 with no report. It never returns a clean one.

- About 0.02s a call on Linux and macOS once the first call has started a helper process (the first costs about 0.3s). The helper imports bankstract once and forks each worker from it, and it exits with your process. Windows has no fork server, so every call spawns a child and costs about 0.35s. Off by default, like `parse()`.
- The memory limit (`memory_mb`) is enforced on Linux only. macOS refuses `RLIMIT_AS`, and Windows has no equivalent, so both get the time limit alone.
- `progress_callback` works with `isolate=True`: the worker sends each event up a pipe and your callback gets them in order, as they happen, and the CLI bar draws as usual. The timeout counts from the call, not from the last event. A callback that raises stops the worker. `bankstract auto --isolate` detects the bank in a worker too, so it prints the same "detected" line and the same messages as without the flag.
- The worker re-imports your main module. Call it from a script under `if __name__ == "__main__":`. Without the guard the child re-runs your script and dies, and you get a `ResourceLimitError` whose message names a main script that could not be re-imported as one cause. A script piped on stdin (`python -`) cannot be re-imported at all, and raises a `RuntimeError` before any worker starts, saying so. `python -c`, a REPL, a notebook and ordinary modules work.

What it misses:

- A forger who regenerates the file with the bank's own library and recomputes every balance passes every check. Only the bank can rule that out.
- A pymupdf re-save keeps the original producer. Word, Acrobat and online editors rewrite it. For fbn and opay the changed trailer `/ID` still gives it away (`id_changed`). Zenith and palmpay write unequal halves, so a re-save of theirs passes.
- A statement that embeds an uncompressed PDF reads as extra revisions and exits 2. This is a deliberate false positive. Excluding embedded sections would let a forger hide a revision inside a fake stream.
- A page stuffed with junk switches the size and overlay checks off for that page. `checks_skipped` says so, as a warning. Real statements stay near 300 text runs a page.
- A retyped amount in the same font and size leaves no file signal. Reconciliation catches it unless the balances were fixed too.

Baselines come from raw bank statements, not from the redacted samples in `tests/`. A bank that updates its PDF library can warn until the baseline in `integrity.py` is updated.

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
