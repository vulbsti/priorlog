# priorlog: Alternatives research

Checked on **2026-11-05**. Each repo was shallow-cloned (`git clone --depth 1`) and read only (README, source, manifests, LICENSE). No third-party code was run. Metadata comes from `gh api repos/OWNER/REPO`. Evidence paths are relative to each repo root.

The exact commits read, so each claim can be re-checked:

| Repo | Commit | Commit date |
| --- | --- | --- |
| matt1398/claude-devtools | `1486f2042c87` | 2026-09-26 |
| vladar107/claudescope | `95f12f6891bc` | 2026-11-04 |
| Liuziyu77/ClaudeScope (same-name project, noted only) | `d690945160b1` | 2026-09-03 |
| obra/episodic-memory | `7e0651935777` | 2026-09-10 |
| pchalasani/claude-code-tools (aichat) | `cc08c03c6b2f` | 2026-11-04 |
| windviki/sessiondex | `5c0263adbc34` | 2026-10-29 |

The priorlog column restates the project's own design description. Those claims are verified against priorlog's code and tests in `VERIFICATION.md`.

> **Name note:** priorlog was previously called "sessionsift". That name is already used by https://github.com/LanceSandino/sessionsift, a different product: a Go, local-first session-analysis tool for Codex and Claude Code with a dashboard, session comparisons and ten read-only MCP tools. As of 2026-11-05 it has 1 star, GitHub reports its license as NOASSERTION, and it was last pushed 2026-11-02. Only its metadata and README were read; it was not analysed further.

---

## 1. claude-devtools

- **Repo:** https://github.com/matt1398/claude-devtools
- **License:** MIT · **Language:** TypeScript · **Stars:** 4,014 · **Last push:** 2026-09-26
- **What it is:** a GUI viewer/debugger for Claude Code sessions, shipped as an Electron desktop app (macOS/Linux/Windows) or a standalone Fastify HTTP server for Docker on port 3456 (`README.md` "Installation", "Docker / Standalone Deployment"; deps `electron-updater`, `fastify` in `package.json`). It reconstructs tool calls, diffs, thinking, subagent trees, per-turn context and token attribution, and compaction. It also has notification triggers and can read sessions on remote machines over SSH (`src/main/services/infrastructure/SshFileSystemProvider.ts`, `SshConnectionManager.ts`).
- **Harnesses:** Claude Code only. It reads `~/.claude/projects` (`src/main/utils/pathDecoder.ts:321`) and per-project `memory/`. No Codex, Pi, or other connectors found: `codex` does not appear anywhere in `src/main`.
- **Search:** no persistent index. Search does a case-insensitive `indexOf` substring scan over extracted text (`src/main/services/discovery/SessionSearcher.ts:258-265`). Extracted text is held in an in-memory LRU cache that invalidates on file mtime (`SearchTextCache.ts`). Matching covers only "User text + AI last text output" (`SessionSearcher.ts` header comment). It searches one project or all projects (`src/main/ipc/search.ts:89,119`), opened from the Cmd+K palette. No embeddings, no network, no API keys ("Zero configuration. No API keys", README).
- **Redaction:** no redaction code found. `grep -i redact|mask` in `src/main` hits only an SFTP mode bitmask comment.
- **Delivery:** GUI only (Electron app plus browser UI). No MCP server and no CLI search command (no `@modelcontextprotocol` dependency in `package.json`).
- **Citations:** a `SearchResult` carries `sessionId`, `projectId`, `timestamp`, `groupId`, `messageUuid`, and `matchStartOffset` (`src/main/types/domain.ts:223-248`). These drive in-app navigation to the matching message. They are not a file or line locator exposed to agents.
- **Incremental:** effectively yes. There is no index to build, and the mtime-keyed cache skips re-extracting unchanged files.
- **Better than priorlog:** much richer visual inspection (context-window attribution, subagent trees, inline diffs, compaction view), SSH remote sessions, desktop notifications, and a large user base.

## 2. Claudescope

Two unrelated projects use this name. The one in the same niche is **vladar107/claudescope**. A second one, Liuziyu77/ClaudeScope, is covered briefly at the end of this section.

