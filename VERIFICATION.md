# Verification

This file maps every requirement (the shared OSS release standard, sections A to G, and the nine
priorlog project criteria) to evidence: a command with its output, or a file. It was last
re-checked on 2026-11-06. The final checks below say which commit each check ran on.

Status key: **PASS** means met, with the evidence shown. **OPEN (owner)** means it needs an
action this session was not allowed to take, which is listed with exact commands in
[BLOCKED.md](BLOCKED.md).

## Project criteria

### 1. Adapters for Claude Code (+ desktop `local_*.json`), Codex CLI, Pi, and user-mapped generic JSONL, each with a synthetic fixture and a test — PASS

| Adapter | Code | Fixture | Test |
| --- | --- | --- | --- |
| Claude Code CLI, subagents, forks | `src/priorlog/adapters/claude.py` | `tests/fixtures/claude/projects/` | `tests/test_adapters.py::test_claude_transcript_subagent_fork_and_desktop` |
| Claude desktop `local_*.json` linkage | `ClaudeAdapter.post_sync` | `tests/fixtures/claude/desktop/u1/w1/local_….json` | same test: desktop title, `desktop_id`, no `cse_` ids |
| Codex CLI | `src/priorlog/adapters/codex.py` | `tests/fixtures/codex/sessions/2026/10/02/rollout-….jsonl` | `test_codex_rollout` |
| Pi | `src/priorlog/adapters/pi.py` | `tests/fixtures/pi/sessions/--work-demo-api--/….jsonl` | `test_pi_session` |
| Generic JSONL (user-mapped) | `src/priorlog/adapters/jsonl.py` | `tests/fixtures/jsonl/supportbot.jsonl` | `test_generic_jsonl_mapping` |

The fixtures are synthetic: invented ids, `/work/demo-app` paths and `example.com` addresses. The
adapters were also run against the maintainer's real transcripts, read-only and with aggregate
counts only. The result matched the predecessor tool's counts within 1%, and that check found one
bug, now fixed. See [docs/verification/real-data-smoke.md](docs/verification/real-data-smoke.md).

### 2. The claude.ai `/v1/code/*` cloud adapter and anything that uses sign-in tokens are excluded; local sources only — PASS

```
$ grep -rnE "v1/code|urllib|http\.client|import requests|httpx|import socket|claude\.ai/api" src/priorlog
(no output: grep exit status 1)
$ grep -rn "credentials.json\|auth.json" src/priorlog
src/priorlog/config.py:23:# harnesses themselves (Claude's .credentials.json, Codex's auth.json) are on this list, ...
src/priorlog/config.py:39:    "*/.credentials.json",
src/priorlog/config.py:40:    "*/credentials.json",
src/priorlog/config.py:41:    "*/auth.json",
```

Those filenames appear only in the built-in **deny** list (`DEFAULT_DENY_PATHS`), which stops
them from being opened.

- No module makes network calls. The only runtime dependency is `mcp`, used for its stdio server.
- The harnesses' own credential files are on the built-in deny list, so they are never opened.
- `test_claude_transcript_subagent_fork_and_desktop` asserts that the cloud ids in the desktop
  file (`bridgeSessionIds`, `remoteControlSpawn`) never reach the index.
- Recorded in [DECISIONS.md](DECISIONS.md) D3.

### 3. Redaction and deny rules are enforced in the broker, tested on API keys, bearer tokens, emails and private-key blocks, with documented config — PASS

- **Enforcement point:** `Store.apply` and `Store.enrich_session` in `src/priorlog/store.py` are the
  only writers. They redact every message, title, cwd, branch and resume command, and drop
  `deny_content` matches, testing each text block as well as the whole message, and titles at
  full length. Transcript-supplied session ids and timestamps are stored only when they are
  plainly ids and ISO times (`Store.safe_id`/`safe_ts`); anything else becomes a stable
  `h-<sha256>` id or is dropped. Unfamiliar line-type names are recorded only when they look like
  type names. `query.raw_lines` re-checks the policy, withholds lines whose decoded values match
  `deny_content` (with the same per-block rule as the store), and redacts the decoded JSON values
  for `read --source`. `files.carry` and desktop `local_…` ids get the same id treatment as session
  ids. A resume command is dropped when its cwd is denied. File paths are the one field stored
  as written (DECISIONS D14).
