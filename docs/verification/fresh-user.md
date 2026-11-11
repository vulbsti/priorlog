# Fresh-user walkthrough: README only

- **Date:** 2026-11-06
- **Commit tested:** `e2ca2b5 Audit round 6: B2 push path over HTTPS; desktop-path hashed ids; glued tokens`
- **Environment:** Ubuntu 24.04.5 LTS (Linux 6.17.0 x86_64), `uv 0.9.8`, Python 3.12.3, Claude Code 2.1.318
- **Isolation:** throwaway `HOME=$FU/home`, `UV_TOOL_DIR=$FU/uv-tools`, `UV_TOOL_BIN_DIR=$FU/home/.local/bin`
  (first on `PATH`), every `PRIORLOG_*` and `XDG_*` variable unset. Nothing was installed beforehand.
- **Source:** the GitHub repo is private, so `https://github.com/vulbsti/priorlog` was replaced by a
  local git repository, written below as `$REPO`. That was the only change to any README command.
- **What I read:** `README.md`, plus one table in `docs/usage.md` (linked from the README) when a
  `--harness` filter returned nothing. No source code, tests, AGENTS.md or CONTRIBUTING.md.

Paths: `$FU` is the throwaway run folder and `$REPO` is the local stand-in for the GitHub URL.
priorlog itself shortens the home folder to `~`.

## Transcript

### 1. Install

```console
$ which priorlog
[exit 1]

$ uv tool install git+file://$REPO
   Updating file://$REPO (HEAD)
    Updated file://$REPO (e2ca2b56ab78b61a019d7d88d0a1d75eea06563b)
Resolved 29 packages in 1.58s
   Building priorlog @ git+file://$REPO@e2ca2b56ab78b61a019d7d88d0a1d75eea06563b
Downloading pydantic-core (2.2MiB)
Downloading cryptography (4.5MiB)
 Downloading pydantic-core
 Downloading cryptography
      Built priorlog @ git+file://$REPO@e2ca2b56ab78b61a019d7d88d0a1d75eea06563b
Prepared 29 packages in 732ms
Installed 29 packages in 9ms
 + annotated-types==0.8.0
 ... (27 more dependencies: anyio, click, cryptography, mcp, pydantic, starlette, uvicorn, ...)
 + priorlog==0.1.0 (from git+file://$REPO@e2ca2b56ab78b61a019d7d88d0a1d75eea06563b)
Installed 1 executable: priorlog
[exit 0]

$ priorlog --version; priorlog --help
priorlog 0.1.0
usage: priorlog [-h] [--version] [--config CONFIG]
                {init,sync,search,read,sessions,status,mcp,install-skill} ...

Search your past coding-agent sessions, with citations.

positional arguments:
  {init,sync,search,read,sessions,status,mcp,install-skill}
    init                write a default config and show what was found
    sync                index new transcript lines (incremental)
    search              full-text search; every hit has a citation
    read                open a citation (<session>#<n>) or a whole session
    sessions            list sessions, most recent first
    status              what is indexed, redaction counts
    mcp                 run the MCP server on stdio
    install-skill       copy the agent skill into ~/.claude or ~/.codex skills

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --config CONFIG       config file (default: $PRIORLOG_CONFIG or
                        ~/.config/priorlog/config.toml)
[exit 0]
```

### 2. Quickstart (empty machine)

```console
$ priorlog init
wrote $FU/home/.config/priorlog/config.toml
  claude          $FU/home/.claude/projects  not found (skipped)
  claude desktop  $FU/home/.config/Claude/claude-code-sessions  not found (skipped)
  codex           $FU/home/.codex/sessions  not found (skipped)
  pi              $FU/home/.pi/agent/sessions  not found (skipped)
index will live at $FU/home/.local/share/priorlog/index.sqlite3
next: priorlog sync

Register the MCP server with your agent (priorlog never edits agent configs itself):
  claude mcp add --scope user priorlog -- priorlog mcp
  codex mcp add priorlog -- priorlog mcp
Add the agent skill (optional):  priorlog install-skill --target claude
[exit 0]

$ priorlog sync
0 files (0 changed, 0 denied), 0 new messages in 0.01s
[exit 0]

$ priorlog search "token bucket"
No matches for `token bucket`. Try fewer or different words, drop a filter, or check `priorlog status` for what is indexed.
[exit 3]
```

