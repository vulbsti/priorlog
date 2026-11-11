"""Incremental sync: bring the index up to date with every configured transcript source.

Per file, the cost is one `stat` when nothing changed. A file that grew is read from the byte
offset where the last sync stopped. A file whose inode changed, or that shrank, is re-indexed
from scratch. Files that the policy denies are never opened.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .adapters.base import Adapter
from .adapters.claude import ClaudeAdapter
from .adapters.codex import CodexAdapter
from .adapters.jsonl import JsonlAdapter
from .adapters.pi import PiAdapter
from .config import Config
from .policy import Policy
from .store import Store


def build_adapters(cfg: Config) -> list[Adapter]:
    adapters: list[Adapter] = []
    if cfg.claude_roots or cfg.claude_desktop_roots:
        adapters.append(ClaudeAdapter(cfg.claude_roots, cfg.claude_desktop_roots))
    if cfg.codex_roots:
        adapters.append(CodexAdapter(cfg.codex_roots))
    if cfg.pi_roots:
        adapters.append(PiAdapter(cfg.pi_roots))
    adapters += [JsonlAdapter(s) for s in cfg.jsonl_sources]
    return adapters


@dataclass
class SyncReport:
    files_seen: int = 0
    files_changed: int = 0
    files_denied: int = 0
    new_messages: int = 0
    seconds: float = 0.0
    unknown_types: Counter = field(default_factory=Counter)
    per_harness: Counter = field(default_factory=Counter)

    def line(self) -> str:
        return (
            f"{self.files_seen} files ({self.files_changed} changed, {self.files_denied} denied), "
            f"{self.new_messages} new messages in {self.seconds:.2f}s"
        )


@contextlib.contextmanager
def _lock(cfg: Config):
    path = Path(cfg.db_path).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def sync(cfg: Config, *, harness: str | None = None) -> SyncReport:
    t0 = time.monotonic()
    report = SyncReport()
    policy = Policy(cfg)
    with _lock(cfg), Store(cfg) as store:
        bulk = store.is_empty()
        if bulk:
            store.begin_bulk()
        try:
            _sync_adapters(store, cfg, policy, report, harness)
        finally:
            if bulk:
                store.end_bulk()  # also on error, so the FTS index always matches the messages
        if report.unknown_types:
            old = json.loads(store.get_meta("unknown_types", "{}") or "{}")
            for k, v in report.unknown_types.items():
                old[k] = old.get(k, 0) + v
            store.set_meta("unknown_types", json.dumps(old, sort_keys=True))
        store.set_meta("last_sync", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        store.set_meta("last_sync_epoch", str(time.time()))
        store.commit()
    report.seconds = time.monotonic() - t0
    return report


def _sync_adapters(
    store: Store, cfg: Config, policy: Policy, report: SyncReport, harness: str | None
) -> None:
    for adapter in build_adapters(cfg):
        if harness and adapter.harness != harness and not adapter.harness.startswith(harness + ":"):
            continue
        adapter.policy = policy
        paths = adapter.discover()
        adapter.prepare(paths)
        for path in paths:
            report.files_seen += 1
            if not adapter.allowed(path):  # the policy, plus any adapter-specific tightening
                report.files_denied += 1
                continue
            try:
                added = _sync_file(store, adapter, path, report)
            except FileNotFoundError:
                continue  # removed while we were scanning
            if added is not None:
                report.files_changed += 1
                report.new_messages += added
                report.per_harness[adapter.harness] += added
        adapter.post_sync(store, policy)
        store.commit()


def _sync_file(store: Store, adapter: Adapter, path: Path, report: SyncReport) -> int | None:
    """Index new lines of one file; None when it was unchanged."""
    st = path.stat()
    row = store.file_state(path, adapter.harness)
    if row["inode"] is not None and (row["inode"] != st.st_ino or st.st_size < row["offset"]):
        store.reset_file(row["id"])
        row = store.file_state(path, adapter.harness)
    elif row["inode"] is not None and st.st_size == row["offset"] and not row["tail"]:
        return None
    elif row["inode"] is not None and st.st_size == row["size"] and st.st_mtime == row["mtime"]:
        return None  # only the open tail is pending and nothing was appended
    offset, line, dropped = store.rewind_tail(row)
    carry = json.loads(row["carry"]) if row["carry"] else {}
    batch = adapter.parse(path, offset, line, carry)
    for t in batch.unknown_types:
        # Line types come from the transcript: only record ones that look like type names.
        ok = re.fullmatch(r"[a-z][a-z_.\-]{0,39}", t) and not store._denied(t)
        name = t if ok else "other"
        report.unknown_types[f"{adapter.harness}:{name}"] += 1
    return store.apply(row["id"], batch, st) - dropped  # net: a re-read open turn is not "new"


def maybe_sync(cfg: Config) -> SyncReport | None:
    """Run a sync when the index is older than `auto_sync_seconds` (0 disables)."""
    if cfg.auto_sync_seconds <= 0:
        return None
    try:
        with Store(cfg) as store:
            last = float(store.get_meta("last_sync_epoch", "0") or 0)
    except Exception:  # noqa: BLE001 - a missing/locked db just means "sync now"
        last = 0.0
    if time.time() - last < cfg.auto_sync_seconds:
        return None
    return sync(cfg)
