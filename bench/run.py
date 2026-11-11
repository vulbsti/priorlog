"""Benchmark priorlog: cold index, incremental sync, search and read latency.

    uv run python bench/generate.py CORPUS            # once
    uv run python bench/run.py CORPUS [--repeats 3]

Each repeat starts from a fresh copy of CORPUS and an empty index:

  1. cold full index      `sync()` in a child process (wall time, peak RSS), DB size on disk
  2. no-op sync           nothing changed
  3. append sync          ~1% new messages appended across 50 files, then `sync()`
  4. search (in-process)  every query in the query set through `priorlog.query.search`
  5. read (in-process)    `priorlog.query.read` of citations taken from the search hits
  6. search (CLI)         a sample of `priorlog search` invocations, process start included

Only stdlib is used. HOME, PRIORLOG_HOME and PRIORLOG_CONFIG point into the work directory, so
nothing outside the corpus is read. Results go to bench/results/<date>.json and a markdown
summary is printed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import re
import resource
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
import generate  # noqa: E402

MARKER = ".priorlog-bench-work"
SHORT = [
    "db",
    "io",
    "ui",
    "id",
    "os",
    "ok",
    "is",
    "if",
    "to",
    "it",
    "we",
    "be",
    "on",
    "as",
    "so",
    "no",
    "up",
    "go",
    "js",
    "ts",
]


# --------------------------------------------------------------------------- child process


def peak_rss_mb() -> float:
    """Peak RSS of this process in MB. On Linux, VmHWM from /proc: unlike ru_maxrss it starts
    over at exec, so a child does not inherit the parent's high-water mark."""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024 if sys.platform == "darwin" else 1024)


def child_sync(cfg_path: str) -> None:
    """Run one sync in this (fresh) process and print timing + peak RSS as JSON."""
    from priorlog.config import load
    from priorlog.sync import sync

    cfg = load(Path(cfg_path))
    rss_before = peak_rss_mb()
    t0 = time.perf_counter()
    rep = sync(cfg)
    seconds = time.perf_counter() - t0
    print(
        json.dumps(
            {
                "seconds": seconds,
                "files_seen": rep.files_seen,
                "files_changed": rep.files_changed,
                "new_messages": rep.new_messages,
                "rss_base_mb": rss_before,
                "rss_peak_mb": peak_rss_mb(),
            }
        )
    )


def run_sync(cfg_path: Path) -> dict:
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, __file__, "--child-sync", str(cfg_path)], capture_output=True, text=True, check=True
    )
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    out["process_wall"] = time.perf_counter() - t0
    return out


# --------------------------------------------------------------------------- query set


def build_queries(seed: int) -> list[tuple[str, str]]:
    """(category, query) pairs. Terms come from the generator's ranked vocabularies."""
    v = generate.Vocab(seed)
    rng = random.Random(seed + 7)
    common = [w for w in v.prose if len(w) >= 3][:30] + v.idents[:10]
    mid = v.idents[100:700] + v.errors[5:20]
    rare = v.idents[4500:6000]
    letters = "ghjkmnpqvwxyz"  # outside hex, so no accidental hits in ids or hashes

    def none() -> str:
        return "".join(rng.choice(letters) for _ in range(9))

    def pick(xs: list[str], n: int) -> list[str]:
        return rng.sample(xs, n)

    q: list[tuple[str, str]] = []
    q += [("1-term common", t) for t in pick(common, 20)]
    q += [("1-term mid", t) for t in pick(mid, 20)]
    q += [("1-term rare", t) for t in pick(rare, 20)]
    q += [("1-term no match", none()) for _ in range(20)]
    two = [f"{a} {b}" for a, b in zip(pick(mid, 15), pick(mid, 15), strict=True)]
    two += [f"{a} {b}" for a, b in zip(pick(common, 10), pick(rare, 10), strict=True)]
    two += [f"{a} {b}" for a, b in zip(pick(rare, 10), pick(mid, 10), strict=True)]
    two += [f"{a} {none()}" for a in pick(mid, 5)]
    q += [("2-term random", s) for s in two]
    three = [" ".join(pick(mid, 3)) for _ in range(15)]
    three += [f"{rng.choice(common)} {rng.choice(mid)} {rng.choice(rare)}" for _ in range(10)]
    three += [f"{rng.choice(common)} {rng.choice(common)} {rng.choice(mid)}" for _ in range(10)]
    three += [f"{rng.choice(mid)} {rng.choice(mid)} {none()}" for _ in range(5)]
    q += [("3-term random", s) for s in three]
    phrases = [f'"{p}"' for p in v.phrases]
    phrases += [f'"{none()} {rng.choice(v.prose)}"' for _ in range(70 - len(phrases))]
    q += [("quoted phrase", s) for s in phrases]
    q += [("short (<3 chars) only", t) for t in SHORT[:20]]
    q += [("short + long term", f"{rng.choice(SHORT)} {rng.choice(mid)}") for _ in range(20)]
    return q


