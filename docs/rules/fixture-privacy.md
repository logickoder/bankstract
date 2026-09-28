# Fixture privacy

Non-negotiable. Raw statements contain real account data. Before any fixture lands in git:

- Account number: `XXXXXXXXXX`
- Name: `Test User`
- Address: `Test Address`
- Phone / email: scrubbed
- BVN: never present

If an unredacted file is staged, halt and warn. Scrub it with `uv run bankstract redact <bank> <raw> <out>`, or regenerate the fixture from a synthetic source.

The rule covers all source and test code. No real personal names, business names, addresses, phone digits, or account numbers inline. Not in fixtures, assertion strings, or synthetic-PDF generators. Use obvious placeholders (`FOO`, `BAR`, `ACME`, `QUUX`, `Placeholder Lane`, `1111 2222`). Real values live only in `tests/<bank>/fixtures/_local/` (gitignored).
