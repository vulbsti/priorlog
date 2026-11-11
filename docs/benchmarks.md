# Benchmarks

How fast priorlog indexes and searches, measured on one laptop with a synthetic corpus of
55,255 indexed messages. Every number on this page comes from `bench/run.py`. The final run is stored in
[`bench/results/2026-11-06.json`](../bench/results/2026-11-06.json), the quieter cross-check in
[`bench/results/2026-11-05.json`](../bench/results/2026-11-05.json), and the run before the
performance fixes in
[`bench/results/2026-11-05-before-fixes.json`](../bench/results/2026-11-05-before-fixes.json). Slow cases
are included.

## Machine

| | |
| --- | --- |
| CPU | AMD Ryzen AI 7 PRO 350 (8 cores / 16 threads, up to 5.1 GHz) |
| RAM | 58 GiB |
| Disk | NVMe SSD, ext4 |
| OS | Ubuntu 24.04.5 LTS, Linux 6.17 |
| Python | 3.14.0 (uv-managed) |
| SQLite | 3.50.4 (the one bundled with that Python) |
| priorlog | 0.1.0 at commit `e2ca2b5` (clean tree: the results JSON records `"src_dirty": false`). `src/` is unchanged from there to the `v0.1.0` tag. |
| Load during the run | 1-minute load average 2.4–2.7 (5-minute 2.4–2.5). Other agent sessions were idle or finished. |

Values came from `lscpu`, `free -h`, `/etc/os-release`, `uname -r`, and
`uv run python -c "import sys, sqlite3; print(sys.version, sqlite3.sqlite_version)"`.
The machine was shared with other jobs. Before the final run, the load average was polled
until the 1-minute value dropped below 3. Load before and after each repeat is in the results
JSON. An earlier run at `80c36df` (1-minute load 1.7–3.2; `bench/results/2026-11-05.json`)
came before the second to fifth audits' broker fixes. Its numbers are close to the final run's
(search p50 21.0 vs 18.6 ms, p95 131 vs 123 ms, cold index 22.3 vs 21.8 s, append sync 817 vs
799 ms), so the broker fixes did not measurably slow indexing or search. The one visible cost is
`read --source`: it now redacts and deny-checks decoded JSON values, and its p95 went from 3.6 to
8.2 ms. Run-to-run spread on this shared machine is about ±10%.

## Reproduce

```bash
uv run python bench/generate.py /tmp/priorlog-bench/corpus   # deterministic, seed 20261105
uv run python bench/run.py /tmp/priorlog-bench/corpus --repeats 3
```

`run.py` points `HOME`, `PRIORLOG_HOME` and `PRIORLOG_CONFIG` into a throwaway work dir, so
nothing real is read. For each repeat it copies the corpus, starts from an empty index, and
runs the steps below in order. Tables show the **median of 3 repeats, with (min–max) across
repeats**.

## The corpus

`bench/generate.py` writes files in the formats the adapters actually parse:

| Harness | Files | Indexed messages | Shape |
| --- | --- | --- | --- |
| Claude Code | 1,042 (incl. subagents) | 30,252 | multi-line assistant turns: text, `tool_use` lines and `tool_result` user lines in between, `ai-title`, snapshots, injected `<system-reminder>`, `isMeta` lines, slash commands |
| Codex CLI | 352 | 11,000 | `session_meta`, developer and injected `<environment_context>` messages (dropped), `reasoning`, `function_call` + output, `event_msg` duplicates |
| Pi | 215 | 8,250 | `session` header, `model_change`, thinking + `toolCall` blocks, `toolResult` messages |
| Generic JSONL | 38 | 5,753 | a support-bot log mapped with `[[sources.jsonl]]` |
| **Total** | **1,647** | **55,255** | 347 MB of JSONL, 51 MB of indexed text |

"Indexed messages" counts what priorlog stores: an assistant turn with its tool calls is one
message, and tool output and injected context are not indexed. `run.py` checks the count from
`priorlog status` against the generator's manifest on every repeat (they matched exactly).

Sessions are mostly short (70% have 1–8 exchanges), with a tail of up to 200 exchanges. Messages
are mostly short (median 380 characters), with some multi-KB pastes and code blocks and a few
of 20–40 KB. Tool outputs range from 40 bytes to 30 KB; they are parsed but never indexed. Text
mixes Zipf-distributed prose words, about 6,000 code identifiers, 3,000 file paths, error
names and technical phrases. About 0.5% of messages contain a fake credential or email, so
redaction has real work to do.

