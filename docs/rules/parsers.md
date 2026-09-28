# Parsers

## Read the statement first

Never invent regex patterns, table coordinates, or column orders for a bank format you haven't read. Open the fixture. Run `pdfplumber` interactively. Confirm the structure. Then write the parser. Guessed parsers silently drop or misclassify rows. Financial data has no margin for that.

## Contract

Every parser implements `Parser` from `parsers/base.py`:

```python
class Parser(ABC):
    bank: str  # registry key. Lowercase, no spaces.
    supported_formats: tuple[Format, ...] = ("pdf",)  # add "xlsx" when supported

    @abstractmethod
    def detect(self, source: Source) -> bool: ...

    @abstractmethod
    def parse(self, source: Source) -> ParseResult: ...

    def detect_confidence(self, source: Source) -> float:
        return 1.0 if self.detect(source) else 0.0  # override with marker fraction
```

`Source = Path | IO[bytes]`. `ParseResult` is frozen. It carries the transactions, optional header `total_credit` / `total_debit`, `StatementMetadata`, `format_version`, the `row_wise_disabled` opt-out, and `reconciliation`. The engine fills `metadata.bank` from the matched parser, and `result.bank` reads it. Parsers never set `reconciliation`. Multi-format parsers (opay) dispatch on `sniff_format(source)` and emit one `format_version` per format (`opay-pdf-2026-01`, `opay-xlsx-2026-01`) so drift is tracked per format.

## Rules

- `detect()` is cheap. First page (PDF) or sheet names (XLSX). Match a header string or column signature. No full parse.
- `parse()` raises a typed `ParseError` subclass carrying `format_version` on layout mismatch. Never return `[]` silently. See CONTRIBUTING.md for which subclass.
- Statements without a per-row balance MUST populate the header totals.
- Set `Transaction.has_time=True` only on rows that print a time.
- Never drop an unparseable block silently. No `.log` sidecar exists yet. Add a shared helper in `writers/` when the first parser needs one.
- Each parser self-registers in `parsers/__init__.py` by import side-effect.
- Share, don't duplicate. `parsers/_money.py` for amounts and account masks. `_columnar.py` for column walkers. `_common.py` / `_xlsx.py` for the pdfplumber / openpyxl boundary.
- Progress: fire `emit("walk_page", i, n_pages)` once per page in the outer loop. Import `emit` from `parsers/_common`, never `bankstract._progress`. `_columnar.walk_rows` already emits it. Never re-emit.
- Each bank parser is independently owned. Never touch one to fix another.