- **Repo:** https://github.com/vladar107/claudescope
- **License:** MIT · **Language:** TypeScript · **Stars:** 21 · **Last push:** 2026-11-04 (root `package.json` version 0.26.0)
- **What it is:** a local, read-only, multi-agent session viewer, search tool, and analytics app. It runs as a web UI on 127.0.0.1:4317 from a background daemon, and also offers MCP, a CLI, a plugin with a skill, and a Raycast extension (`README.md`). Features include a live sessions view, a threaded reader, a "Files changed" view, token and cost analytics, a cross-agent efficiency scorecard, agent memory and instruction-file browsing, and an inventory of extensions (skills, MCP servers, hooks).
- **Harnesses (8):** Claude Code, Codex, JetBrains Junie, pi, opencode (SQLite), GitHub Copilot CLI, Google Antigravity, and xAI Grok CLI (`README.md` "Supported agents"). Connectors live in `packages/server/src/connectors/{claude-code,codex,pi,opencode,antigravity,...}/`. There is no user-mapped generic JSONL connector; new agents are added by writing code ("adding another connector", CONTRIBUTING.md).
- **Search:** DuckDB with the `fts` extension (BM25) over `events.textContent` (`packages/server/src/db/schema.ts:6`, `packages/server/src/data/index.ts:771` `PRAGMA create_fts_index`). It also has a `--literal` exact-substring mode. No embeddings. On first run DuckDB downloads its `json` and `fts` extensions over the network (`packages/server/src/db/duckdb.ts:95-100`, comment at :128). Other outbound calls are a daily version check and an optional pricing refresh from LiteLLM (README "Privacy"). No API keys needed.
- **Redaction:** output-side and opt-in only. `packages/shared/src/redact.ts` masks home paths and prefix-anchored secrets (`sk-`, GitHub tokens, AWS `AKIA`, Slack `xox*`, `Bearer`, PEM private keys). It applies to Markdown export, `get_session` with `redact: true` (`packages/server/src/agent/mcp.ts:227,241`), and `session --redact` in the CLI. Default is `false`. The `search_transcripts` MCP tool has no redact parameter (`mcp.ts:122-140`). The index stores raw text: no redaction occurs before indexing. Credentials on the Extensions page are always reduced to their names (`packages/server/src/connectors/extensions/redact.ts`). No path allow/deny policy beyond choosing source directories.
- **Delivery:** MCP over stdio (`claudescope mcp`) with tools `search_transcripts`, `list_sessions`, `list_projects`, `get_session`, `get_analytics`, and `get_memory` (`packages/server/src/agent/mcp.ts`). CLI query subcommands (`search`, `sessions`, `session`, `analytics`, `digest`). A Claude Code / Codex plugin with a `history` skill and a post-compaction `SessionStart` hook (`plugins/claudescope/skills/history/SKILL.md`, `plugins/claudescope/hooks/hooks.json`). Web GUI. Raycast extension.
- **Citations:** yes, at message level. Hits return `sessionId` + `messageUuid` (`packages/server/src/routes/search.ts:60,91`). They reopen with `get_session {sessionId, around: messageUuid}` or `claudescope session <id> --around <uuid>`. The locator is a message UUID, not a file line number.
- **Incremental:** yes. Files whose (mtime, size) match the `files` table are skipped (`packages/server/src/data/index.ts:7-8,920-978`). Rescans run every 15 s (`REINDEX_INTERVAL_MS`), and FTS rebuilds are throttled (`FTS_REBUILD_MIN_INTERVAL_MS`).
- **Better than priorlog:** more harnesses (8), a full GUI with analytics, cost tracking, and a live view, message-level deep links into a viewer, and packaging on npm, Homebrew, and Nix.

