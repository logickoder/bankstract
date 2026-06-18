# bankstract — PRD

**Status:** concept · v0.1 target
**License:** MIT
**Stack:** Python 3.11+

---

## What

Public Python CLI + library that converts Nigerian bank PDF statements into structured CSV or JSON. Plugin architecture — one parser module per bank.

```bash
bankstract palmpay statement.pdf -o out.csv
bankstract palmpay statement.pdf -o out.json -f json
bankstract auto unknown.pdf -o out.csv          # auto-detect via detect_confidence
cat statement.pdf | bankstract auto - -o -      # stdin/stdout pipeline
bankstract list                                 # show registered parsers
```

```python
import bankstract
result = bankstract.parse("statement.pdf")            # auto-detect
result = bankstract.parse(fp, bank="fbn")             # explicit; fp is BytesIO
result.metadata.account_holder
result.transactions[0].balance
```

## Why

Every Nigerian dev solves this once, badly, in private. Banks export PDFs; tools like BudgetBakers, YNAB, Notion, Google Sheets want CSV. Manual entry costs more than the visibility is worth, so trackers go stale.

bankstract closes that gap with one clean tool, one plugin contract, and community-driven bank coverage.

## Scope

| Version | Coverage                                                                         |
| ------- | -------------------------------------------------------------------------------- |
| v0.1    | PalmPay only. CLI + plugin contract + reconciliation + tests + CI. PyPI release. |
| v0.2    | First Bank parser + OCR fallback for scanned statements.                         |
| v0.3    | Zenith Bank parser (running-balance, multi-page).                                |
| v0.4+   | GTB, Kuda, Opay, Stanbic, Wise, Bamboo, Risevest — community PRs.                |

**Out of scope:** category inference, ML-based parsing, GUI, pushing data into third-party trackers (those belong in downstream tools).

## Architecture

### Stack rationale

- **Python** over Node — `pdfplumber` and `camelot-py` are best-in-class table extractors; `pytesseract` is the cleanest OCR binding. Node alternatives are weaker on table extract and slower on OCR.
- **pdfplumber primary, camelot fallback** — pdfplumber for text-PDF table extract; camelot lattice mode for messy ruled tables; pytesseract only when the text layer is absent (scanned PDFs).
- **pymupdf for true redaction** — `apply_redactions()` rewrites the PDF content stream rather than visually overlaying, so fixture PDFs contain no recoverable PII.
- **pydantic schema** — runtime validation + clean JSON Schema export for downstream tools.
- **click CLI** — standard, autocomplete-friendly, low boilerplate.

### Plugin contract

Every bank is a parser module implementing the `Parser` ABC.

```python
class Parser(ABC):
    bank: str  # module-level identifier (e.g. "palmpay", "fbn")

    @abstractmethod
    def detect(self, source: PdfSource) -> bool:
        """True if this parser handles the given PDF (structural marker match)."""

    @abstractmethod
    def parse(self, source: PdfSource) -> ParseResult:
        """Extract transactions + metadata + header totals. Raise ParseError on format mismatch."""

    def detect_confidence(self, source: PdfSource) -> float:
        """Override to disambiguate when multiple parsers detect the same PDF.
        Default: 1.0 on positive detection, 0.0 otherwise. Callers pick max."""
```

`PdfSource = Path | IO[bytes]` — every entry point accepts either a filesystem path or a seekable binary stream (e.g. `io.BytesIO` from stdin).

Parsers live in `src/bankstract/parsers/<bank>.py` and self-register via import side-effect in `parsers/__init__.py`. A parallel `Redactor` plugin tree under `src/bankstract/redactors/<bank>.py` produces committable fixtures from raw statements.

### Transaction + ParseResult + StatementMetadata schema

```python
class Transaction(BaseModel):
    date: datetime                   # full timestamp; banks w/o time pad with 00:00:00
    narration: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    balance: Decimal | None = None   # None when the statement omits a running balance
    reference: str | None = None     # bank transaction ID
    currency: str = "NGN"


@dataclass(frozen=True)
class StatementMetadata:
    bank: str | None = None
    account_holder: str | None = None
    account_number_masked: str | None = None     # last 4 digits only ("XXXXXX1234")
    statement_period_start: datetime | None = None
    statement_period_end: datetime | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None


@dataclass
class ParseResult:
    transactions: list[Transaction]
    total_credit: Decimal | None = None   # from statement header
    total_debit: Decimal | None = None
    format_version: str | None = None
    metadata: StatementMetadata | None = None
```

Amounts are stored as `Decimal` (not float — financial precision). The Naira sign is stripped before parsing.

### Reconciliation invariant

Two complementary checks:

- **Row-wise** (`reconcile()`): `prev.balance ± debit/credit == curr.balance`. Used when the statement carries a per-row running balance. Mismatch raises `ReconciliationError` with the row index.
- **Totals-based** (`verify_totals()`): sum of parsed credits/debits equals header `Total Money In` / `Total Money Out`. Used when the statement omits a running balance (e.g. PalmPay). Parsers MUST populate `ParseResult.total_credit/total_debit` in that case, otherwise reconciliation is skipped silently — a directive 2 violation.

