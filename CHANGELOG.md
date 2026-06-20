# Changelog

Notable changes per release. Pre-1.0 — breaking changes land freely, called out in the relevant entry.

## 0.13.0 — 2026-06-20

### Added

- **Typed `ParseError` subclasses** so downstream consumers can distinguish failure modes without string-matching on `str(exc)`:
  - **`EncryptedSourceError`** — source PDF or XLSX is password-protected. Raised only in boundary modules `_pdfplumber.py` / `_xlsx.py`.
  - **`EmptyStatementError`** — parser ran clean, bank was detected, zero transactions extracted. Carries `marker_coverage: float` (detect_confidence at raise time) so the caller can distinguish a legitimately empty statement (high coverage) from silent layout drift that skipped every row (low coverage).
  - **`LayoutDriftError`** — bank detected but row extraction broke at a structural anchor (expected column header missing, sheet name missing, header totals unparseable). Carries `format_version` so the caller can surface "we saw version X, parser expects different structure".
- **`is_cdfv2(source)`** helper in `_xlsx.py` — used by `open_workbook` to distinguish encrypted-OOXML envelopes from non-XLSX inputs.

### Breaking (alpha)

- `ParseError` semantics tightened: now reserved for genuinely undiagnosable parse failures. Specific failures raise the typed subclass. Callers using `except ParseError:` keep matching all four via Python inheritance — but if you switch on `type(exc)`, expect the new classes in your match.
- Audit gate in test suite: any bare `raise ParseError(...)` inside `parsers/` or boundary modules must be preceded by a `# type-unknown:` comment justifying why no subclass fits. The AST audit test fails the PR otherwise.

### Internal

- Boundary modules (`_pdfplumber.py`, `_xlsx.py`) raise `EncryptedSourceError` for encrypted sources. `_pdfplumber` catches `PdfminerException` and inspects `args[0]` for `PDFPasswordIncorrect`; `_xlsx` catches `BadZipFile` + `InvalidFileException` + `KeyError` and sniffs CDFV2 magic.
- `sniff_format` now maps CDFV2 magic to `"xlsx"` so the dispatch reaches `open_workbook`, which then raises the typed encryption error.
- Each parser's prior catchall `raise ParseError(...)` call sites audited and reclassified into `EmptyStatementError` / `LayoutDriftError` per the actual cause.
- Test fixtures `tests/fixtures/encrypted_sample.{pdf,xlsx}` shipped (password `test123`); regen tool at `scripts/regen-encrypted-fixtures.py`.

## 0.12.0 — 2026-06-19

### Added

- **`bankstract.parse_to(source, *, format="csv", bank=None, reconcile=True) -> bytes`** — parse + serialize in one call. Mirrors the CLI's parse+write code path exactly so callers (Cloud workers, HTTP handlers) get byte-identical output to the CLI without reimplementing serialization. Single source of truth for canonical CSV / JSON.
- **`bankstract.write_csv(transactions, target)`** and **`bankstract.write_json(result, target)`** promoted from `bankstract.writers.*` to the public re-export surface. Low-level access for callers that already hold a `ParseResult`.

### Changed

- CLI internal: write path consolidated via `parse_to`. User-facing flags unchanged — same `-f`, same `--no-reconcile`, same `-o -` semantics — but the byte stream now flows through `parse_to` rather than a per-command writer call. Flagged for downstream packagers tracking CLI semver.
- CLI status line switched from `wrote N transactions -> <out>` to `wrote N bytes -> <out>`. Informational only — written to stderr when stdout is the data sink.
- JSON output to a file now ends with a trailing `\n` (was a trailing `\n` on stdout only). Additive whitespace; no parser/consumer regression.

### Notes

- Zero-drift contract test (`test_parse_to_byte_identical_to_cli`) parametrizes over every committed PDF fixture × both formats. Subprocess CLI bytes must equal `parse_to` bytes exactly.
- CI now runs the test matrix on `windows-latest` in addition to `ubuntu-latest` — catches line-ending regressions before release.

## 0.11.0 — 2026-06-19

### Added