## Results

Final run: 2026-11-06 at commit `e2ca2b5`, 3 repeats, 1-minute load average 2.4–2.7. Medians
are shown, with min–max in brackets. Raw numbers: `bench/results/2026-11-06.json`.

### Indexing and sync

| Phase | Time | Throughput | Peak RSS | DB on disk |
| --- | --- | --- | --- | --- |
| Cold full index, 55,255 msgs from an empty index | **21.8 s** (21.7–22.5) | **2,536 msgs/s** (2,459–2,551), 15.9 MB/s of JSONL | 34 MB | **214 MB** |
| No-op sync, 1,647 files, nothing changed | **151 ms** (150–153) | | 30 MB | |
| Append sync, +600 msgs (1.1%) in 50 files | **799 ms** (789–901) | | 32 MB | 215 MB |

Each sync runs in a fresh child process. The time is the `priorlog.sync.sync()` call; the whole
process, including interpreter start and imports, adds ~65 ms (cold 21.9 s, no-op 214 ms,
append 864 ms). RSS is the process high-water mark (`VmHWM`); 26 MB of it is the interpreter and
imports, before any sync work. The append sync reported exactly the 600 new messages in all 3
repeats. Re-read open assistant turns at the end of each file are not counted twice.

### Search, in-process

`priorlog.query.search(store, q)` with the default limit of 10, timed with
`time.perf_counter`. 360 queries per repeat, run in shuffled order after an untimed warm-up of 20.
"Matches" is the number of messages that satisfied the query, before the top 10 were picked.

| Query kind | n | p50 ms | p95 ms | p99 ms | median matches | max matches |
| --- | --- | --- | --- | --- | --- | --- |
| 1 term, common (`the`, `should`, top identifiers) | 20 | 86.2 (83.4–86.2) | 196 (188–222) | 201 (199–224) | 15,168 | 52,177 |
| 1 term, mid-frequency identifier or error name | 20 | 15.1 (15.0–15.1) | 25.6 (25.5–26.7) | 26.5 (25.7–28.8) | 377 | 1,007 |
| 1 term, rare identifier | 20 | 10.6 (10.4–10.7) | 17.7 (16.7–19.7) | 19.9 (19.3–20.0) | 18 | 152 |
| 1 term, matches nothing | 20 | 0.39 (0.39–0.42) | 0.53 (0.48–0.55) | 0.57 (0.49–0.57) | 0 | 0 |
| 2 terms that occur together in a message | 40 | 32.6 (31.8–33.6) | 164 (163–182) | 181 (180–195) | 1,062 | 24,448 |
| 2 terms, random pair | 40 | 14.3 (13.8–15.5) | 30.8 (30.0–31.5) | 44.6 (43.0–46.5) | 9 | 439 |
| 3 terms that occur together in a message | 40 | 34.5 (32.9–34.5) | 72.0 (64.8–75.5) | 96.8 (95.8–99.4) | 114 | 5,171 |
| 3 terms, random | 40 | 27.7 (26.2–27.8) | 69.0 (67.8–70.4) | 97.7 (96.0–104.8) | 3 | 1,391 |
| quoted phrase (`"token bucket"`, …) | 80 | 12.3 (12.2–12.6) | 39.3 (39.3–39.8) | 78.9 (76.9–80.5) | 501 | 15,422 |
| **short terms only (< 3 chars, `LIKE` scan)** | 20 | **119 (119–122)** | **165 (154–170)** | **167 (155–178)** | 31,653 | 51,716 |
| short term + a longer term | 20 | 12.9 (12.5–13.6) | 20.9 (19.1–22.4) | 23.6 (22.7–23.8) | 204 | 896 |
| **all 360 queries** | 360 | **18.6** (18.6–19.6) | **123** (122–129) | **184** (166–187) | 217 | 52,177 |

"Occur together" queries are made of words sampled from one random indexed message, the way
you search for something you remember. Random multi-term queries mostly match nothing or very
little, so they show the floor.

### Read and CLI

| Operation | n | p50 | p95 | p99 |
| --- | --- | --- | --- | --- |
| `query.read(store, cite)`: the cited message ± 4, in-process | 300 | 0.1 ms | 0.1 ms | 0.1 ms |
| `query.read(..., source=True)`: also re-reads the original lines and redacts and deny-checks their decoded JSON values | 100 | 0.8 ms (0.8–1.0) | 8.2 ms (8.1–9.4) | 13.4 ms (13.2–14.1) |
| `priorlog search …` CLI, end to end, process start included | 20 | **78 ms** (78–81) | **137 ms** (135–153) | 205 ms (199–212) |
| `priorlog --version` (process start floor) | 5 | 52.6 ms (51.4–58.5) | 60.4 ms | 61.7 ms |