def known_item_queries(store, seed: int) -> list[tuple[str, str]]:
    """Queries made of words that occur together in one indexed message, the way people search
    for something they remember. Message ids are identical in every repeat (files are indexed in
    sorted order), so the same queries come out each time."""
    rng = random.Random(seed + 11)
    top = store.conn.execute("SELECT MAX(id) FROM messages").fetchone()[0]
    word = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
    span = re.compile(r"(?<![\w`])([a-z]{3,} [a-z]{3,} [a-z]{3,})(?![\w`])")
    want = {"2-term co-occurring": 40, "3-term co-occurring": 40, "quoted phrase": 10}
    out: list[tuple[str, str]] = []
    while any(want.values()):
        row = store.conn.execute("SELECT text FROM messages WHERE id = ?", (rng.randint(1, top),)).fetchone()
        words = sorted(set(word.findall(row[0]))) if row else []
        if len(words) < 6:
            continue
        cat = rng.choice([c for c, n in want.items() if n])
        if cat == "quoted phrase":
            spans = span.findall(row[0])
            if not spans:
                continue
            q = f'"{rng.choice(spans)}"'
        else:
            q = " ".join(rng.sample(words, 2 if cat.startswith("2") else 3))
        out.append((cat, q))
        want[cat] -= 1
    return out


# --------------------------------------------------------------------------- helpers


def pct(xs: list[float], p: int) -> float:
    if len(xs) == 1:
        return xs[0]
    return statistics.quantiles(xs, n=100, method="inclusive")[p - 1]


def summary(xs: list[float]) -> dict:
    return {"p50": pct(xs, 50), "p95": pct(xs, 95), "p99": pct(xs, 99), "n": len(xs), "max": max(xs)}


def spread(vals: list[float]) -> dict:
    return {"median": statistics.median(vals), "min": min(vals), "max": max(vals), "values": vals}


def db_bytes(db: Path) -> int:
    return sum(p.stat().st_size for p in (db, Path(f"{db}-wal"), Path(f"{db}-shm")) if p.exists())


def machine() -> dict:
    def first(path: str, key: str) -> str | None:
        try:
            for line in Path(path).read_text().splitlines():
                if line.startswith(key):
                    return line.split(":", 1)[1].strip() if ":" in line else line.split("=", 1)[1].strip('"')
        except OSError:
            return None
        return None

    from priorlog import __version__

    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=BENCH
    )
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src"], capture_output=True, text=True, cwd=BENCH
    )
    return {
        "cpu": first("/proc/cpuinfo", "model name") or platform.processor(),
        "logical_cpus": os.cpu_count(),
        "mem_total": first("/proc/meminfo", "MemTotal"),
        "os": first("/etc/os-release", "PRETTY_NAME=") or platform.platform(),
        "kernel": platform.release(),
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "priorlog": __version__,
        "commit": commit.stdout.strip() or None,
        # True when src/ differs from that commit: the numbers then belong to an uncommitted tree.
        "src_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
    }