- **Tests** in `tests/test_redaction.py`:
  - `test_redactor_masks_each_kind_and_leaves_ordinary_text`: Anthropic, OpenAI, GitHub and AWS keys,
    a JWT, a bearer token, an email, an OpenSSH private-key block, an env assignment and URL
    credentials are all masked. A commit hash, `max_tokens: 100000` and `tokenizer =` survive.
  - `test_secrets_never_reach_the_index_search_or_source_view`: plants secrets in a transcript and
    syncs. The raw bytes of the SQLite file and its WAL don't contain them, searching for them
    returns nothing, the snippet and the `--source` view show placeholders, and the title is
    redacted.
  - `test_deny_rules_drop_messages_and_files`: covers `deny_content`, a user `deny_paths` rule, and
    transcripts inside `.ssh/` and `.env/` directories under a configured root (all 3 counted as
    denied, none searchable). It also checks that a dropped message cannot become a session
    title.
  - `test_deny_content_also_covers_titles_and_desktop_metadata`: an `ai-title` and a desktop
    `local_*.json` title that match `deny_content` are never stored. A transcript blocked by
    `deny_paths` gets no session row from its desktop metadata. Both came from the final audit.
  - `test_source_view_rechecks_policy`: a stricter policy blocks `read --source` on lines that were
    indexed earlier.
  - `test_bad_config_values_are_reported_not_crashed`.
  - From the second and third audits:
    - `test_source_view_withholds_denied_lines_inside_a_cited_range`
    - `test_session_metadata_is_redacted_and_carry_holds_no_raw_text` (Codex cwd, branch, carry)
    - `test_a_missing_sources_section_turns_that_harness_off`
    - `test_transcript_ids_timestamps_and_blocks_cannot_carry_content`. This covers an
      email-valued JSONL session field, a key-valued timestamp, an IDE-prefixed `PRIVATE:`
      prompt, a second assistant part, a multi-line summary title, a secret-shaped line type and
      a JSON-escaped email in a raw line. None of them reach the SQLite bytes or the output.
  - From the fourth audit, the same test also covers Codex and Pi ids, a desktop id that hold
    content, a denied Claude cwd, and an `<ide_selection>` block in an allowed prompt.
  - **Mutation-checked:** each of these fixes was broken on its own while the tests ran, and the
    file was restored afterwards: the per-block deny split, the IDE-block strip, carry
    sanitising, desktop-id sanitising, dropping the resume command with a denied cwd, and the
    decoded-value deny check in `read --source` and its per-block rule, the full-length title
    check, dropping the resume command for a hashed id (both the transcript path and the desktop
    path), the deny check on line-type names, the token-rule lookbehind that catches a token
    glued to `_` (reverted one rule at a time, for every token kind), and the id sanitising of
    `links` rows. In every case the suite failed. The round-3
    fixes `safe_id`, `safe_ts`, the line-type filter, full-length titles and decoded-value
    redaction were mutation-checked by the fourth audit.
- **Config docs:** [docs/configuration.md](docs/configuration.md) (`[policy]`, `[redaction]`, every
  redaction kind, the deny list) and [SECURITY.md](SECURITY.md) (threat model and limits).
- Secret-shaped test strings are generated at runtime with a seeded PRNG, so the repository
  contains none (gitleaks: see section B).

### 4. Incremental sync, and a benchmark of 50k synthetic messages and search p50/p95 published in `docs/benchmarks.md` — PASS

- **Incremental:** byte offset, line number, inode and size per file, plus the open-tail re-read
  (`src/priorlog/sync.py`, `Store.rewind_tail`). Tests in `tests/test_sync.py`:
  - a second sync is a no-op
  - appended lines are read once, and a growing assistant turn is replaced rather than duplicated
  - a partial last line waits for its newline
  - a rewritten file with a new inode is re-indexed
  - the FTS integrity check passes after a bulk rebuild followed by an incremental append
