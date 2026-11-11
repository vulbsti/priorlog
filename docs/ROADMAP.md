# Roadmap

priorlog 0.1.0 covers local search with citations over Claude Code, Codex CLI, Pi and mapped
JSONL logs. The direction stays the same: local only, every hit citable, redaction enforced in
one place. Items here are proposals, not promises. Open an issue before starting anything large.

## Near term

- **Windows support.** Replace the `fcntl` sync lock with a portable one and run CI on
  `windows-latest` (see the good first issue below). Path handling already goes through
  `pathlib`.
- **Pruning.** Transcripts deleted from disk currently stay in the index until it is rebuilt.
  Add a way to drop them (good first issue below).
- **More harnesses.** OpenCode and Cursor are the most requested. Both keep sessions in SQLite
  rather than JSONL (see `docs/research/alternatives-2026-11-05.md` for OpenCode), so they need an
  adapter that reads a database read-only and maps rows to stable line-like locators. That is a
  design change to the citation format, to be agreed in an issue first.
- **Optional semantic search.** An opt-in embeddings column next to FTS5, behind an extra
  (`priorlog[embeddings]`), with search results still carrying the same citations. It must stay
  off by default, work offline after a one-time model download, and come with a benchmark that
  shows it beats trigram search on real recall questions (DECISIONS.md D5).
- **More redaction formats.** Formats seen in real transcripts that 0.1.0 does not mask: npm
  tokens (`npm_…`), Google OAuth access tokens (`ya29.…`) and command-line flags such as
  `--password <value>` or `--token <value>`. Each needs a kind, a runtime-built test value and a
  check that ordinary text (for example `--password-file path`) survives.
- **Better freshness signals.** Report per-harness last-seen times and stale roots in
  `priorlog status`.
- **Packaging.** Publish to PyPI once the name and API settle, so `uv tool install priorlog`
  works.

## Not planned

- Cloud sources (claude.ai, `/v1/code/*`, hosted chat exports fetched over the network) and
  anything that needs a sign-in token. See DECISIONS.md D3.
- A daemon or background service. Auto-sync on query covers freshness.
- Editing agent configs or installing hooks automatically.

## Good first issues

Each of these is small, self-contained and testable with the existing fixtures. Read
[CONTRIBUTING.md](../CONTRIBUTING.md) and [AGENTS.md](../AGENTS.md) first.

### 1. Relative times for `--after`, `--before` and `--since`

- **Why:** `--since 7d` is what people type; today only ISO strings work, and anything else
  silently compares as a string and returns nothing useful.
- **Files:** `src/priorlog/query.py` (a helper used by `_filters()` and `sessions()`),
  `src/priorlog/mcp_server.py` (docstrings), `docs/usage.md`.
- **Acceptance:**
  - `7d`, `12h`, `30m`, `2w` (and `today`, `yesterday`) are converted to an ISO UTC timestamp
    relative to now; ISO input is passed through unchanged.
  - Works for the CLI and the MCP `after`, `before` and `since` parameters.
  - An unparseable value raises `QueryError` with a clear message (exit code 2) instead of
    returning an empty result.
  - One test in `tests/test_citations.py` covering a relative value and an invalid one.

### 2. `priorlog prune` for deleted transcripts

- **Why:** a transcript deleted from disk keeps its messages in the index and keeps showing up
  in search, with a `read --source` that fails with "source file no longer exists".
- **Files:** `src/priorlog/store.py` (a `prune_missing()` method), `src/priorlog/cli.py` (new
  subcommand with `--dry-run` and `--json`), `docs/usage.md`.
- **Acceptance:**
  - For every `files` row whose path no longer exists, delete its messages (the FTS trigger
    handles the index), the `files` row, sessions left without messages, and links that point at
    removed sessions.
  - Uses only `stat`/`exists`; never opens a file.
  - Runs under the same file lock as `sync`.
  - `--dry-run` reports what would be removed without changing anything.
  - A test that syncs the fixtures, moves one transcript away, prunes, and checks search no
    longer returns it while other sessions are untouched.

### 3. Portable sync lock (first step to Windows)

- **Why:** `sync._lock()` uses `fcntl.flock`, which does not exist on Windows, so priorlog
  cannot even import `sync.py` there.
