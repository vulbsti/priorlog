# Changelog

All notable changes to priorlog are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-06

First release.

### Added

- **Harness adapters**
  - Claude Code CLI transcripts (`~/.claude/projects/<project>/<uuid>.jsonl`): consecutive
    assistant lines merged into one message per turn, tool calls reduced to `[tool: name]`
    markers, tool outputs and injected context (system reminders, hook output, task
    notifications) dropped, slash commands kept as `/name args`, messages relayed from other
    sessions kept with role `system`.
  - Claude Code subagents (`<uuid>/subagents/agent-<id>.jsonl`) as their own sessions, titled
    from `agent-<id>.meta.json` and linked to the parent (`subagent` link).
  - Resumed and forked Claude Code sessions: copied parent history is stored once and recorded
    as a `fork` link.
  - Claude desktop app linkage: `local_*.json` files supply the session title, desktop id and
    cwd for the CLI session they point at. Cloud and Remote Control ids in those files are
    ignored.
  - Codex CLI rollouts (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`), current envelope
    format and the older unwrapped format; `event_msg` duplicates, reasoning, developer
    instructions and `<environment_context>` blocks are not indexed.
  - Pi sessions (`~/.pi/agent/sessions/--<cwd>--/<timestamp>_<uuid>.jsonl`); thinking blocks
    and tool results are not indexed.
  - Generic JSONL sources (`[[sources.jsonl]]`) mapped field by field with dotted paths
    (`text`, `role`, `session`, `timestamp`, `role_map`).
- Performance: search ranks and limits inside SQLite. The first sync into an empty index
  rebuilds the FTS index once instead of row by row. The path policy caches per-directory deny
  verdicts (see `docs/benchmarks.md`).
- MCP tools are annotated read-only / idempotent / closed-world (`readOnlyHint`), so clients
  such as `codex exec` can call them without an approval prompt.
- Relative paths in a config file resolve against the file's folder; `examples/demo/config.toml`
  runs priorlog on the bundled synthetic sample transcripts.
- Untitled sessions are named after their first *indexed* user message (set by the store, so a
  message dropped by `deny_content` can never leak through a title).
- **Broker**: all writes go through `Store`, which applies the path policy, redaction and
  `deny_content` rules, so no adapter or client can bypass them.
  - Redaction of private keys, Anthropic, OpenAI, GitHub, GitLab, AWS, Google, Slack, Stripe
    and Hugging Face tokens, JWTs, bearer and basic auth, URL credentials, cookie headers,
    secret `KEY=value` assignments and email addresses, as `[REDACTED:<kind>]`. Optional
    high-entropy masking and custom patterns.
  - Built-in deny list for credential files (`.ssh`, `.aws`, `.env`, `auth.json`,
    `.credentials.json`, `*.pem`, `*.key` and more), checked on the resolved path and every
    parent directory; extendable with `policy.deny_paths`.
  - Per-kind redaction counts, dropped-message and malformed-line counters; values are never
    stored.
- **Incremental sync** with no daemon: per-file byte offset, line number, inode and size; an
  unchanged file costs one `stat`; a growing assistant turn is re-read and replaced; a
  truncated or replaced file is re-indexed; a file lock serialises concurrent syncs.
- **Search**: SQLite FTS5 trigram index (substring matching in any language, quoted phrases,
  a substring fallback for words under 3 characters), filters for harness, project, role and
  time range, at most two hits per session.
- **Citations**: every hit has a `cite` (`<session>#<seq>`), harness, timestamp and a
  `path:Lstart-Lend` locator. `read` opens a cite with surrounding messages or pages through a
  whole session; `read --source` shows the original transcript lines, re-checked by the policy
  and redacted again.
- **CLI**: `init`, `sync`, `search`, `read`, `sessions`, `status`, `mcp`, `install-skill`, with
  `--json` output for scripting.
- **MCP server** on stdio with `search`, `read`, `sessions` and `status` tools, annotated as
  read-only. Results start with a context label, and the index syncs itself when it is older than
  `index.auto_sync_seconds` (default 300).
- **Agent skill** (`skills/priorlog/SKILL.md`), installed with
  `priorlog install-skill --target claude|codex|<dir>`.
- Index stored at `~/.local/share/priorlog/index.sqlite3` with mode `0600`; config at
  `~/.config/priorlog/config.toml`; both overridable with `PRIORLOG_HOME`, `PRIORLOG_CONFIG` and
  the XDG variables.
- Linux and macOS support, Python 3.11 to 3.13; CI on both platforms.

[Unreleased]: https://github.com/vulbsti/priorlog/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vulbsti/priorlog/releases/tag/v0.1.0