- **Benchmark:** `bench/generate.py`, `bench/run.py`, raw results in `bench/results/`, write-up in
  [docs/benchmarks.md](docs/benchmarks.md).

Final run at commit `e2ca2b5`. The results JSON (`bench/results/2026-11-06.json`) records
`"commit": "e2ca2b5", "src_dirty": false`, and `src/` is unchanged from there to the `v0.1.0` tag
(`git diff e2ca2b5 v0.1.0 -- src` is empty). The corpus has 55,255 indexed messages in 1,647 files
(347 MB), and the indexed count matched the generator's manifest in every repeat. 3 repeats,
medians, 1-minute load 2.4–2.7:

| Metric | Result |
| --- | --- |
| Cold full index | 21.8 s, 2,536 msgs/s, 34 MB peak RSS, 214 MB DB |
| No-op sync / append sync (+600 msgs) | 151 ms / 799 ms |
| Search, in-process, all 360 queries, p50 / p95 / p99 | **18.6 / 123 / 184 ms** |
| Search, CLI end to end, p50 / p95 | 78 / 137 ms |
| `read` of a citation, p50 / `read --source`, p95 | 0.1 ms / 8.2 ms |

Slow cases are published too: common terms take 86 ms p50 and short-term `LIKE` scans 119 ms p50.
`docs/benchmarks.md` has a before/after table at similar load. It shows the costs as well as the
gains: rare-term p50 went from 9.4 to 10.6 ms, and `read --source` p95 from 3.5 to 8.2 ms. It also
has a cross-check run at `80c36df` and a note on an intermediate version that was measured and
replaced. Reproduce: `uv run python bench/generate.py DIR && uv run python bench/run.py DIR`.

### 5. Every search hit carries a citation (session, harness, timestamp, line locator) that `read` can open — PASS

- `query._hit` returns `cite`, `session`, `harness`, `timestamp` and `locator` (`path:Lstart-Lend`).
- `tests/test_citations.py::test_every_hit_has_a_citation_that_read_opens` checks, for every hit:
  - all fields are present
  - `read(cite)` marks exactly one message as cited, with the same locator
  - `read(cite, source=True)` returns exactly lines `start..end`
  - those lines, re-read from the real file on disk, are the `user`/`assistant` lines
- The same round trip ran over MCP in `tests/test_mcp.py` and in the end-to-end runs under 6.

### 6. MCP end-to-end proof: headless `claude -p` with a throwaway HOME and only fixture data, plus `codex exec` — PASS (both)

- Script: [scripts/e2e_mcp.sh](scripts/e2e_mcp.sh). It builds a throwaway HOME containing only the
  fixtures and runs both CLIs under `env -i` with the priorlog MCP server as their only tool
  source.
- **When:** both runs were recorded on 2026-11-05 against the code committed in `c525f73`, which
  already had the `readOnlyHint` fix. Since then the MCP tool names, parameters and result format
  have stayed the same. Only broker internals (later audit fixes) and some output wording
  (plurals) changed. `tests/test_mcp.py` drives the same search → read-cite flow through a real
  stdio MCP client on every CI run, so the flow is checked on the tagged code.
- **claude** 2.1.318: [docs/verification/mcp-e2e-claude.md](docs/verification/mcp-e2e-claude.md)
  and the raw `mcp-e2e-claude.jsonl`. It called `mcp__priorlog__search` and then `read` with
  `source=true`, and answered "token bucket per API key in Redis…" citing
  `claude:aaaaaaaa-1111-4111-8111-000000000001` `#1` at `L3-L8`.
- **codex** 0.166.0: [docs/verification/mcp-e2e-codex.md](docs/verification/mcp-e2e-codex.md) and
  the raw `mcp-e2e-codex.jsonl`. It made `mcp_tool_call` items for `search` and `read`, and no
  shell calls. Same answer. It cited the same session and message `#1`, but gave the line as
  "line 8" (plus "line 2" for the request) rather than the full `L3-L8` range.
- The first codex run was refused with "requires approval". Annotating the tools
  `readOnlyHint=True` fixed it, and the re-run passed with no config override.
  `tests/test_mcp.py` asserts the annotation.
