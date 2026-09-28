# Testing

- Every parser ships at least one redacted fixture at `tests/<bank>/fixtures/sample.{pdf,xlsx}`.
- Register every bank in `tests/_fixtures.py`: paths in `FIXTURES`, expected report in `RECONCILIATION`. Cross-bank tests (reconciliation, zero-amount rows, `has_time`, CLI byte-identity, detection) read it from there. Add the bank's time precision to `_PRECISION` in `tests/test_fixture_invariants.py`.
- Read fixtures through the cached `parsed(bank, path)`. Parses take 0.3-4s each.
- Parser and metadata tests parametrize over the committed sample AND `_local/statement.*` when present. Skip the local case with `pytest.mark.skipif(not path.exists())` so CI stays green. The raw fixture catches metadata-regex regressions that placeholders pass.
- Test format-version detection against every version you have.
- Each parser has a `tests/<bank>/test_redactor.py`: synthetic-PDF round trip plus a PII leak sweep.
- No mocking of `pdfplumber` / `camelot` / `pytesseract` / `openpyxl`. Tests run on real files.