**Liuziyu77/ClaudeScope** (https://github.com/Liuziyu77/ClaudeScope, MIT, Python, 21 stars, last push 2026-09-03) is a different tool. It is a Gradio dashboard that visualizes a single Claude Code session as a timeline with token and tool analytics, plus HTML reports. Its "redacted" export replaces message content wholesale (`claudescope/report.py:74-75`). It has no cross-session index and no MCP. It is not a direct alternative.

## 3. obra/episodic-memory

- **Repo:** https://github.com/obra/episodic-memory
- **License:** MIT · **Language:** TypeScript · **Stars:** 500 · **Last push:** 2026-09-10 (`package.json` version 1.6.0)
- **What it is:** semantic plus text "episodic memory" over past agent conversations, delivered as an MCP server, a CLI, and a skill/plugin for Claude Code, Codex, and opencode (`README.md`, `.mcp.json`, `.claude-plugin/`, `.codex-plugin/`, `skills/remembering-conversations/`).
- **Harnesses:** Claude Code (`~/.claude/projects`, `~/.claude/transcripts`), Codex (`~/.codex/sessions`), Cursor (`~/.cursor/projects`, plus a legacy `state.vscdb` importer), opencode (exported from `opencode.db`), and Oh My Pi (`~/.omp/agent/sessions`) (`src/paths.ts:109-115`, `src/cursor-legacy.ts`, `src/opencode-sync.ts`). Plain pi (`~/.pi`) is not listed. No user-mapped generic JSONL.
- **Search/storage:** SQLite (`better-sqlite3`) with an `exchanges` table and a `sqlite-vec` `vec0` virtual table (`src/db.ts:128,175`). Embeddings are computed locally with Transformers.js using `Xenova/bge-small-en-v1.5` (`src/embeddings.ts:15`). The model is fetched from Hugging Face on first run ("first run may take time", `embeddings.ts:97`). Text mode uses SQL `LIKE` with per-token AND, not FTS (`src/search.ts:67-95,230`). Modes are `vector`, `text`, and `both`, with `both` as the default (`search.ts:11,183`).
  - **Network/API:** an optional summarization pass sends conversation content to an LLM. By default it uses Claude via `@anthropic-ai/claude-agent-sdk` and the user's Claude Code auth (default model haiku), or Codex app-server for Codex sessions. Custom endpoints and Bedrock are supported, and `EPISODIC_MEMORY_SKIP_SUMMARIES=1` disables the pass (README "API Configuration"). Summaries are display-only. Search itself is local.
- **Redaction:** no secret-redaction code found (no redact/secret matches in `src/`). Exclusion controls exist: a per-chat `DO NOT INDEX THIS CHAT` marker (`src/sync.ts:10,298`) and a project exclude list via `CONVERSATION_SEARCH_EXCLUDE_PROJECTS` (`src/sync.ts:201-206`). Transcripts are **copied** into an archive at `~/.config/superpowers/conversation-archive` (`src/paths.ts:196-204`).
- **Delivery:** MCP server with tools `search` and `read` (`src/mcp-server.ts:146,179`). CLI `episodic-memory sync|search|show|stats|doctor|index`. Skill plus a `search-conversations` agent. Session hooks for auto-sync (`hooks/hooks.json`). No GUI, though `show --format html` renders HTML.
- **Citations:** yes, with a line locator. Each exchange stores `archive_path`, `line_start`, `line_end`, `session_id`, `timestamp`, and `harness` (`src/db.ts:128-152`). Results print `lineStart-lineEnd` (`src/search.ts:364,478`), and the MCP `read` tool takes `path` + `startLine`/`endLine` (`src/mcp-server.ts:179-190`). The path points to the archived copy, not the original transcript.
- **Incremental:** yes. Sync copies only new or modified files by mtime (`src/sync.ts:146`) and resumes indexing from `MAX(line_end)` per archive file (`src/sync.ts:308`). Auto-sync runs from session hooks.
- **Better than priorlog:** semantic (embedding) search that finds conceptually related discussions without keyword overlap, LLM-generated summaries on results, Cursor and opencode support including legacy Cursor import, a per-chat "do not index" marker, and an established plugin presence (superpowers marketplace).

## 4. aichat session search (pchalasani/claude-code-tools)

- **Repo:** https://github.com/pchalasani/claude-code-tools (`aichat` CLI plus the `plugins/aichat` plugin; search engine published as the `aichat-search` Rust crate in `rust-search-ui/`)
- **License:** MIT · **Language:** Python (+ Rust TUI) · **Stars:** 2,031 · **Last push:** 2026-11-05 (`pyproject.toml` version 1.31.0)
- **What it is:** one tool in a larger suite. `aichat search` is full-text search over sessions with an interactive Rust TUI and a `--json` mode for agents. It ships alongside session resume, trim, export, porting, and lineage tools (`claude_code_tools/aichat.py`, `docs-site/src/content/docs/tools/aichat/search.mdx`).
- **Harnesses:** Claude Code (`~/.claude/projects/**/*.jsonl`) and Codex (`~/.codex/sessions/????/??/??/*.jsonl`) (`claude_code_tools/search_index.py` `auto_index`, ~L1331-1390; `search.mdx` "What gets indexed"). It can filter by multiple Claude homes (`claude_home` field). No Pi or generic JSONL support found.
- **Search/storage:** a Tantivy (BM25) index at `~/.cctools/search-index` (`search_index.py:1319`; `tantivy>=0.22` in `pyproject.toml`). There is **one document per session** with a single `content` field plus metadata (`search_index.py:168-220`). Ranking blends in recency (`_calculate_recency_score`). No embeddings, no network, no API keys for search.
- **Redaction:** no redaction code found in `search_index.py`, `aichat.py`, or `rust-search-ui/src`. The suite has separate `env-safe` and `safety-hooks` tools, but they are not applied to the search index.
- **Delivery:** CLI (`aichat search`, Python) plus a separate `aichat-search` Rust TUI binary. The Claude Code plugin `plugins/aichat` provides a `session-searcher` subagent, `session-search` and `recover-context` skills, a `/recover-context` command, and hooks. No MCP server for search: `mcp` is a package dependency, but no `FastMCP`/`from mcp` usage was found in `claude_code_tools/`. Agents call `aichat search --json` through the shell (`plugins/aichat/skills/session-search/SKILL.md`). There is a TUI but no GUI.
- **Citations:** session-level only. JSON fields are `session_id`, `agent`, `project`, `branch`, `cwd`, `lines`, `created`, `modified`, `first_msg`, `last_msg`, `file_path`, `derivation_type`, `is_sidechain`, and `snippet` (`search.mdx`). There is no per-message or line locator; the skill tells the agent to read the whole session file (max 3).
- **Incremental:** yes. `IndexState.needs_reindex` compares mtime and size (`search_index.py:110-160`). A full rebuild happens when the package version or `INDEX_LOGIC_REVISION` changes (`search_index.py:18-38`). The index updates on every `aichat` command.
- **Better than priorlog:** a fast interactive TUI, session-lineage awareness (trimmed, rollover, and continued sessions), resume and port actions straight from results, filters for sub-agent and `codex exec` noise, and a large user base.

## 5. windviki/sessiondex

- **Repo:** https://github.com/windviki/sessiondex
- **License:** MIT · **Language:** Python · **Stars:** 1 · **Last push:** 2026-10-29 (version 0.1.0, "Beta")
- **What it is:** a local full-text index and search service over agent session histories, with CLI, REST API (FastAPI on 127.0.0.1:8765), MCP, and an agent skill (`README.md`, `src/sessiondex/{cli,api,mcp_server}.py`). This is the closest match to priorlog's niche.
- **Harnesses:** Claude Code, ZCode, Kimi Code, dsh (DeepSeek, zstd JSONL), Qoder, and opencode (`src/sessiondex/provider/*.py`, README table). **No Codex and no Pi**: `grep -i codex` and `\.pi/` in `src/` return nothing. No user-mapped generic JSONL; providers are code.
- **Search/storage:** SQLite FTS5, **contentless** (`content=''`, `contentless_delete=1`) (`src/sessiondex/index.py:86-88`). A custom tokenizer lowercases ASCII words and emits CJK character bigrams, fed to `unicode61` (`src/sessiondex/tokenize.py`, README "How the index works"). Ranking is bm25 with column weights. Stored rows hold only capped excerpts (text 2 KB, reasoning 1 KB, tool output preview 1 KB), and snippets outside an excerpt are regenerated from the original source through locators. No embeddings, no network.
- **Redaction:** no redaction code found (`grep -i redact|secret|mask` in `src/` returns nothing). The privacy approach is to store no full-text copy rather than to redact. Agent stores are opened read-only.
- **Delivery:** MCP over stdio (`sessiondex mcp`) or streamable HTTP (`/mcp`), with tools `search_sessions`, `list_sessions`, `get_session_messages`, `list_agents`, `list_tools`, and `refresh_index`. CLI commands `scan`, `search`, `sessions`, `show`, `status`, `serve`, and `mcp`. REST API. A skill at `integrations/skills/search-sessions/SKILL.md`. No GUI.
- **Citations:** yes. Hits include the session id and a per-message `locator` dict (`src/sessiondex/model.py:52`, `src/sessiondex/search.py:170-199`). They reopen with `sessiondex show <agent> <session_id> --around <msg_id>` or `/api/messages/read`.
- **Incremental:** yes. JSONL resumes from the last byte offset (size and mtime watermarks), SQLite sources use rowid watermarks, and zstd files are reparsed on change (README "Incremental scanning").
- **Better than priorlog:** a contentless index with a small on-disk footprint and no stored transcript copy, CJK-aware tokenization, a REST API, tool-type and role filters, and Chinese-ecosystem agents (ZCode, Kimi, dsh, Qoder) plus opencode.

---

## Comparison table

| | Harnesses | Search tech | Redaction | MCP | CLI | GUI | Citations w/ locator | Incremental | License |
|---|---|---|---|---|---|---|---|---|---|
| **priorlog** | Claude Code (CLI JSONL + desktop `local_*.json` linkage), Codex CLI, Pi, user-mapped generic JSONL | SQLite FTS5 (trigram), local | **In the store, before indexing; re-applied on raw-line reads** (API keys, bearer tokens, emails, private keys) + path allow/deny policy | Yes | Yes | No | Yes: session, harness, timestamp, line locator, opened with `read` | Yes | Apache-2.0 |
| **claude-devtools** | Claude Code only (+ remote over SSH) | In-memory substring scan, mtime LRU cache; no persistent index | No redaction code found | No | No | **Yes** (Electron + web/Docker) | In-app only (sessionId + messageUuid/groupId); not agent-facing | N/A (no index); cache invalidated by mtime | MIT |
| **Claudescope** (vladar107) | Claude Code, Codex, Junie, pi, opencode, Copilot CLI, Antigravity, Grok CLI | DuckDB `fts` BM25 + literal substring; extensions downloaded on first run | Opt-in, **output-side only** (export / `get_session` / CLI `--redact`); index stores raw text; search snippets unredacted | Yes (stdio) | Yes | **Yes** (web UI, analytics) + Raycast | Yes: sessionId + messageUuid, opened with `get_session --around` | Yes (mtime+size, 15 s rescans) | MIT |
| **episodic-memory** (obra) | Claude Code, Codex, Cursor, opencode, Oh My Pi | SQLite + sqlite-vec embeddings (local `bge-small-en-v1.5`, model downloaded once) + SQL LIKE text mode; optional LLM summaries (network) | No secret redaction found; DO-NOT-INDEX marker + project exclude list | Yes (`search`, `read`) | Yes | No (HTML export) | Yes: archive path + line_start-line_end, opened with `read` (points at archived copy) | Yes (mtime copy + resume from max line) | MIT |
| **aichat search** (claude-code-tools) | Claude Code, Codex | Tantivy BM25, one doc per session, recency boost | No redaction code found | No (shell `--json` via skill/subagent) | Yes | TUI (Rust), no GUI | Session-level only (file_path + snippet); no line/message locator | Yes (mtime+size) | MIT |
| **sessiondex** (windviki) | Claude Code, ZCode, Kimi, dsh, Qoder, opencode | SQLite FTS5 contentless, custom ASCII + CJK-bigram tokens, bm25 | No redaction code found (stores only capped excerpts) | Yes (stdio + HTTP) | Yes | No (REST API) | Yes: session id + per-message locator, opened with `show --around` | Yes (byte offset / rowid watermarks) | MIT |

### Points for the README (factual)
- **Redaction before indexing:** of the five tools, only Claudescope has any secret redaction, and it is opt-in and applied to output only. None of them redacts secrets before writing the index.
- **Line-level locators:** episodic-memory is the only alternative with line-range citations, and those point at its archived copy of the transcript. Claudescope and sessiondex use message-ID locators. aichat cites only at session level. claude-devtools has locators for its own UI only.
- **Codex and Pi together:** Claudescope is the only alternative that indexes both Codex and pi. episodic-memory supports Oh My Pi but not plain pi. sessiondex supports neither.
- **Generic JSONL:** none of the five lets users map an arbitrary JSONL format without writing code.
- **Claude desktop app `local_*.json` linkage:** I grepped every repo's .ts/.py/.rs source for `local_`, `claude-code-sessions` and `Application Support/Claude`. No desktop-session handling turned up. The only match was claude-devtools reading the managed `CLAUDE.md` path (`src/main/services/parsing/ClaudeMdReader.ts:219`). It looks like no alternative links desktop-app sessions, but a keyword search could miss other naming, so treat this as **likely, not proven**.
- **Where alternatives are stronger:** semantic search (episodic-memory), GUI and analytics (claude-devtools, Claudescope), harness breadth (Claudescope with 8, sessiondex with 6), a TUI and session-lineage tooling (aichat), and a contentless low-footprint index with CJK support (sessiondex).