- **Auth:** copies of the CLIs' own login were placed in the throwaway HOME, without refresh
  tokens. They were truncated to 0 bytes after the run and the dirs moved to `~/proj/TRASH`. The
  transcripts were grepped for tokens, emails, ids and home paths before they were committed.

### 7. priorlog uses its own data dir and config, installing it changes nothing for an existing session-history tool, and a test proves it — PASS

- `src/priorlog/config.py`: config lives at `$PRIORLOG_CONFIG` or `~/.config/priorlog/config.toml`,
  and data at `$PRIORLOG_HOME` or `~/.local/share/priorlog/`. The index is created with mode `0600`.
- `tests/test_isolation.py::test_full_install_flow_leaves_other_tools_untouched`:
  1. Seeds a throwaway HOME with another memory tool's fake index, its systemd timer and
     service, its MCP entry in `~/.claude.json`, its `recall` skill and agent settings.
  2. Runs `init`, `sync`, `search`, `status` and `install-skill` as subprocesses.
  3. Asserts every file outside priorlog's own three dirs is byte-for-byte unchanged and that no
     new files appear.
  4. Also asserts the index is mode `0600`.
- **On the real machine:** the files were stat-ed and hashed before and after a real sync. The
  diff was empty (see `docs/verification/real-data-smoke.md`). priorlog never registers itself
  with an agent: `init` prints the `claude mcp add` command (DECISIONS D7). The fresh-user test
  confirmed the real `~/.claude.json` gained no priorlog entry.

### 8. A factual "Alternatives" section on claude-devtools, Claudescope, obra/episodic-memory and aichat session-search, written after reading their repos — PASS

- README section "Alternatives", with sources in
  [docs/research/alternatives-2026-11-05.md](docs/research/alternatives-2026-11-05.md).
  1. Each repo was cloned and read without running any of its code. The doc gives file-path
     evidence per claim, for example Claudescope's `packages/shared/src/redact.ts`, which is only
     applied on output.
  2. sessiondex was also covered, since it is in the same niche.
- The key claim (Claudescope's redaction is opt-in and output-only) was re-checked by hand in this
  session: `packages/server/src/agent/mcp.ts:213` says "Set redact: true …".
- The section says where each alternative is the better choice: semantic search, GUI, more
  harnesses.

### 9. A migration guide from the owner's earlier tool, documentation only, with no migration done — PASS

- Met by a private guide kept outside the repo, because the owner's tool is unpublished
  (DECISIONS D13).
- No migration was done: the earlier tool's files, timers and MCP entry were never touched, and
  its index was only opened `mode=ro` for the parity count. The newest mtimes in both source trees
  (the predecessor tool and the agent-broker prototype) predate this session (2026-11-05).

## OSS standard

### A. Repo and identity

| Item | Status | Evidence |
| --- | --- | --- |
| Own git repo at `~/proj/oss/priorlog`; name free on GitHub, PyPI and npm; choice recorded | PASS | DECISIONS.md D1: PyPI 404, npm 404, GitHub search has 1 unrelated hit. `sessiondex` and `sessionsift` were rejected as same-niche clashes. |
| Private GitHub repo under vulbsti, pushed | PASS | https://github.com/vulbsti/priorlog. `gh api repos/vulbsti/priorlog --jq .private,.visibility` gives `true` / `private`. The build session's own `gh repo create` was refused twice by the permission classifier, so the owner approved and created it (BLOCKED.md B1, resolved). `main` and `v0.1.0` are pushed with `GH_TOKEN=$(gh auth token -u vulbsti) git push`. |
| The second (work) GitHub account is never used, no `gh auth switch`, no work-domain author email | PASS | `git log --format='%an <%ae>' \| sort -u` gives `vulbsti <29302849+vulbsti@users.noreply.github.com>` only. Every `gh` call used `GH_TOKEN=$(gh auth token -u vulbsti)`. |
| No `Co-Authored-By` lines; commits at milestones | PASS | `git log --format=%B \| grep -ci co-authored` gives `0`. Commits are milestones (`git log --oneline`). |
| Not public and nothing published; publish steps written down | PASS | The repo is private, and nothing was published to PyPI, npm or any marketplace. Nobody was messaged. [RELEASE.md](RELEASE.md) has the go-public, release and PyPI commands. |

### B. Sources and privacy

| Item | Status | Evidence |
| --- | --- | --- |
| Sources read-only | PASS | Source-tree mtimes under criterion 9. Code was ported by reading, never by editing the originals. |
| The existing session-history tool, its timers and its data dir untouched | PASS | Criterion 7, and the before/after diff in `docs/verification/real-data-smoke.md`. |
| No personal data committed | PASS | The standard's privacy grep (home path, work email domain, owner's first name, any email address) over the tree (excluding `.git`, `.venv` and `uv.lock`) finds nothing except the noreply author and the fake `example.org`/`example.com` addresses in fixtures and tests. Fixtures are synthetic, real-data checks were aggregate-only, and their scratch index was deleted. |
| No personal strings in history | RESOLVED (2026-11-12) | Commit `1251965`, and the first version of the B2 recipe in `23f6275`, contained the owner's work handle, employer domain and home path. The repo is recreated from one clean commit of the current tree, and the old repo is kept private as `vulbsti/priorlog-history` (BLOCKED.md B2). |
| gitleaks over full history: 0 findings | PASS | `docker run --rm -v "$PWD:/r" zricethezav/gitleaks git /r` gives `no leaks found` (output under Final checks). |
| rm never used; deletions moved to `~/proj/TRASH` | PASS | Scratch indexes, temp homes and the old venv were all moved to `~/proj/TRASH/`. |