def fresh_work(work: Path, corpus: Path) -> Path:
    """Copy the corpus into an empty work dir (only ever deletes a dir this script created)."""
    if work.exists():
        if not (work / MARKER).exists():
            raise SystemExit(f"{work} exists and was not created by bench/run.py; refusing to delete it")
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / MARKER).write_text("created by bench/run.py\n")
    dst = work / "corpus"
    shutil.copytree(corpus, dst, ignore=shutil.ignore_patterns("data", "config.toml"))
    (work / "home").mkdir()
    return dst


# --------------------------------------------------------------------------- one repeat


def one_repeat(
    rep: int, corpus: Path, work: Path, queries: list[tuple[str, str]], cli_n: int, seed: int
) -> dict:
    from priorlog import query
    from priorlog.config import load
    from priorlog.store import Store

    copy = fresh_work(work, corpus)
    db = work / "data" / "index.sqlite3"
    cfg_path = generate.write_config(copy, db)
    os.environ.update(
        HOME=str(work / "home"), PRIORLOG_HOME=str(work / "data"), PRIORLOG_CONFIG=str(cfg_path)
    )
    res: dict = {"load_before": os.getloadavg()}
    print(f"[rep {rep}] cold index ...", file=sys.stderr, flush=True)
    res["cold"] = run_sync(cfg_path)
    res["cold"]["db_bytes"] = db_bytes(db)
    cfg = load(cfg_path)
    with Store(cfg) as store:
        res["status"] = {k: v["messages"] for k, v in query.status(store)["harnesses"].items()}
    print(f"[rep {rep}] no-op sync ...", file=sys.stderr, flush=True)
    res["noop"] = run_sync(cfg_path)
    appended = generate.append_round(copy, seed=seed)
    print(
        f"[rep {rep}] append sync ({appended['expected_new_messages']} msgs) ...", file=sys.stderr, flush=True
    )
    res["append"] = run_sync(cfg_path)
    res["append"]["expected_new_messages"] = appended["expected_new_messages"]
    res["append"]["files_appended"] = appended["files"]
    res["append"]["db_bytes"] = db_bytes(db)

    if not any(c.endswith("co-occurring") for c, _ in queries):
        with Store(cfg) as store:
            queries += known_item_queries(store, seed)
    print(f"[rep {rep}] search x{len(queries)} ...", file=sys.stderr, flush=True)
    order = list(range(len(queries)))
    random.Random(seed + rep).shuffle(order)
    searches: list[dict] = []
    cites: list[str] = []
    with Store(cfg) as store:
        for _, q in queries[:20]:  # warm-up, untimed
            query.search(store, q)
        for i in order:
            cat, q = queries[i]
            t0 = time.perf_counter()
            r = query.search(store, q)
            ms = (time.perf_counter() - t0) * 1000
            searches.append(
                {"cat": cat, "q": q, "ms": ms, "matches": r["total_matches"], "hits": len(r["hits"])}
            )
            if cat in ("1-term mid", "1-term rare", "2-term co-occurring", "quoted phrase"):
                cites += [h["cite"] for h in r["hits"]]
        cites = sorted(set(cites))
        random.Random(seed).shuffle(cites)
        cites = cites[:300]
        print(f"[rep {rep}] read x{len(cites)} ...", file=sys.stderr, flush=True)
        reads, reads_src = [], []
        for c in cites:
            t0 = time.perf_counter()
            query.read(store, c)
            reads.append((time.perf_counter() - t0) * 1000)
        for c in cites[:100]:
            t0 = time.perf_counter()
            query.read(store, c, source=True, config=cfg)
            reads_src.append((time.perf_counter() - t0) * 1000)
    res["searches"] = searches
    res["read_ms"] = reads
    res["read_source_ms"] = reads_src

    exe = str(Path(sys.executable).with_name("priorlog"))
    sample = [
        q
        for c, q in queries
        if c in ("1-term mid", "2-term co-occurring", "3-term co-occurring", "quoted phrase")
    ]
    sample = random.Random(seed + 99).sample(sample, cli_n)
    print(f"[rep {rep}] CLI x{cli_n} ...", file=sys.stderr, flush=True)
    cli, floor = [], []
    for _ in range(5):
        t0 = time.perf_counter()
        subprocess.run([exe, "--version"], capture_output=True, check=True)
        floor.append((time.perf_counter() - t0) * 1000)
    for q in sample:
        t0 = time.perf_counter()
        p = subprocess.run([exe, "--config", str(cfg_path), "search", q], capture_output=True, text=True)
        cli.append((time.perf_counter() - t0) * 1000)
        if p.returncode not in (0, 3):
            raise SystemExit(f"priorlog search {q!r} failed: {p.stderr}")
    res["cli_search_ms"] = cli
    res["cli_version_ms"] = floor
    res["load_after"] = os.getloadavg()
    return res


