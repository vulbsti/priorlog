# Real-data smoke test (maintainer machine, 2026-11-05)

This checks that the adapters handle real transcripts, not just the synthetic fixtures. Everything
ran read-only against the maintainer's own `~/.claude/projects`, `~/.codex/sessions` and
`~/.pi/agent/sessions`. The index went to a scratch directory (`PRIORLOG_HOME` and `PRIORLOG_CONFIG`
pointed outside the repo), was never committed, and has since been deleted. Only aggregate numbers are
recorded here. No transcript text is included.

Machine: AMD Ryzen AI 7 PRO 350 (16 threads), 58 GB RAM, Linux 6.17, Python 3.14 (uv venv), SQLite 3.50.4.

## Full sync, then incremental sync

```
$ priorlog init && priorlog sync
1156 files (1156 changed, 0 denied), 3491 new messages in 12.34s

$ priorlog status
  claude              403 sessions     1783 messages
  codex               662 sessions     1523 messages
  pi                   30 sessions      185 messages
redactions: anthropic_key 1, email 369, openai_key 1, secret_assignment 42
dropped by deny_content: 0 · malformed lines: 0
unfamiliar line types (skipped): {"codex:agent_message": 1}

$ priorlog sync          # nothing new except the sessions that were live at the time
1154 files (6 changed, 0 denied), 0 new messages in 0.19s
```

Peak RSS during the full sync was 62 MB, and the index was 38.6 MB on disk.

Message counts look low for 403 sessions, and that is expected for this corpus. Most of these
sessions are agent-driven, so most `user` lines are tool results, which are not indexed. Every run of
tool calls also folds into a single assistant message.

## Parity with the predecessor tool

The owner's earlier private session-search tool is the one priorlog replaces. Its index was
opened **read-only** (`file:...?mode=ro`) to compare message counts for the same laptop sessions:

| | sessions | messages |
| --- | ---: | ---: |
| predecessor tool (laptop, local) | 391 | 1,767 |
| priorlog, first port | 399 | 1,645 |
| priorlog, after fix | 403 | 1,783 |

The first port came out 7% low. A per-session diff showed that the missing messages were relays from
other sessions ("Another Claude session sent a message…"). priorlog checked `isMeta` before the relay
rule and so dropped them, which also merged assistant turns across each relay. Both rules now run in
the same order as the predecessor tool, and relays are stored as role `system`. The fixed version is the one
committed. The extra sessions and messages that remain come from sessions created after the predecessor
tool's last timer run.

## Citation round trip on real data

`priorlog search <term> --harness codex` returned hits whose `source` locators point at real rollout
files. `priorlog read <cite> --source` printed the cited raw lines, redacted. That run showed a long
assistant turn can span many raw lines, so `--source` is now capped at 12 lines with a "… N more
line(s)" note.

Search latency, end to end through the CLI with Python startup included, was 0.07 to 0.09 s per
query on this index.

## The predecessor tool left untouched

Before and after the runs above, the script stat-ed and hashed `~/.claude.json` (MCP registrations) and
the predecessor tool's systemd user timers, and stat-ed its index file.
`diff before.txt after.txt` was empty.