### C. Usable by other people

| Item | Status | Evidence |
| --- | --- | --- |
| One-command install; OS stated | PASS | README: `uv tool install git+https://github.com/vulbsti/priorlog` (or `pipx`, or `uv tool install .`). The git URL only works for the owner while the repo is private; the fresh-user test used the same command against a local clone. Linux and macOS, Python 3.11+. Verified: `uv build` then `uv tool install` into a clean tool dir prints `priorlog 0.1.0`, and the packaged skill installs. |
| Fresh-user test (README only, throwaway HOME) passes | PASS | [docs/verification/fresh-user.md](docs/verification/fresh-user.md): a README-only run at `e2ca2b5`, with the same `src/` and assets as the tag. The README differs only in the Performance numbers, which were updated after the run. Verdict "yes", 0 FAILs, nothing blocking. Known cosmetic notes, left as they are: `search --help` doesn't describe `--harness`/`--after`/`--before` (`docs/usage.md` does); the README's example path differs from the demo data's path; the demo `status` prints an unfamiliar-line-type line the README comment doesn't mention. Earlier runs at `c525f73`, `80c36df`, `264a894`, `9cc236c`, `92275e1` and `cdfca12` raised issues, and all were fixed. |
| Few meaningful tests; CI lint + tests green on the private repo | PASS | 33 tests, 10 of them one parametrized case per token kind (output below). `.github/workflows/ci.yml` runs ruff, then pytest on ubuntu-latest and macos-latest for Python 3.11, 3.12 and 3.13. Runs are under "Final checks". |
| Tag `v0.1.0`; `CHANGELOG.md` | PASS | `git tag` gives `v0.1.0`. [CHANGELOG.md](CHANGELOG.md). |

### D. Maintainable as an open-source project

| Item | Status | Evidence |
| --- | --- | --- |
| LICENSE (Apache-2.0) | PASS | `LICENSE`, the full text from apache.org. `pyproject.toml` has `license = "Apache-2.0"`. |
| README, CONTRIBUTING (dev setup, tests, release), CODE_OF_CONDUCT (Contributor Covenant), SECURITY | PASS | All present. CONTRIBUTING has "Development setup", "Tests" and "Releases (maintainer)". The Code of Conduct is Contributor Covenant 2.1. |
| `.github/ISSUE_TEMPLATE/` (bug and feature), PR template, CODEOWNERS (`@vulbsti`), Dependabot | PASS | `bug_report.yml`, `feature_request.yml`, `config.yml`, `pull_request_template.md`, `CODEOWNERS` (`* @vulbsti`), `dependabot.yml` (uv and github-actions). |
| `docs/architecture.md`, usage guides, `docs/ROADMAP.md` with ≥5 good-first-issue candidates | PASS | architecture, usage and configuration docs. ROADMAP has 9 scoped candidates, each with files and acceptance criteria. |
| `AGENTS.md` | PASS | Layout, 9 invariants, pre-finish commands, fixture/privacy rules, adapter recipe. |

