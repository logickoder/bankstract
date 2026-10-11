# Integrity gaps

Open work on `inspect()` after the first cut. Closed items are listed once below and then dropped. Each open item says what is missing, why it matters and what closes it. Rules for the feature live in [rules/integrity](rules/integrity.md).

## Closed

- **Three checks not mutation-tested.** Breaking `font_size_outlier`, `date_out_of_order` and `date_outside_period` fails a test each.
- **`date_outside_period` depends on the parser.** All four parsers fill the statement period on raw statements, PDF and XLSX. Only the redacted fbn sample lacks it, a redactor effect.
- **Cost of `inspect()`.** Not a gap. The integrity checks cost 0.03s on the 58-page opay PDF and `pdf_forensics` about 0.4s. The parse dominates, and `result=` skips the second one. Isolation adds about 0.02s warm.
- **A cover built from slivers.** The cover check now adds the area each glyph has lost across every fill, so strips that are each under a tenth of a glyph still cross the line when stacked.

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

### 4. A pymupdf re-save keeps the producer, and only some banks give it away

Only tools that rewrite the producer string change it. A re-save through pymupdf, or any tool that copies the Info dictionary, leaves `unexpected_producer` silent. For fbn and opay the trailer `/ID` closes it: the two halves are equal in the raw statement and differ after a pymupdf re-save, and `id_changed` fires on that. What stays open:

- **Zenith and palmpay.** Their raw statements already write unequal halves, so a re-save changes nothing visible. Object numbering gaps and unused objects an editor leaves are untested candidates.
- **One raw file per bank.** The equal-halves rule rests on a single statement each (item 1). A bank that sometimes writes them unequal would warn on genuine files.
- **A tool that keeps the `/ID`.** An incremental save, or qpdf, leaves it alone. The incremental save is caught by `incremental_update`.

### 5. A retyped amount in the same font and size

Reconciliation is the only check that fires, and only if the balances were not fixed too. No file signal is left. Nothing planned.

### 6. XLSX has only a writer check

Fonts, sizes and overlays apply to PDFs. For XLSX the checks are the writer name, reconciliation, day order and period. A cell edited in place inside a file that keeps the original writer name leaves no file signal. Candidate: compare the `created` and `modified` properties against the bank's pattern. opay's raw files set `created` years before `modified`, so this needs more samples (item 1) before it can be a rule.

### 7. Scanned or image-only statements

A statement with no text layer reaches `parse()` and fails there as `unparseable`. No forensic check runs on the image. Out of scope until the OCR fallback exists.

## Deliberate false positive

### 11. A statement with an uncompressed embedded PDF reads as extra revisions

`incremental_update` counts every `startxref <offset>` section. A PDF attached uncompressed inside a statement carries its own, so a clean file raises an error signal and the CLI exits 2. No raw bank statement has an attachment.

This is kept on purpose. The obvious fix skips sections that sit inside a stream body. That trusts the file's own `/Length`, which a forger sets. A reader finds the last `startxref` from the end of the file and ignores stream boundaries, so a forged tail can sit inside a fake stream and drop out of the count. `tests/test_integrity.py` builds that file: the skip rule counts 1 revision where there are 2. A false positive is loud and the owner can inspect it. A miss is silent.

Revisit only with a rule that does not read structure the forger writes. For example, an allowlist of banks known to attach files.

## Cost of evasion

### 12. A stuffed page only earns a warning

A forger who adds over 2000 junk text runs or fills to a page switches the size and overlay checks off for it. `checks_skipped` fires as a `warn`, so a caller that only reads errors misses it. It stays a warning because a dense genuine page would otherwise exit 2. Real pages peak near 300 text runs and 200 fills across the four banks.

Close it once there are enough raw statements per bank to set the cap per bank, then raise the signal to an error for pages that pass a bank's own maximum by a wide margin.

### 14. A forged column keeps its own size

`font_size_outlier` compares an amount with the other amounts in its column. A forger who retypes every amount in a column at one new size leaves a column that agrees with itself. The original column is gone, so nothing disagrees. Close it by comparing a column's size with the bank's known amount size, which needs a per-bank baseline from more raw statements (see item 1).

### 15. Isolation is opt-in, and its memory limit is Linux only

`isolate=True` on `inspect()`, `parse()`, `convert()`, `detect()` and `redact()` bounds any file with a time limit, which closes the form-XObject, Flate and repetition cases that the in-process content gate cannot see: a 62-byte page invoking a form of 100k runs is killed at the limit (`tests/test_isolate.py` builds it). What stays open:

- **Off by default.** A caller who forgets the flag is unprotected. A service taking uploads must pass it.
- **No memory limit on macOS or Windows.** macOS refuses `RLIMIT_AS` (`setrlimit` raises `current limit exceeds maximum limit`), and Windows has no equivalent. A runaway child there is bounded by the time limit alone, so it can use gigabytes for up to `timeout` seconds. Close it with a job object on Windows and a polling RSS check on macOS.
- **The Linux limit is untested here.** The test runs in CI on Ubuntu only. `memory_mb=2048` is a guess at what pymupdf needs in address space, so it could kill a genuine file or let too much through. Confirm on a real Linux run and tune it.
- **The worker re-imports `__main__`.** A script piped on stdin (`python -`) is now refused before a worker starts, with a message that says why and that nothing was checked. A script with no `if __name__ == "__main__":` guard still fails inside the child, and the caller sees a `ResourceLimitError` whose message lists a main script that could not be re-imported beside a crash and out-of-memory. It cannot say which. Close it by having the child report a failed start.
- **Windows still spawns per call.** About 0.35s, and no memory limit. A fork server needs POSIX.
- **The Linux limit baseline moved.** A forked child already holds pymupdf and pdfplumber before it sets `RLIMIT_AS`, so the limit must clear that. `test_a_small_job_runs_under_a_real_memory_limit` checks it at 1024 MB on Ubuntu, and `memory_mb=2048` is a guess that CI has not yet confirmed.
- **The in-process gates are first lines, not bounds.** `_MAX_PAGE_CONTENT` reads the page stream only and decodes a compressed one in full first. They stop the naive crafted file. They do not stop a determined one.

Not a gap, checked: a cover drawn as an annotation. pymupdf reports annotation appearance streams through `get_drawings`, so a white Square annotation over an amount is flagged.

### 16. The cover check is tuned on four banks

`overlay_over_text` is an error: a fill at half opacity or more that touches a tenth of one glyph, drawn after the text. No later fill touches any text on the four banks' raw statements, so it spares them. Another generator, a print-to-PDF copy or an XLSX conversion may paint a stamp, watermark or row shade over text and raise an error on a genuine file (exit 2). Close it with raw statements from more sources, then tune per bank or demote a known-benign pattern.

### 17. The fork server is shared and long-lived

On Linux and macOS workers fork from a helper that imported bankstract once. Two consequences, neither tested here:

- `multiprocessing` has one fork server per process. If the host app or another library already started it, `set_forkserver_preload` is ignored. Workers still run and stay isolated, but each pays the cold import (about 0.35s) and the 0.02s figure does not hold.
- The helper keeps the code it imported. A host that reloads or upgrades bankstract in process keeps forking workers that run the old version. Restart the process, or close the helper, after a reload.

### 18. `recv_bytes` has no deadline once a message begins

The loop checks the deadline before each read, and the size cap bounds a message, but a read that has started waits for its bytes. The worker is our own code, which writes a whole message or dies, so a crafted file cannot make it send a partial one. A worker stopped from outside (SIGSTOP) mid-message would hold the parent. Close it with a non-blocking read loop against the deadline.

