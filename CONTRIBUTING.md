# Contributing

bankstract takes parsers, redactors, bug fixes, and docs. CLAUDE.md is the operating charter — read it before opening a PR. Highlights below.

## Gate

`ruff check` + `ruff format --check` + `pyright` (strict) + `pytest` must pass clean. The pre-commit hook runs the same checks. CI runs them again.

```bash
uv sync --all-extras
uv run pre-commit install
uv run pytest
```

## Adding a bank parser

1. Copy `src/bankstract/parsers/palmpay.py` to `src/bankstract/parsers/<bank>.py`. Implement `detect()`, `parse() -> ParseResult`, and optionally override `detect_confidence()` when your bank's markers may collide with another's.
2. Copy `src/bankstract/redactors/palmpay.py` to `src/bankstract/redactors/<bank>.py`.
3. Drop the raw statement at `tests/<bank>/fixtures/_local/statement.pdf` (gitignored) and run `uv run bankstract redact <bank> tests/<bank>/fixtures/_local/statement.pdf tests/<bank>/fixtures/sample.pdf`. Eyeball the output, commit only the redacted sample.
4. Add `tests/<bank>/test_parser.py` + `tests/<bank>/test_redactor.py`.

### Parser self-registration

Each parser self-registers by calling `register(MyParser())` at module top level. The CLI walks `all_parsers()` and synthesizes a `bankstract <bank>` command per registered parser via `cli.py`'s `for _bank in sorted(all_parsers()): _bank_command(_bank)`. Side-effect imports in `parsers/__init__.py` make every new parser file load on package import — adding a new file is enough; no central registry edit.

That import-side-effect choice trades a small static-analysis discoverability hit (IDE doesn't auto-suggest `bankstract <newbank>` until the package re-loads) for zero per-bank wiring. Acceptable for the plugin shape.

### Dual-fixture testing rule

Parser and metadata tests parametrize over BOTH `tests/<bank>/fixtures/sample.pdf` (committed, redacted) AND `tests/<bank>/fixtures/_local/statement.pdf` (gitignored, raw) when present. The raw fixture catches metadata-regex regressions that placeholder-only redacted samples silently pass. Skip pattern:

```python
LOCAL = Path(__file__).parent / "fixtures" / "_local" / "statement.pdf"
_FIXTURES = [
    pytest.param(SAMPLE, id="sample"),
    pytest.param(
        LOCAL,
        id="local",
        marks=pytest.mark.skipif(not LOCAL.exists(), reason="raw fixture absent"),
    ),
]
```

## Fixture privacy

CLAUDE.md directive 3 is load-bearing. No real personal names, business names, addresses, phone digits, BVN, or account numbers may appear inline in source, tests, or committed fixtures. Use obviously-fake placeholders (`FOO`, `BAR`, `ACME`, `QUUX`, `Placeholder Lane`, `1111 2222`). Raw statements live only in gitignored `_local/`.

## Reconciliation invariant

Every parser MUST produce rows where `prev.balance ± debit/credit == curr.balance` (banks with a balance column) OR where the parsed credit/debit sums match the statement header's totals (banks without). The CLI applies whichever invariants the parser supplied evidence for. Never weaken `reconcile.py` to make tests pass — the parser is wrong, not the invariant.

## Commits

Conventional Commits. CI release gate keys off the prefix:

- `feat:` → minor bump on PyPI collision
- `fix:` / `perf:` → patch bump
- `chore:` / `docs:` / `test:` / `refactor:` / `ci:` / `style:` / `build:` / `revert:` → no publish
- Anything else → workflow logs a warning and skips publish

Don't push or tag without owner approval. Diffs reviewed manually.