### E. Visuals

| Item | Status | Evidence |
| --- | --- | --- |
| Hero image | PASS | `assets/hero.jpg`, 1600x640, 186 KB, generated with gpt-6-luna via `codex exec`. Prompt, candidates and rejection reasons are in `assets/src/hero-prompt.md`. |
| Architecture diagram, SVG, readable in light and dark | PASS | `assets/architecture-{light,dark}.svg` (9.7 KB each) via `<picture>`. The generator is `assets/src/diagrams/build.py`. |
| Demo GIF of the real tool | PASS | `assets/demo.gif` (182 KB, 960x634, 26.7 s) is a real terminal recording. util-linux `script` records `assets/src/demo/session.sh` in a 100x30 pseudo-terminal, where each command is typed and then actually run against the synthetic fixtures in a throwaway HOME. The raw `session.typescript` and `session.timing` are committed. `assets/src/demo/record.py` replays them with their recorded timing through a small terminal emulator and renders a GIF, the same pipeline as asciinema plus agg. The first frame is the finished search screen, from the same recording. |
| Explainer visual | PASS | `assets/citation-anatomy-{light,dark}.svg`, built from the same real capture. |
| Sources in `assets/src/`; each image < 2 MB; README media < 10 MB | PASS | README media total 409,099 bytes (`du -cb`). |
| Checked in GitHub-style light and dark | PASS | Each asset was rendered with headless Chromium in a mock page with GitHub's `#ffffff` and `#0d1117` backgrounds, ~880 px column and `<picture>` switching, with the dark colour scheme forced: `docs/verification/visual-review/readme-{light,dark}.jpg`. The mock holds the README's media, not its full text, so the check covers the assets. Fixes made after review: GIF poster frame, no screen clear, 12px minimum labels, dark variant selection. |

### F. Honesty

| Item | Status | Evidence |
| --- | --- | --- |
| Every README claim backed by a test or benchmark | PASS | See "README claims" below. |
| Factual Alternatives section, written after checking the projects | PASS | Criterion 8. |

### G. How to work

| Item | Status | Evidence |
| --- | --- | --- |
| Manager delegates and verifies | PASS | Subagents did the alternatives research, benchmarks, MCP e2e, docs, visuals and the fresh-user test. Every report was re-checked, and their findings led to fixes: the title leak, config typing, `readOnlyHint`, a wrong fixture date, the slash-command bug, SQL ranking, bulk FTS rebuild and the policy cache. |
| No questions to the owner; decisions in DECISIONS.md; blockers in BLOCKED.md | PASS | DECISIONS D1–D14; BLOCKED B1 and B2 (both resolved). |
| VERIFICATION.md maps every criterion | PASS | This file. |
| Final adversarial audit by a fresh subagent, repeated until it passes | PASS | See "Final audit" below. |

## README claims