- **Files:** `src/priorlog/sync.py`, `.github/workflows/ci.yml` (add `windows-latest` to the
  test matrix), `pyproject.toml` (classifier), `tests/test_isolation.py` (the `0o600` mode check
  needs a POSIX-only guard).
- **Acceptance:**
  - Use `msvcrt.locking` on Windows and `fcntl.flock` elsewhere, with no new dependency.
  - Two concurrent `sync()` calls still serialise (test with two threads or processes).
  - The suite passes on ubuntu, macos and windows in CI.

### 4. Redaction pattern for Google Cloud service-account keys

- **Why:** a pasted service-account JSON contains `"private_key": "-----BEGIN PRIVATE KEY-----\n..."`
  with literal `\n` escapes, plus `"private_key_id"` (40 hex characters). The PEM rule catches the
  key body and email redaction catches `client_email` (when `emails = true`), but the
  `private_key_id` value is not masked by any rule.
- **Files:** `src/priorlog/redact.py`, `tests/test_redaction.py`, `docs/configuration.md`
  (kinds table).
- **Acceptance:**
  - A new kind `gcp_service_account` masks the `private_key_id` value when it appears in a
    service-account JSON (next to `"type": "service_account"` or a `private_key` field).
  - Ordinary 40-character hex strings such as git commit hashes are not masked (the existing
    test already asserts this for one hash).
  - The test builds the fake service-account JSON at runtime (split prefixes, seeded random
    body) so gitleaks stays clean.

### 5. Shell completion

- **Why:** subcommands, `--harness` values and `--role` choices are easy to mistype.
- **Files:** `src/priorlog/cli.py` (a `completion {bash,zsh,fish}` subcommand that prints a
  script generated from `build_parser()`), `docs/usage.md`.
- **Acceptance:**
  - `priorlog completion bash` prints a script that completes subcommands and their flags, and
    the fixed values of `--role` and `--target` (`claude`, `codex`).
  - No new runtime dependency; the script is derived from the argparse parser, so new flags
    appear automatically.
  - Documented install lines for bash, zsh and fish.

### 6. Show disabled harnesses in `priorlog init`

- **Why:** a harness with `enabled = false`, or a section with no `roots`, simply vanishes from
  the `init` output, which makes "why is Codex not indexed?" hard to answer.
- **Files:** `src/priorlog/config.py` (keep which harnesses were disabled, or expose the raw
  `[sources]` table), `src/priorlog/cli.py` (`cmd_init`).
- **Acceptance:**
  - `init` prints one line per known harness: its roots with `found` / `not found (skipped)`,
    or `disabled (enabled = false)`, or `no roots configured`.
  - Configured JSONL sources are listed with their globs and the number of matching files.
  - A test in `tests/test_isolation.py` or a new small test asserting the output for a config
    with one disabled harness.

### 7. Re-apply deny rules and new redaction patterns to existing rows

- **Why:** redaction and `deny_content` run when a message is written. Adding a pattern or a
  deny rule later does not touch rows that are already indexed. Today the only fix is deleting the
  index and syncing again.
- **Files:** `src/priorlog/store.py` (a `reapply_rules()` method that re-redacts `messages.text`
  and session titles and drops denied rows; it must go through the same `_clean`/`_denied`
  helpers), `src/priorlog/cli.py` (`priorlog sync --reapply`).
- **Acceptance:**
  - After adding a `deny_content` rule and running `priorlog sync --reapply`, a matching
    message is gone from search and from the FTS index (`integrity-check` passes).
  - A test covers both a new custom pattern and a new deny rule.

### 8. Highlight matches in `read` output

- **Why:** `search` marks matched words with «», but `read <cite>` shows the cited message
  without them, so in a long message the reader has to find the match again.
- **Files:** `src/priorlog/query.py` (`read()` takes an optional `highlight` list),
  `src/priorlog/cli.py` / `mcp_server.py` (pass the query terms through when known),
  `src/priorlog/render.py`.
- **Acceptance:**
  - `priorlog read <cite> --highlight "token bucket"` wraps matches in «».
  - Without `--highlight`, the output is unchanged.

### 9. `--json` for `priorlog init`

- **Why:** `init` prints which roots were found as plain text, and setup scripts must parse it.
- **Files:** `src/priorlog/cli.py` (`cmd_init`).
- **Acceptance:**
  - `priorlog init --json` prints `{"config": ..., "roots": [{"harness", "path", "found"}], "db": ...}`.
  - The plain-text output is unchanged.
