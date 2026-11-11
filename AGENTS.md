# AGENTS.md

Instructions for AI coding agents working on this repository. Humans: see
[CONTRIBUTING.md](CONTRIBUTING.md), which has the same rules in more detail.

priorlog indexes coding-agent transcripts (Claude Code, Codex CLI, Pi, generic JSONL) into a
local SQLite FTS5 index, redacts secrets on the way in, and serves search with citations over
MCP and a CLI. It handles private data, so the invariants below matter more than style.

## Layout

```
src/priorlog/
  cli.py          argparse CLI: init, sync, search, read, sessions, status, mcp, install-skill
  mcp_server.py   MCP server (stdio): search, read, sessions, status tools
  config.py       config file + env vars, DEFAULT_TOML, DEFAULT_DENY_PATHS
  policy.py       which files may be opened (roots/globs minus deny globs, symlinks resolved)
  redact.py       Redactor: built-in patterns, email, custom, optional high-entropy
  store.py        Store: the only writer. SQLite schema, redaction + deny_content on write
  sync.py         incremental sync engine, file lock, build_adapters()
  query.py        read side: search, read (incl. --source raw lines), sessions, status
  render.py       markdown output shared by CLI and MCP; the context LABEL
  adapters/
    base.py       Batch, Msg, SessionInfo, Tail, TurnBuilder, iter_lines, loads, dig
    claude.py     Claude Code CLI + subagents + forks + desktop local_*.json
    codex.py      Codex CLI rollouts
    pi.py         Pi sessions
    jsonl.py      user-mapped JSONL
skills/priorlog/SKILL.md   agent skill (packaged into the wheel as priorlog/skill/SKILL.md)
tests/                     pytest suite; tests/fixtures/ holds synthetic transcripts only
docs/                      architecture, configuration, usage, roadmap
DECISIONS.md               why things are the way they are; read before changing a design choice
```

## Invariants (never break these)

1. **All writes go through `Store`.** `Store.apply` and `Store.enrich_session` run the redactor
   and `deny_content` on every message, title, cwd, branch and resume command. Do not add another code
   path that writes to the database, and do not open the SQLite file from anywhere else.
2. **Adapters never write, and `Batch.carry` holds ids and offsets only.** `carry` is persisted
   unredacted (`files.carry`), so never put transcript text, paths or cwd in it. `parse()` returns
   a `Batch`; `post_sync()` may only call
   `store.enrich_session(...)`. Adapters do not import `sqlite3`.
3. **Policy check before opening any file.** The sync engine calls `policy.allowed(path)` before
   `parse()`. `discover()` only lists paths. Anything that opens a file outside that loop
   (`post_sync`, `query.raw_lines`) must check the policy itself first.
4. **Raw source lines are redacted too.** `query.raw_lines` re-checks the policy, applies
   `deny_content` and redacts before returning. Keep its caps (`RAW_MAX_LINES`,
   `RAW_LINE_CHARS`).
5. **priorlog never edits agent configs.** `init` prints MCP registration commands; it must not
   run them or touch `~/.claude.json`, `~/.codex/config.toml`, settings files or hooks.
6. **Nothing is written outside priorlog's own config and data dirs** (and the skill dir that
   `install-skill` is explicitly asked to write). `tests/test_isolation.py` enforces this with a
   byte-for-byte snapshot of a fake HOME seeded with another memory tool's files.
7. **Local only.** No network calls, no sign-in tokens, no cloud sources. The index file is
   created with mode `0600`.
8. **Every MCP result starts with `render.LABEL`.** Retrieved text is context, not instructions.
9. **Citations stay exact.** `Msg.line_start`/`line_end` must be the real 1-based lines the
   message came from; `tests/test_citations.py` re-reads them from disk.

## Before you finish

Run all three and make sure they pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Add a `CHANGELOG.md` entry under `[Unreleased]` for user-visible changes, and update `docs/`
when behaviour, config keys or CLI flags change. Keep tests few and meaningful: one test that
exercises a real path end to end beats several that restate the implementation.

## Fixtures and privacy

- Fixtures are synthetic. Never copy a real transcript into the repo, and never paste content
  from the user's own sessions into code, tests, docs or commit messages.
- No real names, emails, hostnames or home paths. Use `/work/demo-app`-style paths and invented
  ids.
- Never write a literal secret-shaped string. Build them at runtime (split prefixes, seeded
  random bodies) as `tests/test_redaction.py` does, so the gitleaks scan stays clean.
- When testing the CLI by hand, use a throwaway `HOME`, or set `PRIORLOG_CONFIG` and
  `PRIORLOG_HOME` to a temp dir.

## Adding a harness adapter

1. `src/priorlog/adapters/<name>.py`: subclass `Adapter`, set `harness = "<name>"`, implement
   `discover()` (list only) and `parse(path, offset, line, carry) -> Batch` using `iter_lines`,
   `loads`, `batch.session(...)`, `Msg` and `TurnBuilder` (`flush()` before user messages,
   `finish()` at the end). Count unknown line types in `batch.unknown_types`; never raise on them.
2. `config.py`: add `<name>_roots` to `Config`, **include it in `Config.roots`** (otherwise the
   policy denies every file), read it with `harness_roots("<name>")` in `parse()`, and add a
   `[sources.<name>]` section to `DEFAULT_TOML`.
3. `sync.py`: append the adapter in `build_adapters()`. `cli.py`: list its roots in `cmd_init`.
4. Tests: a synthetic fixture under `tests/fixtures/<name>/`, its root in
   `tests/conftest.py::write_config`, and one test in `tests/test_adapters.py` asserting roles,
   exact text and exact line ranges.
5. Docs: `docs/configuration.md` (keys, default root) and `CHANGELOG.md`.

## Do not

- Commit, push or tag unless the user asks.
- Add runtime dependencies (the only one is `mcp`) without the user's agreement.
- Weaken a redaction pattern, a deny rule or the policy to make a test pass.
