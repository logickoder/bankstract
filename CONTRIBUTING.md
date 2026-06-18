# Contributing

bankstract takes parsers, redactors, bug fixes, and docs. CLAUDE.md is the operating charter — read it before opening a PR. Highlights below.

## Gate

`ruff check` + `ruff format --check` + `pyright` (strict) + `pytest` must pass clean. The pre-commit hook runs the same checks. CI runs them again.

```bash
uv sync --all-extras
uv run pre-commit install
uv run pytest
```

## Adding a bank parser

1. Copy `src/bankstract/parsers/palmpay.py` (PDF-only template) or `opay.py` (PDF + XLSX dispatch template) to `src/bankstract/parsers/<bank>.py`. Implement `detect()`, `parse() -> ParseResult`, and optionally override `detect_confidence()` when your bank's markers may collide with another's. Reuse shared helpers — `parse_amount` / `parse_amount_optional` / `mask_account_number` from `parsers/_money.py`, `walk_rows` from `parsers/_columnar.py`, `first_page_text` / `extract_words_per_page` from `parsers/_common.py`, `open_workbook` / `sniff_format` from `_xlsx.py`.
2. Declare which input formats your parser handles: `supported_formats: tuple[Format, ...] = ("pdf",)` (default) or `("pdf", "xlsx")`. The CLI gates dispatch on this attribute and `bankstract list` prints it. Mirror on the redactor (`Redactor.supported_formats`) if the redaction path also supports XLSX.
3. Copy `src/bankstract/redactors/palmpay.py` to `src/bankstract/redactors/<bank>.py`. For XLSX redaction, override `Redactor.redact()` to dispatch on `sniff_format(src)` — openpyxl cell-level rewrites for XLSX, fall through to the inherited template-method PDF pipeline otherwise.
4. Drop the raw statement at `tests/<bank>/fixtures/_local/statement.{pdf,xlsx}` (gitignored) and run `uv run bankstract redact <bank> tests/<bank>/fixtures/_local/statement.pdf tests/<bank>/fixtures/sample.pdf`. Eyeball the output, commit only the redacted sample.
5. Add `tests/<bank>/test_parser.py` + `tests/<bank>/test_redactor.py`. Multi-format banks parametrize tests over both `.pdf` and `.xlsx` fixtures.

### Parser self-registration

Each parser self-registers by calling `register(MyParser())` at module top level. The CLI walks `all_parsers()` and synthesizes a `bankstract <bank>` command per registered parser via `cli.py`'s `for _bank in sorted(all_parsers()): _bank_command(_bank)`. Side-effect imports in `parsers/__init__.py` make every new parser file load on package import — adding a new file is enough; no central registry edit.

That import-side-effect choice trades a small static-analysis discoverability hit (IDE doesn't auto-suggest `bankstract <newbank>` until the package re-loads) for zero per-bank wiring. Acceptable for the plugin shape.

### Dual-fixture testing rule

Parser and metadata tests parametrize over the committed redacted sample(s) AND any raw `_local/statement.*` (gitignored) when present. The raw fixture catches metadata-regex regressions that placeholder-only redacted samples silently pass. Multi-format parsers (PDF + XLSX) parametrize over every supported extension.

```python
SAMPLE_PDF = FIXTURE_DIR / "sample.pdf"
SAMPLE_XLSX = FIXTURE_DIR / "sample.xlsx"
LOCAL_PDF = FIXTURE_DIR / "_local" / "statement.pdf"
LOCAL_XLSX = FIXTURE_DIR / "_local" / "statement.xlsx"

_FIXTURES = [
    pytest.param(SAMPLE_PDF, id="sample-pdf"),
    pytest.param(SAMPLE_XLSX, id="sample-xlsx",
                 marks=pytest.mark.skipif(not SAMPLE_XLSX.exists(), reason="no XLSX")),
    pytest.param(LOCAL_PDF, id="local-pdf",
                 marks=pytest.mark.skipif(not LOCAL_PDF.exists(), reason="raw absent")),
    pytest.param(LOCAL_XLSX, id="local-xlsx",
                 marks=pytest.mark.skipif(not LOCAL_XLSX.exists(), reason="raw absent")),
]
```

`tests/conftest.py` also emits CSV + JSON for every fixture into `_local/<stem>.{ext}.{csv,json}` on every pytest run so the owner can eyeball parser output across all banks without re-running the CLI.

## Fixture privacy

CLAUDE.md directive 3 is load-bearing. No real personal names, business names, addresses, phone digits, BVN, or account numbers may appear inline in source, tests, or committed fixtures. Use obviously-fake placeholders (`FOO`, `BAR`, `ACME`, `QUUX`, `Placeholder Lane`, `1111 2222`). Raw statements live only in gitignored `_local/`.

## Reconciliation invariant

Every parser MUST produce rows where `prev.balance ± debit/credit == curr.balance` (banks with a balance column) OR where the parsed credit/debit sums match the statement header's totals (banks without). The CLI applies whichever invariants the parser supplied evidence for. Never weaken `reconcile.py` to make tests pass — the parser is wrong, not the invariant.

## Commits

Conventional Commits. CI release gate keys off the prefix:

- `feat:` → minor bump on PyPI collision
- `fix:` / `perf:` → patch bump
- `chore:` / `docs:` / `test:` / `refactor:` / `ci:` / `style:` / `build:` / `revert:` → no publish
- Anything else → workflow logs a warning and skips publish

Don't push or tag without owner approval. Diffs reviewed manually.