| Claim | Backed by |
| --- | --- |
| Indexes Claude Code (+ desktop titles), Codex, Pi, any mapped JSONL | `tests/test_adapters.py` (4 tests) |
| Secrets masked before storage, and again when raw lines are read | `tests/test_redaction.py` |
| Credential files are never opened | `test_deny_rules_drop_messages_and_files`, `DEFAULT_DENY_PATHS` |
| Every hit has `session#message`, harness, timestamp and `file:Lstart-Lend`, which `read --source` opens | `tests/test_citations.py`, `tests/test_mcp.py` |
| MCP tools `search`, `read`, `sessions`, `status` | `tests/test_mcp.py`, the e2e transcripts |
| Syncs itself before a query when the index is older than 5 min; no timer needed | `maybe_sync` + `test_mcp_search_then_read_citation` (auto-sync indexes the fixtures on the first call) |
| Only reads transcripts, writes only its own dirs, index mode 0600 | `tests/test_isolation.py` |
| Never edits agent configs | `test_isolation` (`~/.claude.json` and `~/.codex/config.toml` unchanged), `cmd_init` only prints |
| Resumed and forked sessions are de-duplicated, subagents linked, turns merged with `[tool: Bash x3]` markers | `test_claude_transcript_subagent_fork_and_desktop` (`[tool: Bash x2]`) |
| Codex-injected context dropped; Pi thinking and tool output not indexed | `test_codex_rollout`, `test_pi_session` |
| Performance numbers | `docs/benchmarks.md`, `bench/results/` |
| Install with `uv tool install` / `pipx` | wheel build plus isolated install (C), fresh-user test |
| Limitations (lexical only, regex redaction can miss things, deleted transcripts linger, no Windows, no cloud) | Stated as limitations. DECISIONS D5 and D8, ROADMAP item 2. |

## Final checks

These checks were run at `c3fbd85` on 2026-11-06. That commit has the same `src/`, `tests/`,
`bench/`, `assets/`, README and docs as the `v0.1.0` tag. Later commits change only
`VERIFICATION.md`, `BLOCKED.md` and `RELEASE.md`; check with `git diff --stat c3fbd85 main`. `src/` is
byte-identical to `e2ca2b5`, the commit the benchmark and the fresh-user run were made from
(`git diff e2ca2b5 c3fbd85 -- src` is empty); `c3fbd85` only adds tests and fixes docs.

```
$ uv run pytest -v | tail -1
============================== 33 passed in 1.87s ==============================

$ uv run ruff check . && uv run ruff format --check .
All checks passed!
55 files already formatted

$ docker run --rm -v "$PWD:/r" zricethezav/gitleaks git /r
INF 26 commits scanned.
INF scanned ~1982202 bytes (1.98 MB) in 304ms
INF no leaks found

$ git log --format='%an <%ae>' | sort -u
vulbsti <29302849+vulbsti@users.noreply.github.com>

$ git log --format=%B | grep -ci co-authored
0

$ privacy grep of the working tree (home path, owner's first name, work domain): matching lines
0

$ every email address in the working tree, excluding uv.lock (count of occurrences)
      5 29302849+vulbsti@users.noreply.github.com
      2 dana.reyes@example.com            # synthetic: the demo fixture, and this file quoting it

$ commits whose tree contains the private strings (BLOCKED.md B2)
23f6275 Benchmarks, search and sync perf, broker fixes from the final audit
1251965 Benchmarks, single-statement search, perf fixes, verification

$ du -cb assets/hero.jpg assets/demo.gif assets/*.svg | tail -1
409099  total

$ GH_TOKEN=$(gh auth token -u vulbsti) gh api repos/vulbsti/priorlog --jq '.private,.visibility'
true
private
```

CI on the private repo: every push to `main` since the repo was created is green
(`gh run list --workflow CI`). Each run is lint plus `test` on ubuntu-latest and macos-latest
× Python 3.11, 3.12 and 3.13. That covers `ce62db6`, `1251965`, `23f6275`, `80c36df`, `10d9e0a`,
`676604e`, `040e6df`, `264a894`, `94e4c9f`, `eaed20d`, `9cc236c`, `cde4e9c`, `92275e1`,
`659acf0`, `f2ab1df`, `a4d4861`, `cdfca12`, `83df3e2`, `e2ca2b5`, `91e72f8` and `857d128` (checked with `gh run list --repo vulbsti/priorlog --workflow CI --json headSha,conclusion`; the `--commit` filter needs the full SHA). The tagged commit's own run is
linked in "Final audit". Dependabot opened PRs #1 and #2 (action bumps), both with green CI. They
are left open for the owner.

## Final audit

Seven rounds, each run by a fresh subagent that had not seen the earlier reviews, with the
project criteria, OSS_STANDARD.md and this file as its brief. Every BLOCKER and MAJOR finding was
fixed and the next round re-checked it. Rounds 1 to 6 returned FAIL; round 7 returned
**PASS**.

