# bankstract - Agent Operating Charter

You are working inside `bankstract`, a public Python library that converts Nigerian bank PDF and XLSX statements into structured CSV and JSON via a per-bank parser plugin system.

Owner: Jeffery Orazulike (github.com/logickoder).

## CORE DIRECTIVES

Short form. Each links to the full rule in `docs/rules/`. Read the linked rule before working in its area.

1. **Zero hallucination on parser logic.** Read the fixture before writing a regex or column map. [parsers](docs/rules/parsers.md)
2. **Reconciliation is load-bearing.** A broken fixture means the parser is wrong. Never weaken `reconcile.py`. [reconciliation](docs/rules/reconciliation.md)
3. **Fixture privacy is non-negotiable.** No real PII in fixtures, source, or tests. [fixture-privacy](docs/rules/fixture-privacy.md)
4. **Human in the loop.** No commit, push, tag, or publish without an explicit owner command. [workflow](docs/rules/workflow.md)
5. **Surgical edits.** Change only what was asked. Each parser is independently owned. [workflow](docs/rules/workflow.md)
6. **No boilerplate comments.** Comment only what would confuse a future reader. [code-style](docs/rules/code-style.md)
7. **Tone.** Direct, technical, honest. [voice](docs/rules/voice.md), [workflow](docs/rules/workflow.md)
8. **Pyright strict is green or bust.** Zero errors, zero warnings, no project-wide relaxing. [code-style](docs/rules/code-style.md)

## REPO LAYOUT

```
bankstract/
├── pyproject.toml             ruff + pytest config
├── pyrightconfig.json         strict-mode pyright config
├── README.md                  public-facing
├── PRD.md                     product spec
├── CONTRIBUTING.md            new-bank checklist + gate rules
├── LICENSE                    MIT
├── uv.lock                    locked deps
├── src/
│   └── bankstract/            package (src-layout. hatchling editable mode
│       ├── __init__.py        rejects prefix rewrites, so use a real subdir)
│       ├── cli.py             click entrypoint with --format csv|json + `-` stdin/stdout
│       ├── schema.py          pydantic Transaction + StatementMetadata + ParseResult + errors
│       ├── reconcile.py       reconcile_result() entry point + row-wise / totals checks
│       ├── _api.py            lib API: parse() / convert() / detect() / redact() / list_parsers()
│       ├── _source.py         Source = Path | IO[bytes] + rewind() helper
│       ├── _layout.py         shared Word dataclass + classify + Y-grouping
│       ├── _pdfplumber.py     typed facade over pdfplumber (open_doc)
│       ├── _pymupdf.py        typed facade over pymupdf (redactor boundary)
│       ├── _xlsx.py           typed facade over openpyxl + sniff_format(source)
│       ├── writers/
│       │   ├── csv.py         write_csv(transactions, target: Path | TextIO)
│       │   ├── json.py        write_json(result, target). Full ParseResult shape.
│       │   └── serialize.py   serialize(result, format) -> canonical bytes. Switches on OutputFormat.
│       ├── parsers/
│       │   ├── __init__.py    registry (import side-effect)
│       │   ├── base.py        Parser ABC + supported_formats: tuple[Format, ...]
│       │   ├── _common.py     first_page_text + extract_words_per_page
│       │   ├── _columnar.py   column_of / row_columns / walk_rows (shared by fbn + zenith)
│       │   ├── _money.py      parse_amount / parse_amount_optional / mask_account_number
│       │   ├── palmpay.py     PDF. Totals-based reconcile.
│       │   ├── fbn.py         PDF. Row-wise + totals reconcile.
│       │   ├── zenith.py      PDF. Row-wise reconcile.
│       │   └── opay.py        PDF + XLSX. Dispatch via sniff_format.
│       └── redactors/
│           ├── __init__.py    registry (import side-effect)
│           ├── base.py        Redactor ABC + RedactReport + supported_formats
│           ├── _shared.py     redact_word / redact_range / shape_preserve / page_rows / apply_regex_sweeps
│           ├── palmpay.py     phrase-based
│           ├── fbn.py         column-aware aggressive blank
│           ├── zenith.py      column-aware aggressive blank (skips above table header)
│           └── opay.py        PDF column-aware + XLSX cell-level rewrite
├── tests/
│   ├── _fixtures.py           FIXTURES + RECONCILIATION tables, cached parsed()
│   ├── test_reconcile.py      bank-agnostic invariant tests
│   ├── test_fixture_invariants.py  cross-bank row checks (zero amounts, has_time)
│   └── <bank>/                one folder per bank, mirrors src/ layout
│       ├── test_parser.py
│       ├── test_redactor.py
│       └── fixtures/
│           ├── sample.pdf     redacted PDF. Committed.
│           └── _local/        gitignored. Drop raw PDFs here for dev.
├── docs/rules/                agent rules, one topic per file
└── .github/workflows/         ci.yml + publish.yml (release gate)
```

## COMMANDS

Project uses `uv` for env + deps. Lockfile is `uv.lock`.

```bash
# install / sync (creates .venv, installs from uv.lock)
uv sync --all-extras

# enable the pre-commit hook (one-time, runs ruff + pyright + pytest before every commit)
uv run pre-commit install

# add a dep
uv add <pkg>
uv add --dev <pkg>

# lint + types (MUST pass clean)
uv run ruff check src tests
uv run ruff format src tests
uv run pyright src tests

# test
uv run pytest                              # all
uv run pytest tests/palmpay -v             # one bank
uv run pytest -k reconcile                 # invariant only

# run CLI locally
uv run bankstract palmpay tests/palmpay/fixtures/sample.pdf -o /tmp/out.csv

# redact a raw statement into a committable fixture
uv run bankstract redact list
uv run bankstract redact palmpay tests/palmpay/fixtures/_local/statement.pdf tests/palmpay/fixtures/sample.pdf

# bump version
scripts/bump-version.sh                 # patch bump (default)
scripts/bump-version.sh minor           # minor bump
scripts/bump-version.sh major           # major bump
scripts/bump-version.sh 0.3.0           # set exact version

# build wheel + sdist
uv build
```

## OUT OF SCOPE - DO NOT ADD

- Category inference (rule-based or ML). Downstream concern.
- GUI / web UI. CLI only.
- Direct integration with BudgetBakers, YNAB, Notion. Downstream concern.
- Pushing to remote APIs. bankstract reads PDFs, never posts elsewhere.
- Statement download automation (logging into bank portals). Separate tool.
- Encrypted-PDF password prompting beyond a single `--password` CLI flag

If asked to add any of the above, push back. They aren't part of bankstract.

## RULES

One topic per file in `docs/rules/`, the single source of truth. `.claude/rules/` holds thin wrappers (frontmatter plus an `@` import) that Claude Code loads by path. Edit the source in `docs/rules/`, never the wrapper.

| Rule | Covers |
|---|---|
| [parsers](docs/rules/parsers.md) | read-before-write, parser contract, shared helpers, progress events |
| [reconciliation](docs/rules/reconciliation.md) | the invariant, `reconcile_result`, opt-out rules |
| [fixture-privacy](docs/rules/fixture-privacy.md) | redaction, placeholders, `_local/` |
| [testing](docs/rules/testing.md) | fixture registration, dual-fixture rule, no mocking |
| [code-style](docs/rules/code-style.md) | pyright strict, comments, stack conventions |
| [workflow](docs/rules/workflow.md) | human in the loop, surgical edits, commits, release gate, response format |
| [voice](docs/rules/voice.md) | copy, comments, commits, errors |