The CLI sample is 20 queries drawn from the mid-frequency, co-occurring and phrase kinds. About
50–60 ms of every CLI call is starting Python and importing priorlog.

## Before and after the v0.1.0 performance fixes

The first full run of this benchmark (commit `ce62db6`) found four problems, and they were fixed
before release:

1. Search ranks, caps hits per session, limits and counts inside SQLite. Before, it fetched every
   matching row and sorted it in Python.
2. A cold sync into an empty index drops the FTS triggers and builds the trigram index once at
   the end (`'rebuild'`).
3. The path policy caches each directory's deny verdict.
4. A correctness fix: slash-command arguments were dropped when anything sat between
   `</command-name>` and `<command-args>`.

The first version of fix 1 ran the ranking and the `COUNT` as two statements, which ran the FTS
`MATCH` and `bm25` twice. That made specific queries (the common case) 20–50% slower than
before, even though broad queries and the tail got faster. The benchmark caught it. The shipped
version does everything in **one statement**: a `MATERIALIZED` CTE for the match, `ROW_NUMBER()`
for the per-session cap, and `COUNT(*) OVER ()` / `SUM(rn = 1) OVER ()` for the totals. A
side-by-side A/B on the same index, at low load, returned identical hit lists for all 360 queries
and was faster than both earlier versions at p50: rare 9.0 ms, mid 14.5 ms, no match 0.04 ms,
common 76 ms, co-occurring two-term 30 ms. `tests/test_citations.py` checks that the totals match
a direct `COUNT`.

Medians from two full runs on the same machine, corpus and `run.py`, at similar load (before:
1-minute load 1.5–2.9; final: 2.4–2.7). An intermediate two-statement version was also measured:
its rare-term p50 was 14.2 ms. Its raw results file was not kept, so it is not in the table.

| Metric | Before (`ce62db6`) | Final (`e2ca2b5`) | Change |
| --- | --- | --- | --- |
| Cold full index | 36.2 s (1,528 msgs/s) | 21.8 s (2,536 msgs/s) | 1.7× faster |
| No-op sync | 329 ms | 151 ms | 2.2× faster |
| Append sync (+600 msgs) | 804 ms | 799 ms | about the same |
| Peak RSS (cold index) | 31 MB | 34 MB | +3 MB |
| DB on disk after cold index | 212 MB | 214 MB | +1% |
| Search p50 / p95 / p99, all 360 | 18.1 / 188 / 266 ms | 18.6 / 123 / 184 ms | p50 about the same; p95 35% and p99 31% faster |
| 1 term rare, p50 | 9.4 ms | 10.6 ms | 13% slower |
| 1 term mid, p50 | 15.9 ms | 15.1 ms | 5% faster |
| 1 term common, p50 / p95 | 151 / 318 ms | 86 / 196 ms | 1.6–1.8× faster |
| Short terms only, p50 | 188 ms | 119 ms | 1.6× faster |
| Quoted phrase, p50 | 12.3 ms | 12.3 ms | same |
| `read --source`, p95 | 3.5 ms | 8.2 ms | 2.3× slower (decoded-value redaction and deny checks) |
| CLI search p50 / p95 | 68.6 / 171 ms | 78 / 137 ms | p50 14% slower; p95 20% faster |

The fixes leave typical queries about where they were and cut the worst cases by a third, because
broad queries no longer pull every matching row into Python. Rare-term queries pay about 1 ms for
SQLite's window function and join over the match set. The cold-index and no-op-sync gains come
from fixes 2 and 3. `read --source` got slower because it now redacts and deny-checks each decoded
JSON value, but it stays under 15 ms at p99. The CLI p50 sits within process-start noise
(`priorlog --version` alone ranges from 51 to 64 ms). Raw numbers:
`bench/results/2026-11-05-before-fixes.json` (before), `bench/results/2026-11-06.json` (final)
and `bench/results/2026-11-05.json` (the `80c36df` cross-check).

## Where the time goes

Profiles were taken with `cProfile`, and the side experiments with short scripts on the same
corpus and index, at low load. They are not part of `run.py`.

