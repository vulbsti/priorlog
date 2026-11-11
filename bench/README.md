# bench

The scripts behind [docs/benchmarks.md](../docs/benchmarks.md). Standard library only. Run
them from the repo root, and keep the corpus outside the repo:

```bash
uv run python bench/generate.py /tmp/priorlog-bench/corpus   # ~10 s, ~350 MB, 55k indexed messages
uv run python bench/run.py /tmp/priorlog-bench/corpus        # ~5 min for 3 repeats
```

- `generate.py` writes a seeded, deterministic corpus in the real on-disk formats (Claude Code
  project dirs with subagents, Codex rollouts, Pi sessions, one generic JSONL log), plus
  `config.toml` (index under `<corpus>/data`, auto sync off) and `manifest.json` (the exact
  message count priorlog should index, per harness). `--messages N` changes the size.
  `--append` adds one "1% growth" round to an existing corpus.
- `run.py` copies the corpus to `<corpus>/../work` (or `--work DIR`) for each repeat, starting
  with an empty index. It measures a cold full index, a no-op sync, an append sync,
  360 in-process searches, `read` of citations, and a sample of `priorlog search` CLI runs. It
  checks the indexed counts against the manifest, prints markdown tables, and writes the raw
  numbers to `bench/results/<date>.json`. `HOME`, `PRIORLOG_HOME` and `PRIORLOG_CONFIG` point
  into the work dir, so nothing real is read.

`run.py` deletes and recreates its work dir on every repeat. It refuses to delete a directory it
did not create (one without the `.priorlog-bench-work` marker).

Numbers depend on load. Check `uptime` first and run on a quiet machine.