`priorlog read <cite-from-search> --source` could not run here because there is no cite yet. The
README's next paragraph ("No transcripts on this machine yet?") covers that case, so I went to the
sample data.

### 3. Sample data block (run in one shell, from `$FU`)

```console
$ git clone $REPO priorlog && cd priorlog
Cloning into 'priorlog'...
done.

$ export PRIORLOG_CONFIG="$PWD/examples/demo/config.toml" PRIORLOG_HOME="$(mktemp -d)"
$ echo $PRIORLOG_HOME
/tmp/tmp.mTfMOFOyWF

$ priorlog sync && priorlog search rate limiter
6 files (6 changed, 0 denied), 16 new messages in 0.03s
1 hit(s) for `rate limiter` (1 matching message in 1 session).

[1] Orders API rate limiting · claude · 2026-10-01 09:00 · user
    > The API is getting hammered. Design a «rate limiter» for /v1/orders.
    cite: claude:aaaaaaaa-1111-4111-8111-000000000001#0   source: $FU/priorlog/tests/fixtures/claude/projects/-work-demo-app/aaaaaaaa-1111-4111-8111-000000000001.jsonl:L2

Open a hit: priorlog read <cite>   (add --source for the original transcript lines)

$ priorlog read claude:aaaaaaaa-1111-4111-8111-000000000001#0 --source
# Orders API rate limiting
- session: claude:aaaaaaaa-1111-4111-8111-000000000001 · harness: claude · 4 messages
- cwd: /work/demo-app
- branch: main
- transcript: $FU/priorlog/tests/fixtures/claude/projects/-work-demo-app/aaaaaaaa-1111-4111-8111-000000000001.jsonl
- resume: cd /work/demo-app && claude --resume aaaaaaaa-1111-4111-8111-000000000001
- active: 2026-10-01 09:00 → 2026-10-01 09:05

▶ [user · 2026-10-01 09:00 · claude:aaaaaaaa-1111-4111-8111-000000000001#0 · $FU/priorlog/tests/fixtures/claude/projects/-work-demo-app/aaaaaaaa-1111-4111-8111-000000000001.jsonl:L2]
The API is getting hammered. Design a rate limiter for /v1/orders.

[assistant · 2026-10-01 09:00 · claude:aaaaaaaa-1111-4111-8111-000000000001#1 · ...jsonl:L3-L8]
Let me look at the current middleware first.

[tool: Bash x2]

Decision: use a token bucket per API key, stored in Redis with a Lua script so refill and take are atomic. Sliding-window logs were rejected because they cost O(requests) memory per key. Burst capacity 20, refill 5 tokens per second.

[user · 2026-10-01 09:05 · claude:aaaaaaaa-1111-4111-8111-000000000001#2 · ...jsonl:L9]
/review middleware/ratelimit.py

[assistant · 2026-10-01 09:05 · claude:aaaaaaaa-1111-4111-8111-000000000001#3 · ...jsonl:L10]
Review done: the Lua script handles clock skew by using Redis TIME instead of the client clock.

Original transcript lines (redacted):
  L2: {"type": "user", "sessionId": "aaaaaaaa-1111-4111-8111-000000000001", "timestamp": "2026-10-01T09:00:00Z", "cwd": "/work/demo-app", "gitBranch": "main", "message": {"role": "user", "content": "<system-reminder>injected context</system-reminder>The API is getting hammered. Design a rate limiter for /v1/orders."}}

Linked sessions: fork to claude:bbbbbbbb-2222-4222-8222-000000000002, subagent to claude:agent-r1
[exit 0]

$ priorlog status
index: /tmp/tmp.mTfMOFOyWF/index.sqlite3 (0.1 MB) · last sync: 2026-11-06T06:43:09Z · 6 files
  claude           3 sessions    8 messages
  codex            1 session     2 messages
  jsonl:supportbot 3 sessions    4 messages
  pi               1 session     2 messages
redactions: email 1
dropped by deny_content: 0 · malformed lines: 1
unfamiliar line types (skipped): claude:some-future-type (1)
[exit 0]
```