Both modes catch silently-dropped rows, which is the failure mode of every naive PDF parser.

### Failure handling

- **Unparseable blocks** go to a `.log` sidecar file. Never silently dropped.
- **Format-version drift** — each parser logs a detected `format_version` at run start. Parse errors include the detected version, so issue reports are actionable.

### Repo layout

```
bankstract/
├── pyproject.toml             hatchling backend, ruff + pytest + pyright config
├── pyrightconfig.json         IDE-side mirror of [tool.pyright]
├── uv.lock                    uv-managed lockfile
├── README.md
├── PRD.md
├── LICENSE                    MIT
├── src/
│   └── bankstract/            standard src-layout package
│       ├── cli.py
│       ├── schema.py          Transaction + ParseResult + errors
│       ├── reconcile.py       reconcile() + verify_totals()
│       ├── _layout.py         Word dataclass + classify + Y-grouping (shared)
│       ├── _pymupdf.py        typed facade over pymupdf
│       ├── _pdfplumber.py     typed facade over pdfplumber + PdfSource alias
│       ├── _api.py            lib API: parse() / detect() / list_parsers()
│       ├── writers/csv.py
│       ├── writers/json.py
│       ├── parsers/
│       │   ├── __init__.py    registry (import side-effect)
│       │   ├── base.py        Parser ABC
│       │   ├── _common.py     pdfplumber boundary helpers (text/words)
│       │   ├── _columnar.py   shared column-table walker (fbn + zenith)
│       │   ├── palmpay.py
│       │   ├── fbn.py
│       │   └── zenith.py
│       └── redactors/
│           ├── __init__.py    registry (import side-effect)
│           ├── base.py        Redactor ABC + RedactReport (template-method)
│           ├── _shared.py     redact + row-walk + regex-sweep primitives
│           ├── palmpay.py
│           ├── fbn.py
│           └── zenith.py
├── tests/
│   ├── test_reconcile.py      bank-agnostic
│   └── <bank>/                one folder per bank
│       ├── test_parser.py
│       ├── test_redactor.py
│       └── fixtures/
│           ├── sample.pdf     redacted sample (committed)
│           └── _local/        gitignored: raw statements for dev
└── .github/workflows/ci.yml   uv + ruff + pyright + pytest
```

## CLI surface

```bash
bankstract <bank> <pdf> -o <out>                # explicit parser, CSV default
bankstract <bank> <pdf> -o <out> -f json        # JSON instead of CSV
bankstract auto <pdf> -o <out>                  # detect via detect_confidence (max wins)
bankstract <bank> - -o -                        # stdin → stdout pipeline (`-` sentinel)
bankstract list                                 # show registered parsers
```

`-` as the PDF arg reads from stdin into a `BytesIO`. `-` as `-o` writes to stdout; summary lines redirect to stderr so the data stream stays clean for piping.

## Risks

| Risk                                                                         | Mitigation                                                                                                 |
| ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Statement format drift — banks rev PDFs annually.                            | Per-parser `format_version` detection + log on parse error. Per-bank fixture suite in tests.               |
| OCR accuracy on scanned statements — ₦ / N confusion, comma-separator drift. | Post-OCR regex normalization. Reconciliation invariant catches arithmetic errors before they ship.         |
| Charset edge cases — `₦` decodes differently across PDF producers.           | Strip currency symbols and store as `Decimal`.                                                             |
| Fixture privacy — sample PDFs contain PII.                                   | All fixtures must be anonymized: account numbers, names, addresses scrubbed. Never commit unredacted PDFs. |

## Roadmap

- [ ] `pyproject.toml` + Parser ABC + Transaction schema + csv writer + reconciliation
- [ ] PalmPay parser + 1 anonymized fixture + test
- [ ] CLI wrapper + auto-detect
- [ ] README + LICENSE + CI
- [ ] **v0.1.0** — PyPI release, PalmPay only, FBN marked in progress
- [ ] First Bank parser + OCR fallback → **v0.2.0**
- [ ] Open issues for next 5 banks; invite contributors

## Contributing

Add a bank in four steps:

1. Copy `src/bankstract/parsers/palmpay.py` to `src/bankstract/parsers/<your_bank>.py` and implement `detect()` + `parse() -> ParseResult`.
2. Copy `src/bankstract/redactors/palmpay.py` to `src/bankstract/redactors/<your_bank>.py` for the fixture pipeline.
3. Drop the raw statement in `tests/<your_bank>/fixtures/_local/` (gitignored), run `uv run bankstract redact <your_bank> <raw> tests/<your_bank>/fixtures/sample.pdf`, eyeball the output, commit the redacted sample.
4. Add tests in `tests/<your_bank>/test_parser.py` and `tests/<your_bank>/test_redactor.py`.

CI runs `ruff` + `pyright` (strict) + `pytest`. All three must pass. Reconciliation invariant must hold on every fixture.

## License

MIT. See `LICENSE`.