- **`bankstract.redact(source, *, bank=None) -> RedactResult`** lib API. In-memory bytes — no tempfile, no disk write. Streaming callers (HTTP responses, archives) get the redacted payload without filesystem hops.
- **`bankstract.list_redactors() -> list[str]`** mirrors `list_parsers()`.
- **`RedactResult`** dataclass (`data: bytes`, `bank`, `format`, `format_version`, `report: RedactReport`) and **`Format`** type alias (`Literal["pdf","xlsx"]`) exposed via `bankstract`.
- **`Redactor`** ABC + **`RedactReport`** now re-exported from `bankstract` for type-hinting downstream consumers.

### Changed (breaking, alpha)

- `Redactor.redact(src: Path, dst: Path) -> RedactReport` → **`Redactor.redact(source: Source) -> RedactResult`**. Disk write moved to caller. `bankstract` CLI's `redact <bank> <src> <dst>` now thin-wraps the lib API, with `-` sentinel support for stdin/stdout — fully backwards-compatible at the CLI surface.
- `Format` type alias moved from `bankstract._xlsx` (internal) to `bankstract.schema` (public).
- `RedactReport` moved from `bankstract.redactors.base` to `bankstract.schema` (single canonical location for public dataclasses).

### Notes

- CLI subcommand behaviour unchanged for end users: `bankstract redact opay statement.pdf out.pdf` still works byte-identically.
- Cloud / SaaS workers can now `from bankstract import redact` instead of shelling out to the CLI.

## 0.10.0 — 2026-06-18

- Removed back-compat aliases (`PdfSource` → `Source`, opay `FORMAT_VERSION`). Alpha clean-break.
- `_api.SourceLike` distinct from internal `_source.Source` to disambiguate strict-vs-ergonomic unions.
- `_api.parse` / `detect` wrap `ValueError` as `ParseError` for a consistent exception surface.
- CLI `sniff_format` ValueError now surfaces as `ClickException` (was silently swallowed); fixed underlying `_peek` bug that reads from current cursor instead of offset 0 for stream sources.

## 0.9.0 — 2026-06-18

- **XLSX support architecture**: `_xlsx.py` boundary (openpyxl + `sniff_format`), `supported_formats: tuple[Format, ...]` per parser/redactor, OPay PDF + XLSX both first-class.
- OPay parser dispatches on `sniff_format(source)` internally; per-format `format_version` constants.
- OPay redactor adds cell-level XLSX rewrite path alongside the PDF template.
- CLI gates parser/redactor dispatch on `supported_formats`; `bankstract list` shows formats per bank.
- Dedup pass: `parsers/_money.py` (`parse_amount`, `parse_amount_optional`, `mask_account_number`) replaces 4 per-parser copies; `_source.rewind()` replaces 3.

## 0.8.0 — 2026-06-18

- **OPay parser** (wallet section): 8-col layout, distance-based multi-row narration attribution, multi-section truncation.
- **`ParseResult.row_wise_reconcilable`** opt-out flag for banks where balance column hides multi-account side-effects (OPay's OWealth auto-save/withdraw).
- OPay PDF redactor + sample.pdf fixture.

## 0.7.0 — 2026-06-18

- Per-parser `detect_confidence()` overrides — fraction-of-matched-markers scoring; real disambiguation, not just plumbing.
- `writers/csv.write_csv(transactions, target: Path | TextIO)` unified target; dropped `write_csv_stream` duplicate.
- FBN statement period extraction (when raw fixture preserves the line).
- `CONTRIBUTING.md` + README "Public surface" table.
- JSON output drops top-level `bank` — `metadata.bank` canonical.

## 0.6.0 — 2026-06-18

- Top-level lib API: `parse`, `detect`, `list_parsers`.
- JSON writer + CLI `--format json|csv`.
- `StatementMetadata` dataclass + backfilled for PalmPay/FBN/Zenith.
- `Path | BinaryIO | str` source type; CLI `-` sentinel for stdin/stdout.
- `Parser.detect_confidence(source) -> float` additive default.

## 0.5.0 — earlier

- Zenith parser + redactor.

## 0.4.0 and earlier

- FBN, PalmPay parsers + reconciliation invariant + CLI.
