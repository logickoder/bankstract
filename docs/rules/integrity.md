# Integrity

`inspect()` reports tamper signals. It never says a statement is forged.

- Evidence, not a verdict. A forger who regenerates the file with the bank's own library and recomputes every balance passes every check. Say so in any copy that describes the feature.
- Two severities. `error`: the file or its numbers contradict a bank export (extra revision, overlay, reconciliation failure, unparseable). `warn`: differs from the baseline and can be innocent (producer, fonts, size, dates).
- A check that flags a raw bank statement is wrong, not the statement. Run every new check over all `_local/statement.*` files before it ships. Zero signals on raw files is the bar.
- Baselines (`_BASELINES` in `integrity.py`) come from raw statements in `_local/`. Never from a committed sample. The redactor rewrites fonts, and the opay XLSX redactor re-saves through openpyxl.
- Match the producer on library name, never version. A bank bumping iText must not flag every statement.
- A bank missing from a table skips that check. Add it only when its raw statement shows a stable signature.
- Never exempt a signal because the file's own structure says to: stream `/Length`, the `/Prev` chain, object order. A forger writes that structure. A reader finds the last `startxref` from the end of the file and ignores it. Prefer a loud false positive to a miss a forger can build.
- Bound the work a crafted page can cost. A file is untrusted input. Never size a loop or a structure by a coordinate or count the file supplies. `_MAX_PAGE_CONTENT` gates a page before any extraction, because a cap on runs applied afterwards comes too late: a 1 MB page cost 720 MB. `_MAX_PAGE_OBJECTS` and `_OVERLAY_BUDGET` cap the page-level checks. A skipped page is reported as `checks_skipped`. Drop non-finite coordinates in the facade.
- Count the `startxref` keyword for revisions, not `startxref <offset>`. PDF reads a comment as whitespace. Discount only the `startxref 0` section a linearized file writes at the top, with `/Linearized` beside it. The marker alone cancels nothing.
- Set a threshold from real statements, and leave a forger nothing to tune. The cover check works per glyph at a tenth of a glyph and half opacity, because no later fill touches any text on the four banks' raw statements. A 50% run-level ratio and a 0.9 opacity cut-off both let a forger hide one digit or sit just under the line. Measure the raw files before loosening one.
- A check that cannot run says so. Silence reads as clean. A bank-agnostic check runs with no detected bank. An object the facade drops, or a file that will not open for the file checks, becomes a `checks_skipped` warning.
- Compare dates by day. Real exports order same-day rows loosely.
- Every check ships with a forged test file that trips it. Build the forgery from a committed sample in `tests/test_integrity.py`.
- `pymupdf` stays behind `_pymupdf.py`. Workbook properties are read from the zip in `_xlsx.py`, not through openpyxl, which rewrites them on load.
- Signal `detail` strings are public copy. Follow [voice](voice.md): `<what>. <why>. <do this>.`
- `detail` quotes the statement: amounts, balances, covered text. It is customer data. Show it to the owner of the statement. Never write it to a log, an error tracker or stderr. Log `code`, `severity`, `page` and `row`. The CLI keeps `detail` in the stdout JSON and prints only those four to stderr. A new check that quotes text needs no extra step. A new log line that prints `detail` is a bug.
- Pass `result=` to `inspect()` when the caller already parsed. The result must come from the same source. Nothing checks that.

## Known gaps

- A pymupdf re-save keeps the original producer. Only tools that rewrite it (Word, Acrobat, online editors) change it.
- A retyped amount in the same font and size leaves no file signal. Reconciliation is the only check that fires, and only if the forger didn't fix the balances.
