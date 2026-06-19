# bankstract — Claude Operating Charter

You are working inside `bankstract`, a public Python library that converts Nigerian bank PDF statements into structured CSV via a per-bank parser plugin system.

Owner: Jeffery Orazulike (github.com/logickoder).

---

## CORE DIRECTIVES

### 1. ZERO HALLUCINATION ON PARSER LOGIC
Never invent regex patterns, table coordinates, or column orders for a bank format you haven't read. Open the fixture PDF. Run `pdfplumber` interactively. Confirm the structure. Then write the parser. Guessed parsers silently drop or misclassify rows — financial data has no margin for that.

### 2. RECONCILIATION INVARIANT IS LOAD-BEARING
Every parser MUST produce rows where `prev.balance ± debit/credit == curr.balance`. If a parser change breaks reconciliation on any fixture, the parser is wrong — not the invariant. Never weaken `reconcile.py` to make tests pass.

### 3. FIXTURE PRIVACY IS NON-NEGOTIABLE
Sample PDFs in `tests/fixtures/` contain real account data. Before any fixture lands in git:
- Account number → `XXXXXXXXXX`
- Name → `Test User`
- Address → `Test Address`
- Phone / email → scrubbed
- BVN → never present

If an unredacted PDF is staged, halt and warn. Run `uv run bankstract redact <bank> <raw> <out>` to scrub it, or regenerate the fixture from a synthetic source.

The same rule extends to **all source and test code**: no real personal names, business names, addresses, phone digits, or account numbers may appear inline — not in test fixtures, not in assertion strings, not in synthetic-PDF generators. Use obviously-fake placeholders (`FOO`, `BAR`, `ACME`, `QUUX`, `Placeholder Lane`, `1111 2222`, etc.). Real values live only in `tests/<bank>/fixtures/_local/` (gitignored).

### 4. HUMAN IN THE LOOP
Do not run `git commit`, `git push`, `git tag`, or any publish operation without explicit owner command in the current turn. Edit, save, halt. Owner reviews diffs manually.

### 5. SURGICAL EDITS
Modify the specific function, parser, or test under request. Don't touch unrelated files, rewrite working parsers to "improve" them, or refactor across modules without an explicit refactor task. Each bank parser is independently owned — touching one to "fix" another is forbidden.

### 6. NO BOILERPLATE COMMENTS
No `# Parse the PDF` above `parse_pdf()`. No docstrings on obvious methods. Comments only where non-obvious algorithmic choices, format quirks, or regex constraints need explanation. A comment earns its place when removing it would confuse a future reader:

```python
# PalmPay statements use \r\n between transaction blocks but \n within
# narration lines. Splitting on \n alone merges ad
blocks = raw.split("\r\n\r\n")
```

### 7. TONE
Direct, technical, honest. No "I've gone ahead and...", no "Let me know if...". Report the change, the file, the test status.

### 8. PYRIGHT STRICT IS GREEN OR BUST
All code under `src/` and `tests/` must pass `uv run pyright` with the strict-mode config in `pyproject.toml` (`[tool.pyright] typeCheckingMode = "strict"`). Zero errors, zero warnings. Untyped third-party libraries (pymupdf, pdfplumber, openpyxl) are wrapped at the boundary in `_pymupdf.py` / `_pdfplumber.py` / `_xlsx.py` — downstream code stays fully typed. If you must touch an untyped library directly, annotate the bridging call with `cast(Any, ...)` or a local `# type: ignore[...]` comment, never a project-wide rule relax.