The counts match the README comment ("1 email redacted, 1 deliberately malformed line skipped").

### 4. Curious-user extras (same shell, demo index)

```console
$ priorlog status --json
{
  "db": "/tmp/tmp.mTfMOFOyWF/index.sqlite3",
  "db_bytes": 94208,
  "last_sync": "2026-11-06T06:43:09Z",
  "files": 6,
  "harnesses": {
    "claude": {"sessions": 3, "messages": 8},
    "codex": {"sessions": 1, "messages": 2},
    "jsonl:supportbot": {"sessions": 3, "messages": 4},
    "pi": {"sessions": 1, "messages": 2}
  },
  "redactions": {"email": 1},
  "dropped_by_deny_content": 0,
  "malformed_lines": 1,
  "unknown_types": {"claude:some-future-type": 1}
}
[exit 0]
(nested objects collapsed onto one line here; the real output is indented)

$ priorlog search rate limiter --harness codex
No matches for `rate limiter`. Try fewer or different words, drop a filter, or check `priorlog status` for what is indexed.
[exit 3]

$ priorlog search --help
usage: priorlog search [-h] [--harness HARNESS] [--project PROJECT]
                       [--role {user,assistant,system}] [--after AFTER]
                       [--before BEFORE] [-n LIMIT] [--json] [--no-sync]
                       query [query ...]

positional arguments:
  query

options:
  -h, --help            show this help message and exit
  --harness HARNESS
  --project PROJECT     substring of the working directory or title
  --role {user,assistant,system}
  --after AFTER
  --before BEFORE
  -n LIMIT, --limit LIMIT
  --json                machine-readable output
  --no-sync             skip the automatic incremental sync

$ priorlog search zzqxnomatchqq
No matches for `zzqxnomatchqq`. Try fewer or different words, drop a filter, or check `priorlog status` for what is indexed.
[exit 3]

$ priorlog sessions
8 session(s), most recent first.

- Invoices go to the wrong address, please send them to [REDACTED:email] instead · jsonl:supportbot:conv-9 · jsonl:supportbot · 2026-10-07 10:00 → 2026-10-07 10:00 · 1 msgs
- How do I rotate my webhook signing secret? · jsonl:supportbot:conv-8 · jsonl:supportbot · 2026-10-06 09:00 → 2026-10-06 09:00 · 1 msgs
- My export to CSV times out after 30 seconds · jsonl:supportbot:conv-7 · jsonl:supportbot · 2026-10-05 12:00 → 2026-10-05 12:00 · 2 msgs
- test_payment_retry is flaky on CI, find out why · pi:019f0000-0000-7000-8000-000000000004 · pi · 2026-10-04 08:00 → 2026-10-04 08:00 · 2 msgs · /work/demo-api
- Follow-up: add a Retry-After header when the bucket is empty. · claude:bbbbbbbb-2222-4222-8222-000000000002 · claude · 2026-10-03 14:00 → 2026-10-03 14:00 · 2 msgs · /work/demo-app
- Migrate CI from Travis to GitHub Actions and keep the Postgres service. · codex:cccccccc-3333-4333-8333-000000000003 · codex · 2026-10-02 10:00 → 2026-10-02 10:00 · 2 msgs · /work/demo-app
- Orders API rate limiting · claude:aaaaaaaa-1111-4111-8111-000000000001 · claude · 2026-10-01 09:00 → 2026-10-01 09:05 · 4 msgs · /work/demo-app
- Benchmark limiter algorithms · claude:agent-r1 · claude · 2026-10-01 09:01 → 2026-10-01 09:02 · 2 msgs
[exit 0]

$ priorlog search "token bucket" --harness claude
3 hit(s) for `token bucket` (3 matching messages in 2 sessions).

[1] Benchmark limiter algorithms · claude · 2026-10-01 09:01 · user
    > Benchmark «token bucket» vs sliding window in Redis
    cite: claude:agent-r1#0   source: $FU/priorlog/tests/fixtures/claude/projects/-work-demo-app/aaaaaaaa-1111-4111-8111-000000000001/subagents/agent-r1.jsonl:L1
[2] Benchmark limiter algorithms · claude · 2026-10-01 09:02 · assistant
    > «Token bucket»: 0.21 ms p95 per check; sliding window log: 0.94 ms p95 at 1k req/s.
    cite: claude:agent-r1#1   source: $FU/priorlog/tests/fixtures/claude/projects/-work-demo-app/aaaaaaaa-1111-4111-8111-000000000001/subagents/agent-r1.jsonl:L2
[3] Orders API rate limiting · claude · 2026-10-01 09:00 · assistant
    > Let me look at the current middleware first. [tool: Bash x2] Decision: use a «token bucket» per API key, stored in Redis with a Lua script so refill and take are atomic. Sliding-window logs were rejected because they cost O(requests) memory per…
    cite: claude:aaaaaaaa-1111-4111-8111-000000000001#1   source: $FU/priorlog/tests/fixtures/claude/projects/-work-demo-app/aaaaaaaa-1111-4111-8111-000000000001.jsonl:L3-L8

Open a hit: priorlog read <cite>   (add --source for the original transcript lines)
[exit 0]

$ priorlog search webhook --harness supportbot
No matches for `webhook`. Try fewer or different words, drop a filter, or check `priorlog status` for what is indexed.
[exit 3]
```

