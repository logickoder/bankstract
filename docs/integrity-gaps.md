# Integrity gaps

Open work on `inspect()` after the first cut. Each item says what is missing, why it matters and what closes it. Rules for the feature live in [rules/integrity](rules/integrity.md).

## Needs data from the owner

### 1. More raw samples per bank

- **Gap.** Each baseline (`_BASELINES` in `integrity.py`) comes from one raw statement per bank. Palmpay's "no producer" rule and opay's two-font list rest on a single file each.
- **Risk.** A bank changes its PDF library or fonts. Genuine statements start to warn.
- **Close.** Collect raw statements from different months and accounts per bank. Run `inspect` over all of them. Every raw statement must come back clean. Widen a table only when two or more real files disagree with it.

### 2. Real edited statements

- **Gap.** Every test forgery is synthetic, built with pymupdf. They prove each check fires. They say nothing about how Word, Acrobat or an online editor change a statement.
- **Risk.** A real edit may leave a signal pattern we don't look for, or trip a check differently than the synthetic one.
- **Close.** Edit a copy of a raw statement with each common tool. Keep the copies in `_local/` (gitignored). Add a `_local` test per tool that asserts the signals it leaves.

## Detection limits

### 3. Same-library forgery passes

A forger who regenerates the file with the bank's own library and recomputes every balance passes every check. Only the bank can rule that out. Closing this needs bank-side verification, which is out of scope for bankstract.

### 4. A pymupdf re-save keeps the producer

Only tools that rewrite the producer string change it. A re-save through pymupdf, or any tool that copies the Info dictionary, leaves `unexpected_producer` silent. Candidates to close it: the trailer `/ID` pair, object numbering gaps, and unused objects left by an editor. None is tested yet. Measure each on raw statements and on re-saved copies before adding it.

### 5. A retyped amount in the same font and size

Reconciliation is the only check that fires, and only if the balances were not fixed too. No file signal is left. Nothing planned.

### 6. XLSX has only a writer check

Fonts, sizes and overlays apply to PDFs. For XLSX the checks are the writer name, reconciliation, day order and period. A cell edited in place inside a file that keeps the original writer name leaves no file signal. Candidate: compare the `created` and `modified` properties against the bank's pattern. opay's raw files set `created` years before `modified`, so this needs more samples (item 1) before it can be a rule.

### 7. Scanned or image-only statements

A statement with no text layer reaches `parse()` and fails there as `unparseable`. No forensic check runs on the image. Out of scope until the OCR fallback exists.

## Verification

### 8. Three checks are not mutation-tested

Breaking each of the producer, font, overlay, revision, mod-date and XLSX checks fails its tests. `font_size_outlier`, `date_out_of_order` and `date_outside_period` were not broken on purpose after the code settled. Do it once and record the result here.

### 9. `date_outside_period` depends on the parser

It fires only when the parser fills `statement_period_start` and `statement_period_end`. Check which of the four parsers do, and list the ones that don't. A parser that never fills them silently disables this check for its bank.

## Cost

### 10. Cost of `inspect()` on a large statement

Measured on raw statements, 2026-10-11:

| Bank    | Spans  | Fills | `parse` | `pdf_forensics` | `inspect` total |
| ------- | ------ | ----- | ------- | --------------- | --------------- |
| fbn     | 135    | 141   | 0.11s   | 0.02s           | 0.11s           |
| zenith  | 457    | 144   | 0.24s   | 0.01s           | 0.23s           |
| palmpay | 139    | 226   | 0.11s   | 0.01s           | 0.17s           |
| opay    | 12,180 | 6,078 | 4.04s   | 0.56s           | 4.55s           |

