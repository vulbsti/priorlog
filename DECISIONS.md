# Decisions

Decisions made while building priorlog, with the reason for each. The owner was not
available for questions, so every call below was made by the building session and can be
revisited.

## D1. Name: `priorlog`

- Checked on 2026-11-05: PyPI `priorlog` → 404 (free), npm `priorlog` → 404 (free), GitHub
  repository search for `priorlog` → 1 unrelated hit (`PriorLogic`, empty description, 0 stars).
- Rejected after checking:
  - `sessiondex`: an active project in exactly this niche (windviki/sessiondex).
  - `sessionsift`: PyPI/npm free, but `LanceSandino/sessionsift` is a session-analysis MCP tool for
    Codex and Claude Code. Same niche, so the name was dropped before the first commit.
  - `backtrail`, `tracebook`, `agentdex`, `cairn-memory`: taken on npm or PyPI, or crowded on GitHub.
- Meaning: "the log of prior sessions". It is also what an agent should check before asking the
  user something they already answered.

## D2. A new codebase that ports the best of both sources, not a merge of either

- **A private predecessor tool**, the owner's earlier session-search tool (about 2k LOC, runs
  daily), supplied the Claude Code reader: fork dedup, turn merging, slash-command and relay
  handling, desktop `local_*.json` linkage. It also supplied the FTS5 trigram schema and the
  search ranking idea.
- **A private agent-broker prototype** (5.3k LOC) supplied the broker idea: redaction and path
  policy enforced centrally, adapters for Codex, Pi and generic JSONL, and line locators on every
  record.
- The broker prototype also carries a daemon, a socket protocol, tmux control, a research worker
  and many compatibility aliases. None of that is needed for search-with-citations, and all of it
  adds attack surface. Rewriting the core around one choke point (`Store`) gave about 1.6k LOC
  with the same guarantees and fewer moving parts.
- Real-data parity check (2026-11-05, read-only, index in a scratch dir): the predecessor
  indexes 1,767 messages from the laptop's Claude Code sessions, and priorlog indexes 1,783. Investigating that gap
  found and fixed a dropped-relay bug in the port (see `docs/verification/real-data-smoke.md`).

## D3. Local sources only

- The claude.ai `/v1/code/*` cloud adapter in the predecessor tool is undocumented and needs the
  user's sign-in token. It is **excluded** (project criterion 2).
- The desktop `local_*.json` files also contain cloud and Remote Control ids (`bridgeSessionIds`,
  `remoteControlSpawn`). priorlog ignores them, and a test asserts that no `cse_` id reaches the index.
- Harness credential files (`.credentials.json`, `auth.json`, `.env`, keys, and similar) are on a
  built-in deny list. They are never opened, even under a configured root.

## D4. Redaction runs in the store, at write time and again at read time

- Every message, title, cwd and resume command passes through `Redactor` inside `Store` before it
  is written. `read --source` re-reads raw lines from disk, re-checks the path policy and redacts
  again. No adapter or client can bypass it.
- Emails are redacted by default. Personal data is the most common leak in transcripts.
- High-entropy masking is **off** by default. It masks long mixed-case strings, which also hides
  base64 data and generated identifiers people search for. Lower-case hex such as commit hashes
  is not affected either way. It can be turned on in config.
- `KEY=value` masking only fires when the key *ends* in a secret word (`API_KEY`, `db_password`)
  and the value is not purely numeric. That stops `max_tokens: 100000` and `tokenizer =` from being
  masked.

## D5. Search: SQLite FTS5 trigram, no embeddings in v0.1

- Zero extra dependencies, substring semantics (`deploy` finds `deployment`), works for any
  language, and is fast enough at 50k messages (see `docs/benchmarks.md`).
- Embeddings would need a model download and would make "every claim backed by a benchmark"
  harder. They are listed in `docs/ROADMAP.md`. episodic-memory is the better choice if semantic
  search is the main need, and the README says so.

## D6. Incremental sync without a daemon

- Each file keeps a byte offset, line number, inode and size. An unchanged file costs one `stat`.
- The last assistant turn stays "open" and is re-read next time, because Claude Code writes one line
  per content block.
- MCP `search`/`read` run a quick sync first when the index is older than `auto_sync_seconds`
  (default 300). No systemd timer is needed, so there is nothing that could clash with an existing session-history tool's timers.

## D7. priorlog never edits agent configs

- `priorlog init` prints the `claude mcp add` / `codex mcp add` commands instead of running them.
  Installing priorlog therefore cannot change another tool's MCP registration or anything else in
  `~/.claude.json` (project criterion 7, `tests/test_isolation.py`).
- `install-skill` writes only `~/.claude/skills/priorlog/SKILL.md` (or the Codex equivalent) and
  refuses to overwrite without `--force`.

## D8. Platforms: Linux and macOS, Python 3.11+

- The sync lock uses `fcntl`, which Windows does not have. Windows support is a roadmap item.
- Python 3.11 is the minimum for stdlib `tomllib`.
- CI runs on ubuntu-latest and macos-latest.

## D9. License: Apache-2.0

This is the standard's default. Nothing argued against it.

## D10. Commit identity

Commits use `vulbsti <29302849+vulbsti@users.noreply.github.com>`, the GitHub noreply address, so
no personal email appears in the history.

## D11. Learning-mode "your turn" prompts were skipped

The session ran in a learning output style that normally pauses for the human to write small
pieces of code. The owner said they would not answer questions, so no such pauses were made.

## D12. One pushed commit contains personal strings; history rewrite left to the owner

Commit `1251965` (pushed to the private repo on 2026-11-05) quoted the owner's work-account handle,
employer domain and home path inside `VERIFICATION.md`, in the rows describing the privacy grep.
The final audit caught it. The next commit (`23f6275`) removed them from `VERIFICATION.md` but
repeated them in the first version of the BLOCKED.md B2 recipe, and `80c36df` replaced that with
placeholders. Every other commit is clean (`git grep` over all reachable commits); the tree has
been clean since `80c36df`. Replacing that commit needs a force-push, which the
build session's permission check refused ("Git Destructive"), so it was not attempted another way.
The repo is private and holds only this session's commits. **Before the repo goes public**, the
owner should replace the history with a fresh single-commit history. That is being done by
recreating the repo from one clean commit (BLOCKED.md B2, resolved).

## D13. The migration guide for the predecessor tool was moved out of the repo

Project criterion 9 asked for a migration guide from the owner's earlier private session-search
tool. It was written, but it describes an unpublished tool and the owner's own setup, so it was
moved out of the repo before publishing and is kept as a private note.

## D14. Transcript paths are stored as written

`files.path`, which appears in every citation's `source` locator, is stored unredacted, because it
is what `read --source` re-opens. For Claude Code, the project folder name encodes the working
directory. `deny_content` therefore does not hide a word that appears in a folder path. To keep a
whole project out, use `deny_paths`, which stops the file from being opened at all. This is
documented in SECURITY.md and docs/configuration.md.