At this point I opened `docs/usage.md` (linked from the README as "Usage"). Its flag table says
`--harness` takes `claude`, `codex`, `pi`, `jsonl:<name>` or `jsonl`.

```console
$ priorlog search webhook --harness jsonl:supportbot -n 1
1 hit(s) for `webhook` (1 matching message in 1 session).

[1] How do I rotate my webhook signing secret? · jsonl:supportbot · 2026-10-06 09:00 · user
    > How do I rotate my «webhook» signing secret?
    cite: jsonl:supportbot:conv-8#0   source: $FU/priorlog/tests/fixtures/jsonl/supportbot.jsonl:L3

Open a hit: priorlog read <cite>   (add --source for the original transcript lines)
[exit 0]

$ priorlog read claude:nope#0 --source
error: no session 'claude:nope'; use search or sessions to find one
[exit 2]
```

### 5. MCP registration with Claude Code (new shell: demo variables gone)

```console
$ claude mcp add --scope user priorlog -- priorlog mcp
Added stdio MCP server priorlog with command: priorlog mcp to user config
File modified: $FU/home/.claude.json
[exit 0]

$ claude mcp list
Checking MCP server health…

priorlog: priorlog mcp - ✔ Connected
[exit 0]

$ claude mcp get priorlog
priorlog:
  Scope: User config (available in all your projects)
  Status: ✔ Connected
  Type: stdio
  Command: priorlog
  Args: mcp
  Environment:

To remove this server, run: claude mcp remove priorlog -s user
[exit 0]
```

No model was run, so the MCP tools themselves were not called. This only shows that the server
starts and completes the handshake.

### 6. Skill install

```console
$ priorlog install-skill --target claude
installed skill: $FU/home/.claude/skills/priorlog/SKILL.md
[exit 0]

$ head -5 $HOME/.claude/skills/*/SKILL.md
---
name: priorlog
description: Search and cite the user's past coding-agent sessions on this machine (Claude Code, Codex CLI, Pi and configured JSONL logs) through the priorlog MCP tools or CLI. Use when the user refers to earlier work ("last time", "we already fixed this", "what did we decide about X", "how did I set up Y"), asks for a project's history, or before asking the user for context they probably gave in another session.
---
[exit 0]

$ priorlog install-skill --target claude      # run again
$FU/home/.claude/skills/priorlog/SKILL.md exists (use --force to replace it)
[exit 1]

$ priorlog install-skill --target codex
installed skill: $FU/home/.codex/skills/priorlog/SKILL.md
[exit 0]
```

### 7. Real index after the demo, cleanup, and what was written to HOME