- **The integrity checks are cheap.** On the 58-page opay PDF the size and overlay checks take 0.03s together. `pdf_forensics` is the 0.56s: 0.20s in `get_texttrace`, 0.08s in `get_drawings`, the rest in Python loops over 172k glyphs. About 12% of the total.
- **Parse is the cost.** 4.04s of 4.55s. That is pdfplumber extraction, not new work. `convert()` pays it too.
- **The real problem was the second parse.** A caller who ran `convert()` or `parse()` and then `inspect()` parsed the file twice. 8s or more on a 58-page opay statement. Closed: `inspect(source, result=...)` reuses a `ParseResult` and skips the parse. Callers who don't pass one still pay it.
- **Not worth doing.** Trimming the Python loops in `pdf_forensics` would save about 0.1s and put RTL and rotated text at risk.
- **Out of scope here.** Speeding up opay's parse. That belongs to the parser, not to integrity.

## Deliberate false positive

### 11. A statement with an uncompressed embedded PDF reads as extra revisions

`incremental_update` counts every `startxref <offset>` section. A PDF attached uncompressed inside a statement carries its own, so a clean file raises an error signal and the CLI exits 2. No raw bank statement has an attachment.

This is kept on purpose. The obvious fix skips sections that sit inside a stream body. That trusts the file's own `/Length`, which a forger sets. A reader finds the last `startxref` from the end of the file and ignores stream boundaries, so a forged tail can sit inside a fake stream and drop out of the count. `tests/test_integrity.py` builds that file: the skip rule counts 1 revision where there are 2. A false positive is loud and the owner can inspect it. A miss is silent.

Revisit only with a rule that does not read structure the forger writes. For example, an allowlist of banks known to attach files.

## Cost of evasion

### 12. A stuffed page only earns a warning

A forger who adds over 2000 junk text runs or fills to a page switches the size and overlay checks off for it. `checks_skipped` fires as a `warn`, so a caller that only reads errors misses it. It stays a warning because a dense genuine page would otherwise exit 2. Real pages peak near 300 text runs and 200 fills across the four banks.

Close it once there are enough raw statements per bank to set the cap per bank, then raise the signal to an error for pages that pass a bank's own maximum by a wide margin.

### 13. A cover built from slivers

The cover check flags a fill that touches a tenth of one glyph. A forger can split a cover into pieces that each touch less than that, then stack enough of them to hide the glyph. It costs many fills per digit, and each one sits after the text it covers, which no real statement has. Close it by summing the covered area per glyph across fills, not testing each fill alone.

### 14. A forged column keeps its own size

`font_size_outlier` compares an amount with the other amounts in its column. A forger who retypes every amount in a column at one new size leaves a column that agrees with itself. The original column is gone, so nothing disagrees. Close it by comparing a column's size with the bank's known amount size, which needs a per-bank baseline from more raw statements (see item 1).

### 15. Isolation is opt-in, and its memory limit is Linux only

`inspect(isolate=True)` bounds any file with a time limit, which closes the form-XObject, Flate and repetition cases that the in-process content gate cannot see: a 62-byte page invoking a form of 100k runs is killed at the limit (`tests/test_isolate.py` builds it). What stays open:

- **Off by default.** A caller who forgets the flag is unprotected. A service taking uploads must pass it.
- **No memory limit on macOS or Windows.** macOS refuses `RLIMIT_AS` (`setrlimit` raises `current limit exceeds maximum limit`), and Windows has no equivalent. A runaway child there is bounded by the time limit alone, so it can use gigabytes for up to `timeout` seconds. Close it with a job object on Windows and a polling RSS check on macOS.
- **The Linux limit is untested here.** The test runs in CI on Ubuntu only. `memory_mb=2048` is a guess at what pymupdf needs in address space, so it could kill a genuine file or let too much through. Confirm on a real Linux run and tune it.
- **`parse()` and `convert()` are not isolated.** pdfplumber has the same exposure, and `inspect()` is protected only when it does its own parse inside the child. Isolate those entry points the same way, or document that callers must.
- **The in-process gates are first lines, not bounds.** `_MAX_PAGE_CONTENT` reads the page stream only and decodes a compressed one in full first. They stop the naive crafted file. They do not stop a determined one.

Not a gap, checked: a cover drawn as an annotation. pymupdf reports annotation appearance streams through `get_drawings`, so a white Square annotation over an amount is flagged.
