# Workflow

## Human in the loop

Never run `git commit`, `git push`, `git tag`, or any publish step without an explicit owner command in the current turn. Edit, save, halt. The owner reviews diffs.

## Surgical edits

Change the function, parser, or test under request. Don't touch unrelated files, rewrite working parsers to improve them, or refactor across modules without an explicit refactor task.

## Commits

- Split work into logical commits (feature, refactor, docs, ci). Each passes the pre-commit hook on its own.
- Conventional Commits. `!` marks a breaking change.
- `publish.yml` reads only the newest commit's subject. `feat` / `fix` / `perf` (with or without `!`) publish. Anything else skips. Keep the version-bump commit last with a releasing prefix, e.g. `feat!: release 0.16.0`.

## Response format

- State change: terse confirmation with file + function name.
- Diagnosis: root cause in one to two sentences, then the fix.
- Refusal: cite the rule being upheld (e.g. "fixture not read. Read tests/fbn/fixtures/sample.pdf first").
- Direct, technical, honest. No "I've gone ahead and...", no "Let me know if...". Never apologize.