```console
$ priorlog status
index: ~/.local/share/priorlog/index.sqlite3 (0.1 MB) · last sync: 2026-11-06T06:42:59Z · 0 files
  (empty: run `priorlog sync`)
redactions: none
dropped by deny_content: 0 · malformed lines: 0

$ mv /tmp/tmp.mTfMOFOyWF ~/proj/TRASH/    # README: remove $PRIORLOG_HOME when done (rm is blocked on this machine)

$ find $HOME -path $HOME/.cache -prune -o \( -type f -o -type l \) -print | sort; ls $HOME/.cache
$FU/home/.claude/backups/.claude.json.backup.1793947408996
$FU/home/.claude.json
$FU/home/.claude/skills/priorlog/SKILL.md
$FU/home/.codex/skills/priorlog/SKILL.md
$FU/home/.config/priorlog/config.toml
$FU/home/.local/bin/priorlog
$FU/home/.local/share/priorlog/index.lock
$FU/home/.local/share/priorlog/index.sqlite3
claude-cli-nodejs
uv
```

The demo run wrote nothing into the real index, which matches the README. Every file is one I
would expect. `.claude.json` and its backup come from `claude mcp add`. `.cache` belongs to uv
and Claude Code.

## Step results

| README step | Result | Reason |
| --- | --- | --- |
| Install (`uv tool install git+…`) | PASS | Installed cleanly in a few seconds. `priorlog --version` and `--help` work. |
| `priorlog init` | PASS | Wrote the config, listed each source as "not found (skipped)", and printed the next step and the MCP commands. |
| `priorlog sync` | PASS | Ran on an empty machine without errors. |
| `priorlog search "token bucket"` | PASS | Empty index gave a helpful message and exit 3, as documented. |
| `priorlog read <cite> --source` | PASS (N/A) | No cite exists on an empty machine. The README sends you straight to the sample data, where it worked. |
| Sample data: clone, export, `sync && search` | PASS | 16 messages indexed. The hit and cite match the README. |
| Sample data: `read … --source` | PASS | Opened the session, marked the cited message and showed the redacted raw line L2. |
| Sample data: `status` | PASS | Showed 1 email redacted and 1 malformed line, as the comment says. |
| README sample output vs real output | CONFUSING (cosmetic) | The README example shows `source: ~/.claude/projects/-work-demo-app/…`. The demo prints `…/tests/fixtures/claude/projects/…`. `status` also prints an extra "unfamiliar line types" line that the README doesn't mention. |
| `claude mcp add` then `claude mcp list` | PASS | Wrote only `$FU/home/.claude.json`. The server shows as `✔ Connected`. |
| `priorlog install-skill --target claude` | PASS | Went to `~/.claude/skills/priorlog/SKILL.md`. A second run refuses without `--force` (exit 1). `--target codex` also worked. |
| Extras: `status --json`, no-match exit code | PASS | Valid JSON. A search with no match exits 3. |
| Extras: `--harness` filter | CONFUSING | `--harness supportbot` silently matched nothing (exit 3). The right value is `jsonl:supportbot`, which `search --help` doesn't say. I learned it from `docs/usage.md`, though `status` output does show the name. |

## Verdict

**Yes.** I finished install, the Quickstart, the whole sample-data block, MCP registration and
skill install using only the README, with no outside help. Nothing failed.

Points where I guessed, worked around something or read beyond the README:

1. **URL substitution** (required by the test setup, not a README problem). I used the local
   repository in place of the GitHub URL for both `uv tool install` and `git clone`.
2. **`read <cite-from-search> --source` on an empty machine.** There is no cite to read. I
   understood this to mean "use the sample data next", which the following paragraph supports.
3. **`--harness` values.** I guessed `supportbot` for the JSONL source, got a silent "No matches",
   and had to open `docs/usage.md` to learn the form `jsonl:<name>`. `search --help` gives no
   description for `--harness`, `--after` or `--before`.
4. **Sample output differs slightly from the README** (source path, extra status line). It didn't
   block anything.
5. **Cleanup:** `rm` is blocked on this machine, so I moved the temp `$PRIORLOG_HOME` to a trash
   folder. This is a local constraint, not a README issue.
6. **Not tested:** `PATH` already had `~/.local/bin` first. I didn't check what a user sees when
   uv's tool bin folder is not on `PATH`, or whether `claude mcp list` still connects then.