---

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
│   └── bankstract/            package (src-layout; hatchling editable mode
│       ├── __init__.py        rejects prefix rewrites, so use a real subdir)
│       ├── cli.py             click entrypoint w/ --format csv|json + `-` stdin/stdout
│       ├── schema.py          pydantic Transaction + StatementMetadata + ParseResult + errors
│       ├── reconcile.py       row-wise + totals-based invariant checks
│       ├── _api.py            lib API: parse() / detect() / list_parsers()
│       ├── _source.py         Source = Path | IO[bytes] + rewind() helper
│       ├── _layout.py         shared Word dataclass + classify + Y-grouping
│       ├── _pdfplumber.py     typed facade over pdfplumber (open_doc)
│       ├── _pymupdf.py        typed facade over pymupdf (redactor boundary)
│       ├── _xlsx.py           typed facade over openpyxl + sniff_format(source)
│       ├── writers/
│       │   ├── csv.py         write_csv(transactions, target: Path | TextIO)
│       │   └── json.py        write_json(result, target) — full ParseResult shape
│       ├── parsers/
│       │   ├── __init__.py    registry (import side-effect)
│       │   ├── base.py        Parser ABC + supported_formats: tuple[Format, ...]
│       │   ├── _common.py     first_page_text + extract_words_per_page
│       │   ├── _columnar.py   column_of / row_columns / walk_rows (shared by fbn + zenith)
│       │   ├── _money.py      parse_amount / parse_amount_optional / mask_account_number
│       │   ├── palmpay.py     PDF — totals-based reconcile
│       │   ├── fbn.py         PDF — row-wise + totals reconcile
│       │   ├── zenith.py      PDF — row-wise reconcile
│       │   └── opay.py        PDF + XLSX — dispatch via sniff_format
│       └── redactors/
│           ├── __init__.py    registry (import side-effect)
│           ├── base.py        Redactor ABC + RedactReport + supported_formats
│           ├── _shared.py     redact_word / redact_range / shape_preserve / page_rows / apply_regex_sweeps
│           ├── palmpay.py     phrase-based
│           ├── fbn.py         column-aware aggressive blank
│           ├── zenith.py      column-aware aggressive blank (skips above table header)
│           └── opay.py        PDF column-aware + XLSX cell-level rewrite
├── tests/
│   ├── test_reconcile.py      bank-agnostic invariant tests
│   └── <bank>/                one folder per bank, mirrors src/ layout
│       ├── test_parser.py
│       ├── test_redactor.py
│       └── fixtures/
│           ├── sample.pdf     redacted PDF — committed
│           └── _local/        gitignored: drop raw PDFs here for dev
└── .github/workflows/ci.yml
```

## STACK + CONVENTIONS

- Python 3.11+ (use `match`, `Self`, `Unpack` where applicable)
- All public functions and class attributes are type-hinted; pyright strict passes clean
- Money is `decimal.Decimal`, never `float`
- Dates are `datetime.datetime` (full timestamp), never `str` past the parser boundary; banks without a time component pad with `00:00:00`
- Currency stripped at parse time; the symbol is never re-emitted in stored data
- `pdfplumber` primary; `camelot-py` lattice fallback; `pytesseract` OCR last
- `pymupdf` only at the redactor / facade boundary; never reach for it from parser code
- `click` for CLI; no `argparse`
- `pydantic` v2 for the `Transaction` record; `dataclass` for `ParseResult` / `RedactReport`

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

# lint + types (MUST pass clean — see directive 8)
uv run ruff check src tests
uv run ruff format src tests
uv run pyright src tests

# test
uv run pytest                              # all
uv run pytest tests/test_palmpay.py -v     # one bank
uv run pytest -k reconcile                 # invariant only

# run CLI locally
uv run bankstract palmpay tests/fixtures/palmpay/sample.pdf -o /tmp/out.csv

# redact a raw statement into a committable fixture
uv run bankstract redact list
uv run bankstract redact palmpay tests/fixtures/palmpay/_local/statement.pdf tests/fixtures/palmpay/sample.pdf

# bump version
scripts/bump-version.sh                 # patch bump (default)
scripts/bump-version.sh minor           # minor bump
scripts/bump-version.sh major           # major bump
scripts/bump-version.sh 0.3.0           # set exact version

# build wheel + sdist
uv build
```

## PARSER CONTRACT

Every parser implements `Parser` ABC from `parsers/base.py`:

