## What

<!-- One line describing the change -->

## Why

<!-- Motivation. Link to issue if applicable. -->

## Checklist

- [ ] `uv run ruff check src tests` clean
- [ ] `uv run ruff format --check src tests` clean
- [ ] `uv run pyright src tests` clean (strict mode)
- [ ] `uv run pytest` green
- [ ] CHANGELOG.md updated under unreleased section
- [ ] README Public API block updated if surface changed
- [ ] No real bank PDFs in tests/fixtures/ (redactor used or synthetic)
- [ ] AST audit (`test_no_bare_parse_error_without_justification`) green
- [ ] Conventional commit subject: `feat:` / `fix:` / `chore:` / etc.

## Notes