**Cold index (after the fixes).** The redactor's regexes are now the largest single cost, at
about 40%. SQLite takes about 40%, which is the row inserts plus the one-time FTS `rebuild` at
the end (~8 s under the profiler). JSON parsing is about 7%, and the policy check is under 2%.
Before the fixes, about two thirds of the time went into the per-row FTS trigger. A separate
experiment loaded the same 51 MB of message text into bare SQLite tables:

| Same 55k texts, inserted one row at a time in one transaction | Time | DB size |
| --- | --- | --- |
| plain table, no FTS | 0.2 s | 59 MB |
| FTS5 `unicode61` (word tokens), kept in sync by a trigger | 5.1 s | 78 MB |
| FTS5 `trigram`, kept in sync by a trigger (priorlog before the fix; still used for incremental syncs) | 25.9 s | 203 MB |
| FTS5 `trigram`, built once at the end with `INSERT INTO fts(fts) VALUES('rebuild')` (cold sync now) | 8.9 s | 205 MB |
| FTS5 `trigram` via trigger, `PRAGMA cache_size` = 64 MB | 24.6 s | 203 MB |

The trigram tokenizer is what makes substring search work in any language. It costs about
2–5× the indexing time and 2.6× the disk of word tokens. A larger page cache does not help.

Of the redaction time, a single pattern (`secret_assignment`, the `KEY=value` rule) takes
about a third, because its leading lazy `[\w.\-]*?` is retried at every word boundary. This
is not fixed yet.

**No-op sync.** Before the fix, almost all of it was the path policy: about 23 deny globs
matched with `fnmatch` against every file and every ancestor directory, ~300 calls per file
here. With the per-directory cache, what is left is mostly `Path.resolve()` (one `lstat` per
path component) and walking `path.parents`, at about 0.08 ms per file. The benchmark corpus sits
12 directories deep, while a real `~/.claude/projects/<project>/<uuid>.jsonl` is about 6 deep.

**Search.** Ranking now happens in SQLite, so only the top 10 rows (and their text) reach
Python. Cost still grows with the number of matches, because `bm25` is computed for every match
before the top 10 are chosen. For the query `the` (52k matches), `search` takes ~190 ms, down
from ~400 ms. Rare terms are not free either: a long identifier is split into many trigrams, and
FTS5 intersects the posting list of each one, including common trigrams like `ent` or `_pa`.

## What this means, and the limits

- **Search is fast for specific queries and slower for common ones.** Identifiers, paths,
  error names, phrases and words that occur together return in 15–40 ms at p50. A query that
  matches most of the corpus (`the`, `error`, a 2-letter term) takes 0.1–0.2 s at 55k
  messages, and that cost grows linearly with corpus size.
- **Terms shorter than 3 characters** can't use the trigram index. Alone, they become
  `LIKE '%xx%'` scans over every message (see "short terms only": the slowest category).
  Combined with a longer term, the trigram index narrows the rows first, and the `LIKE`
  filter is cheap.
- **Terms are ANDed substrings.** `rate limiter` matches messages containing both `rate` and
  `limiter` anywhere, including inside other words. Quoted phrases match the exact substring.
- **Cold index** runs at about 2,500 messages/s on one core (sync is single-threaded). It is
  a one-time cost: later syncs read only appended bytes. It is now bound by redaction and
  SQLite about equally, not by reading files.
- **Redaction cost is an open item.** `secret_assignment` alone is about a third of
  redaction time, which is about 40% of a cold index. Every new message pays it.
- **Incremental sync** costs a fixed ~0.08 ms per transcript file, plus ~1 ms per new
  message. New rows go through the per-row FTS trigger, which is the slow path in the table
  above. With thousands of transcript files, a no-op sync costs around 100–200 ms. The MCP
  server runs one at most every `auto_sync_seconds` (default 300).
- **CLI latency** is dominated by process start. `priorlog --version` alone takes 51–64 ms of a
  typical 78 ms search. The MCP server is a long-lived process, so it pays the in-process
  numbers.
- **Disk:** the index is about 4× the indexed text and about 60% of the raw JSONL size here.
  Real transcripts with larger tool outputs have a smaller ratio, because tool output is not
  indexed.
- **Warm cache only.** The corpus and index were in the OS page cache, since the copy and the
  index were just written. Cold-cache numbers (after a reboot) would be higher and were not
  measured, because dropping caches needs root.
- **Synthetic text.** The vocabulary is Zipf-distributed, but it is not real conversation.
  Match counts per query kind are shown so you can judge how representative each row is.
  Real corpora have longer tool outputs and more repetition.
- Peak RSS stays around 30 MB, because sync streams one file at a time and commits once per
  harness.