```python
class Parser(ABC):
    bank: str  # registry key — lowercase, no spaces
    supported_formats: tuple[Format, ...] = ("pdf",)  # add "xlsx" when supported

    @abstractmethod
    def detect(self, source: Source) -> bool: ...

    @abstractmethod
    def parse(self, source: Source) -> ParseResult: ...

    def detect_confidence(self, source: Source) -> float:
        return 1.0 if self.detect(source) else 0.0  # override w/ marker fraction
```

`Source = Path | IO[bytes]`. `ParseResult` carries the transaction list plus optional `total_credit` / `total_debit` read from the statement header + `StatementMetadata` + `format_version` + `row_wise_reconcilable` opt-out. Parsers whose statements omit a per-row balance column MUST populate the totals so the CLI can fall back to `verify_totals()` instead of silently skipping reconciliation. Multi-format parsers (e.g. OPay) dispatch internally on `sniff_format(source)` and emit per-format `format_version` constants (`opay-pdf-2026-01` vs `opay-xlsx-2026-01`) so drift detection works per format independently.

Rules:
- `detect()` is cheap — read first page (PDF) or sheet names (XLSX), match header string or column signature. No full parse.
- `parse()` raises `ParseError` (carrying `format_version`) on layout mismatch. No silent return of `[]`.
- Unparseable mid-document blocks must go to a `.log` sidecar. Never silently dropped. Add a shared helper in `writers/` when the first parser needs one — no speculative helper today.
- Each parser self-registers in `parsers/__init__.py` via import side-effect. No central registry edit needed.
- Share, don't duplicate: amount/account helpers live in `parsers/_money.py` (`parse_amount`, `parse_amount_optional`, `mask_account_number`); columnar walkers in `_columnar.py`; pdfplumber/openpyxl boundaries in `_common.py` / `_xlsx.py`.

## TESTING

- Every parser ships with at least one anonymized fixture under `tests/<bank>/fixtures/sample.pdf`
- Reconciliation invariant tested for every fixture in `test_reconcile.py` (row-wise + totals-based)
- Format-version detection tested against multiple versions when more than one is available
- Each parser has a sibling `tests/<bank>/test_redactor.py` covering the redactor (synthetic-PDF round trip + PII leak sweep)
- No mocking of `pdfplumber` / `camelot` / `pytesseract` / `openpyxl` — tests run against real fixture PDFs/XLSX
- Every parser/metadata test parametrizes over both `tests/<bank>/fixtures/sample.pdf` (committed, redacted) AND `tests/<bank>/fixtures/_local/statement.pdf` (gitignored, raw) when present. Skip the local case via `pytest.mark.skipif(not _local.exists())` so CI stays green without raw fixtures. The raw fixture catches metadata-regex regressions that placeholder values silently pass

## OUT OF SCOPE — DO NOT ADD

- Category inference (rule-based or ML) — downstream concern
- GUI / web UI — CLI only
- Direct integration with BudgetBakers, YNAB, Notion — downstream concern
- Pushing to remote APIs — bankstract reads PDFs, never posts elsewhere
- Statement download automation (logging into bank portals) — separate tool
- Encrypted-PDF password prompting beyond a single `--password` CLI flag

If asked to add any of the above, push back. They aren't part of bankstract.

## VOICE (README, docstrings, issue templates)

- No emojis in body copy
- No marketing language ("seamless", "powerful", "robust", "blazingly fast")
- No AI / blockchain / Web3 framing
- Declarative sentences. State what it does, then how.
- Owner's brand identifier is `logickoder` — always link to `github.com/logickoder` in public-facing copy

## ASSISTANT RESPONSE FORMAT

- State change → terse confirmation with file + function name
- Diagnosis → root cause in one to two sentences, then the fix
- Refusal → cite the directive being upheld (e.g. "fixture not read. Read tests/fixtures/fbn/sample.pdf first")
- Never apologize. Acknowledge errors technically and move on