# --------------------------------------------------------------------------- aggregate + report


def aggregate(reps: list[dict], manifest: dict) -> dict:
    agg: dict = {}
    for phase in ("cold", "noop", "append"):
        agg[phase] = {
            k: spread([r[phase][k] for r in reps])
            for k in (
                "seconds",
                "process_wall",
                "rss_peak_mb",
                "rss_base_mb",
                "new_messages",
                "files_changed",
            )
        }
    agg["cold"]["msgs_per_s"] = spread([r["cold"]["new_messages"] / r["cold"]["seconds"] for r in reps])
    agg["cold"]["mb_per_s"] = spread([manifest["jsonl_bytes"] / 1e6 / r["cold"]["seconds"] for r in reps])
    agg["cold"]["db_mb"] = spread([r["cold"]["db_bytes"] / 1e6 for r in reps])
    agg["append"]["db_mb"] = spread([r["append"]["db_bytes"] / 1e6 for r in reps])
    agg["append"]["expected_new_messages"] = reps[0]["append"]["expected_new_messages"]
    order = [
        "1-term common",
        "1-term mid",
        "1-term rare",
        "1-term no match",
        "2-term co-occurring",
        "2-term random",
        "3-term co-occurring",
        "3-term random",
        "quoted phrase",
        "short (<3 chars) only",
        "short + long term",
    ]
    seen = {s["cat"] for s in reps[0]["searches"]}
    cats = [c for c in order if c in seen] + sorted(seen - set(order))
    agg["search"] = {}
    for cat in [*cats, "all"]:
        per = [summary([s["ms"] for s in r["searches"] if cat in ("all", s["cat"])]) for r in reps]
        matches = [s["matches"] for s in reps[0]["searches"] if cat in ("all", s["cat"])]
        agg["search"][cat] = {
            "n": per[0]["n"],
            **{p: spread([x[p] for x in per]) for p in ("p50", "p95", "p99", "max")},
            "median_matches": statistics.median(matches),
            "max_matches": max(matches),
            "no_hit_queries": sum(1 for m in matches if m == 0),
        }
    for key in ("read_ms", "read_source_ms", "cli_search_ms", "cli_version_ms"):
        per = [summary(r[key]) for r in reps]
        agg[key] = {
            "n": per[0]["n"],
            **{p: spread([x[p] for x in per]) for p in ("p50", "p95", "p99", "max")},
        }
    return agg


def fmt(s: dict, scale: float = 1.0, digits: int = 1, unit: str = "") -> str:
    m, lo, hi = (s[k] * scale for k in ("median", "min", "max"))
    return f"{m:.{digits}f}{unit} ({lo:.{digits}f}–{hi:.{digits}f})"


