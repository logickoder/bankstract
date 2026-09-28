# Code style

## Pyright strict is green or bust

All code under `src/` and `tests/` passes `uv run pyright` in strict mode (`pyproject.toml`). Zero errors, zero warnings. Untyped libraries (pymupdf, pdfplumber, openpyxl) are wrapped at the boundary in `_pymupdf.py` / `_pdfplumber.py` / `_xlsx.py`. Downstream code stays fully typed. If you must touch an untyped library directly, use `cast(Any, ...)` or a local `# type: ignore[...]`. Never relax a rule project-wide.

## Comments

No boilerplate. No `# Parse the PDF` above `parse_pdf()`. No docstrings on obvious methods. Comment only non-obvious choices, format quirks, or regex constraints. A comment earns its place when removing it would confuse a future reader:

```python
# PalmPay statements use \r\n between transaction blocks but \n within
# narration lines. Splitting on \n alone merges adjacent blocks.
blocks = raw.split("\r\n\r\n")
```

## Stack

- Python 3.11+. Use `match`, `Self`, `Unpack` where they fit.
- Money is `decimal.Decimal`, never `float`.
- Dates are `datetime.datetime` past the parser boundary, never `str`. Date-only banks pad `00:00:00` and leave `has_time=False`.
- Currency symbols are stripped at parse time and never re-emitted.
- `pdfplumber` is the extractor. `camelot-py` and `pytesseract` are declared extras for a lattice and OCR fallback that isn't wired yet.
- `pymupdf` only at the redactor / facade boundary. Never in parser code.
- `click` for the CLI. No `argparse`.
- pydantic v2 for `Transaction`. Frozen dataclasses for `ParseResult`, `StatementMetadata`, `ReconciliationReport`.
