## What and why

<!-- What does this change, and why is it needed? Link the issue if there is one. -->

## How it was tested

<!-- Commands you ran, and any test you added. -->

- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run pytest`

## Checklist

- [ ] All writes still go through `Store` (adapters do not write; redaction cannot be bypassed).
- [ ] No file is opened without a policy check; nothing is written outside priorlog's own directories.
- [ ] Fixtures and tests are synthetic. No real transcripts, names, emails, paths or secret-shaped
      strings (build those at runtime, as in `tests/test_redaction.py`).
- [ ] `CHANGELOG.md` has an `[Unreleased]` entry if users would notice the change.
- [ ] Docs updated (`docs/`, `SECURITY.md`) if behaviour, config or guarantees changed.