| Round | Verdict | What it found (fixed in) |
| --- | --- | --- |
| 1 | FAIL | Denied titles stored, desktop metadata creating rows for denied transcripts, private strings in VERIFICATION.md (`23f6275`, `80c36df`) |
| 2 | FAIL | `read --source` raw-line deny, absent `[sources.X]` sections, branch and carry text, subagents of denied sessions (`676604e`) |
| 3 | FAIL | Content in mapped ids and timestamps, later content blocks, full-length titles, line-type names, escaped raw lines (`eaed20d`) |
| 4 | FAIL | Codex, Pi and desktop ids, denied cwd in resume commands, IDE blocks, tests too weak to fail when a fix was removed (`92275e1`) |
| 5 | FAIL | B2 recipe did not work end to end, decoded-value redaction in `read --source`, test strength (`a4d4861`) |
| 6 | FAIL | B2 push path (SSH key belongs to another account), hashed ids on the desktop path, tokens glued to `_`, benchmark and evidence provenance (`e2ca2b5`, `91e72f8`) |
| 7 | **PASS** | Six MINOR findings, no BLOCKER or MAJOR. Five fixed in `c3fbd85`, one moved to the roadmap (below). |

Round 7 checked: the full test suite, ruff and gitleaks over the whole history; author and
co-author lines; the privacy grep of the tree and of every commit (only `1251965` and `23f6275`
hit, as B2 says); benchmark provenance (`bench/results/2026-11-06.json` records `e2ca2b5` with
`src_dirty: false`, and every number in the README and `docs/benchmarks.md` matches it); CI on
every push; mutation tests of every round-6 fix in a scratch clone; a broker probe that plants
secrets in text, tool names, titles, cwd, branch, timestamps, line types, desktop ids,
session-file stems and tool results, none of which reached the SQLite or WAL bytes, search,
`read` or `read --source` (file paths are stored as written, as D14 and SECURITY.md say); the
README quickstart in a throwaway HOME; all links and anchors, the media budget and the
governance files; and a simulation of BLOCKED.md B2 steps 1, 2 and 4 in a copy of the repo
(one commit left, old SHAs unreachable, both greps empty).

Round 7's MINOR findings and what happened to them:

1. Only the GitHub rule had a glued-to-`_` test. Now one parametrized case per token kind; each
   rule's lookbehind reverted on its own fails the suite (`c3fbd85`).
2. Removing the id sanitising of `links` rows went unnoticed. The hashed-id test now adds a
   subagent under a token-shaped session stem and asserts the `links` row uses the hashed id
   (`c3fbd85`; mutation re-checked). The other two surviving mutations (key redaction in
   `_redact_value`, the final plain-text pass in `_redact_line`) are defence in depth behind
   rules that are already tested, and are left as they are.
3. B2's broad privacy grep ran after the irreversible delete. It is now part of the step-2 gate,
   and the recipe notes that a deleted repo can be restored for 90 days (`c3fbd85`).
4. The email-count note in "Final checks" named the wrong second file (`c3fbd85`).
5. `docs/verification/real-data-smoke.md` gave the wrong SQLite version (`c3fbd85`).
6. npm tokens, Google `ya29.` OAuth tokens and `--password <value>` flags are not masked. The
   pattern-based limitation is stated in the README; these formats are now listed under
   "More redaction formats" in [docs/ROADMAP.md](docs/ROADMAP.md#near-term) and linked from the
   README's Limitations. Adding them changes `src/`, which would invalidate the benchmark
   provenance for 0.1.0, so they are left for the next release.

Round 7 also noted that the MCP end-to-end runs were recorded at `c525f73`.
`src/priorlog/mcp_server.py` has not changed since then, and `tests/test_mcp.py` runs the same
flow in CI on every push.

CI for the tagged commit (`v0.1.0` = `f6cef3b`): green,
[run 42178449305](https://github.com/vulbsti/priorlog/actions/runs/42178449305): lint plus `test`
on ubuntu-latest and macos-latest × Python 3.11, 3.12 and 3.13, all `success`. This line was added
in the commit after the tag, since a commit can't name its own run.