def markdown(result: dict) -> str:
    a, m = result["aggregate"], result["manifest"]
    n = result["repeats"]
    out = [
        f"Corpus: {m['expected_total']:,} indexed messages in {m['files_total']:,} files "
        f"({m['jsonl_bytes'] / 1e6:.0f} MB of JSONL). {n} repeats; median (min–max).",
        "",
        "| Phase | Time | Throughput | Peak RSS | DB on disk |",
        "| --- | --- | --- | --- | --- |",
        f"| Cold full index ({a['cold']['new_messages']['median']:,.0f} msgs) | {fmt(a['cold']['seconds'], unit=' s')} "
        f"| {fmt(a['cold']['msgs_per_s'], digits=0)} msgs/s, {fmt(a['cold']['mb_per_s'])} MB/s | "
        f"{fmt(a['cold']['rss_peak_mb'], digits=0, unit=' MB')} | {fmt(a['cold']['db_mb'], digits=0, unit=' MB')} |",
        f"| No-op sync ({m['files_total']:,} files, 0 changed) | {fmt(a['noop']['seconds'], 1000, 0, ' ms')} | | "
        f"{fmt(a['noop']['rss_peak_mb'], digits=0, unit=' MB')} | |",
        f"| Append sync (+{a['append']['new_messages']['median']:,.0f} msgs in "
        f"{a['append']['files_changed']['median']:.0f} files) | {fmt(a['append']['seconds'], 1000, 0, ' ms')} | | "
        f"{fmt(a['append']['rss_peak_mb'], digits=0, unit=' MB')} | {fmt(a['append']['db_mb'], digits=0, unit=' MB')} |",
        "",
        f"Process wall time including interpreter start and imports: cold {fmt(a['cold']['process_wall'], unit=' s')}, "
        f"no-op {fmt(a['noop']['process_wall'], 1000, 0, ' ms')}, append {fmt(a['append']['process_wall'], 1000, 0, ' ms')}. "
        f"RSS after imports, before sync: {a['cold']['rss_base_mb']['median']:.0f} MB.",
        "",
        "In-process `priorlog.query.search` (limit 10, warm page cache), milliseconds:",
        "",
        "| Query kind | n | p50 | p95 | p99 | median matches | max matches |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cat, s in a["search"].items():
        out.append(
            f"| {cat} | {s['n']} | {fmt(s['p50'], digits=2)} | {fmt(s['p95'], digits=2)} | {fmt(s['p99'], digits=2)} "
            f"| {s['median_matches']:,.0f} | {s['max_matches']:,} |"
        )
    out += [
        "",
        "| Operation | n | p50 | p95 | p99 |",
        "| --- | --- | --- | --- | --- |",
    ]
    labels = {
        "read_ms": "`query.read` of a citation (in-process)",
        "read_source_ms": "`query.read(..., source=True)` (in-process)",
        "cli_search_ms": "`priorlog search` CLI, end to end",
        "cli_version_ms": "`priorlog --version` (process start floor)",
    }
    for key, label in labels.items():
        s = a[key]
        out.append(
            f"| {label} | {s['n']} | {fmt(s['p50'], digits=1)} ms | {fmt(s['p95'], digits=1)} ms | {fmt(s['p99'], digits=1)} ms |"
        )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("corpus", type=Path, nargs="?", help="corpus made by bench/generate.py")
    p.add_argument("--work", type=Path, help="scratch dir (default: <corpus>/../work); wiped each repeat")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--cli", type=int, default=20, help="CLI search invocations per repeat")
    p.add_argument("--out", type=Path, help="results JSON (default: bench/results/<date>.json)")
    p.add_argument("--child-sync", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.child_sync:
        child_sync(args.child_sync)
        return 0
    if args.corpus is None:
        p.error("corpus is required")
    corpus = args.corpus.resolve()
    manifest = json.loads((corpus / "manifest.json").read_text())
    work = (args.work or corpus.parent / "work").resolve()
    queries = build_queries(manifest["seed"])
    exp = manifest["expected_messages"]
    expected = {
        "claude": exp["claude"],
        "codex": exp["codex"],
        "jsonl:supportbot": exp["jsonl"],
        "pi": exp["pi"],
    }
    reps = []
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    for rep in range(args.repeats):
        reps.append(one_repeat(rep, corpus, work, queries, args.cli, manifest["seed"]))
        if reps[-1]["status"] != expected:
            print(f"WARNING: indexed {reps[-1]['status']} != expected {expected}", file=sys.stderr)
    result = {
        "started": started,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "machine": machine(),
        "manifest": manifest,
        "repeats": args.repeats,
        "queries": len(queries),
        "index_matches_manifest": all(r["status"] == expected for r in reps),
        "load_avg": [[r["load_before"], r["load_after"]] for r in reps],
        "aggregate": aggregate(reps, manifest),
        "raw": [{k: v for k, v in r.items()} for r in reps],
    }
    out = args.out or BENCH / "results" / f"{date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(markdown(result))
    print(f"\nresults: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
