"""The SQLite index: one file under priorlog's own data dir, mode 0600.

Every write goes through `Store`, and `Store` runs redaction and the content deny rules on
every message, title and working directory before it touches the database. That is the
"broker": adapters produce raw text, but no raw text can reach the index or a client.

Tables
  files     one row per transcript file: byte offset / line reached, inode, size, adapter carry
  sessions  one row per conversation (id = "<harness>:<native id>")
  messages  redacted text + the file and line range it came from (the citation locator)
  fts       FTS5 trigram index over messages.text (substring search, any language)
  links     subagent / fork relations
  stats     counters: redactions per kind, dropped messages, malformed lines (never values)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .adapters.base import Batch, SessionInfo, short
from .config import Config
from .redact import Redactor

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  harness TEXT NOT NULL,
  inode INTEGER, size INTEGER, mtime REAL,
  offset INTEGER NOT NULL DEFAULT 0,
  line INTEGER NOT NULL DEFAULT 0,
  carry TEXT, tail TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  harness TEXT NOT NULL,
  native_id TEXT,
  title TEXT, title_rank INTEGER NOT NULL DEFAULT -1,
  cwd TEXT, branch TEXT,
  started_at TEXT, ended_at TEXT,
  parent_id TEXT, desktop_id TEXT, resume_cmd TEXT,
  file_id INTEGER REFERENCES files(id)
);
CREATE INDEX IF NOT EXISTS sessions_harness ON sessions(harness);
CREATE INDEX IF NOT EXISTS sessions_native ON sessions(native_id);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  role TEXT NOT NULL,
  ts TEXT,
  text TEXT NOT NULL,
  file_id INTEGER NOT NULL,
  line_start INTEGER NOT NULL,
  line_end INTEGER NOT NULL,
  UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS messages_file ON messages(file_id);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(text, content='messages', content_rowid='id', tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
  INSERT INTO fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
  INSERT INTO fts(fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TABLE IF NOT EXISTS links (
  from_id TEXT NOT NULL, to_id TEXT NOT NULL, kind TEXT NOT NULL,
  PRIMARY KEY (from_id, to_id, kind)
);
CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
"""

# A transcript-supplied session id (or timestamp) is stored as-is only when it is obviously not
# content: ids from a conservative character set that no redaction or deny rule touches, and
# timestamps that look like ISO 8601. Anything else is replaced (ids by a stable hash), so a
# user-mapped `session` field holding an email address can't leak through every citation.
_SAFE_NATIVE = re.compile(r"[A-Za-z0-9._:+\-]{1,200}")
_ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.,]+)?(?:Z|[+-]\d{2}:?\d{2})?")

_SESSION_FIELDS = (
    "harness",
    "native_id",
    "cwd",
    "branch",
    "started_at",
    "ended_at",
    "parent_id",
    "desktop_id",
    "resume_cmd",
    "file_id",
)


class Store:
    def __init__(self, config: Config, *, readonly: bool = False) -> None:
        self.config = config
        self.path = Path(config.db_path)
        self.redactor = Redactor(config)
        self.deny = config.deny_content
        self._ids: dict[str, str] = {}
        if not readonly:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not self.path.exists()
            if fresh:  # create it private before SQLite writes anything into it
                os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        if not readonly:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            self.conn.execute(
                "INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
            )
            self.conn.commit()
        else:
            self.conn.execute("PRAGMA query_only=ON")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ broker rules

    def _clean(self, text: str | None, counts: Counter) -> str | None:
        if text is None:
            return None
        result = self.redactor.redact(text)
        counts.update(result.counts)
        return result.text

    def _denied(self, text: str) -> bool:
        return denied(text, self.deny)

    def _safe_native(self, native: str) -> str:
        """`native` if it is plainly an id (safe characters, no deny match, untouched by
        redaction); otherwise a stable `h-<sha256 prefix>` of it."""
        if _SAFE_NATIVE.fullmatch(native) and not self._denied(native) and self.redactor(native) == native:
            return native
        return f"h-{hashlib.sha256(native.encode()).hexdigest()[:16]}"

    def safe_id(self, sid: str | None) -> str | None:
        if sid is None:
            return None
        cached = self._ids.get(sid)
        if cached is not None:
            return cached
        harness = batch_harness(sid)
        native = sid[len(harness) + 1 :] if sid.startswith(harness + ":") else sid
        safe_native = self._safe_native(native)
        safe = sid if safe_native == native else f"{harness}:{safe_native}"
        self._ids[sid] = safe
        return safe

    @staticmethod
    def safe_ts(ts: object) -> str | None:
        return ts if isinstance(ts, str) and _ISO_TS.fullmatch(ts.strip()) else None

    def bump(self, counts: Counter, prefix: str = "") -> None:
        for k, v in counts.items():
            if v:
                self.conn.execute(
                    "INSERT INTO stats(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = value + ?",
                    (prefix + k, v, v),
                )

    # ------------------------------------------------------------------ files

    def file_state(self, path: Path, harness: str) -> sqlite3.Row:
        key = str(path)
        row = self.conn.execute("SELECT * FROM files WHERE path = ?", (key,)).fetchone()
        if row is None:
            self.conn.execute("INSERT INTO files(path, harness) VALUES (?, ?)", (key, harness))
            row = self.conn.execute("SELECT * FROM files WHERE path = ?", (key,)).fetchone()
        return row

    def reset_file(self, file_id: int) -> None:
        """The file was truncated or replaced: forget everything indexed from it."""
        sids = [
            r[0]
            for r in self.conn.execute(
                "SELECT DISTINCT session_id FROM messages WHERE file_id = ?", (file_id,)
            )
        ]
        self.conn.execute("DELETE FROM messages WHERE file_id = ?", (file_id,))
        self.conn.execute(
            "UPDATE files SET offset = 0, line = 0, carry = NULL, tail = NULL WHERE id = ?", (file_id,)
        )
        for sid in sids:
            if not self.conn.execute(
                "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1", (sid,)
            ).fetchone():
                self.conn.execute(
                    "UPDATE sessions SET title = NULL, title_rank = -1 WHERE id = ? AND desktop_id IS NULL",
                    (sid,),
                )

    def rewind_tail(self, row: sqlite3.Row) -> tuple[int, int, int]:
        """Drop the open tail stored last time; return (offset, line, messages_dropped)."""
        tail = json.loads(row["tail"]) if row["tail"] else None
        if not tail:
            return row["offset"], row["line"], 0
        cur = self.conn.execute(
            "DELETE FROM messages WHERE session_id = ? AND seq >= ?", (tail["session"], tail["seq"])
        )
        return tail["offset"], tail["line"], max(cur.rowcount, 0)

    # ------------------------------------------------------------------ writes

    def apply(self, file_id: int, batch: Batch, stat: os.stat_result) -> int:
        """Store one adapter batch (already parsed from `file_id`). Returns new message count."""
        self._sanitize(batch)
        counts: Counter = Counter()
        dropped = 0
        for info in batch.sessions.values():
            self._upsert_session(info, counts, file_id)
        seqs: dict[str, int] = {}
        tail_seq = None
        added = 0
        for i, m in enumerate(batch.messages):
            if m.session not in seqs:
                if m.session not in batch.sessions:
                    self._upsert_session(SessionInfo(m.session, batch_harness(m.session)), counts, file_id)
                seqs[m.session] = self.conn.execute(
                    "SELECT COALESCE(MAX(seq), -1) + 1 FROM messages WHERE session_id = ?", (m.session,)
                ).fetchone()[0]
            if batch.tail and i == batch.tail.first_index:
                tail_seq = seqs[m.session]
            if self._denied(m.text):
                dropped += 1
                continue
            text = self._clean(m.text, counts)
            self.conn.execute(
                "INSERT INTO messages(session_id, seq, role, ts, text, file_id, line_start, line_end) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (m.session, seqs[m.session], m.role, m.ts, text, file_id, m.line_start, m.line_end),
            )
            seqs[m.session] += 1
            added += 1
            if m.role == "user":
                # Untitled sessions are named after their first accepted user message. The
                # text is already redacted, and denied messages never get here.
                self.conn.execute(
                    "UPDATE sessions SET title = ?, title_rank = 0 WHERE id = ? AND title_rank < 0",
                    (short(text), m.session),
                )
        for frm, to, kind in batch.links:
            self.conn.execute("INSERT OR IGNORE INTO links VALUES (?, ?, ?)", (frm, to, kind))
        tail = None
        if batch.tail and tail_seq is not None:
            tail = json.dumps(
                {
                    "offset": batch.tail.offset,
                    "line": batch.tail.line,
                    "session": batch.tail.session,
                    "seq": tail_seq,
                }
            )
        self.conn.execute(
            "UPDATE files SET offset = ?, line = ?, inode = ?, size = ?, mtime = ?, carry = ?, tail = ? WHERE id = ?",
            (
                batch.end_offset,
                batch.end_line,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime,
                json.dumps(batch.carry) if batch.carry else None,
                tail,
                file_id,
            ),
        )
        self.bump(counts, "redacted:")
        self.bump(Counter({"dropped_by_deny_content": dropped, "malformed_lines": batch.malformed}))
        return added

    def _sanitize(self, batch: Batch) -> None:
        """Make every transcript-supplied id and timestamp in the batch safe to store."""
        sessions = {}
        for info in batch.sessions.values():
            new = self.safe_id(info.id)
            if new != info.id:
                info.native_id = new.rsplit(":", 1)[-1]
                info.resume_cmd = None  # it would embed the unsafe original id
            info.id = new
            info.parent_id = self.safe_id(info.parent_id)
            sessions[new] = info
        batch.sessions = sessions
        for m in batch.messages:
            m.session = self.safe_id(m.session)
            m.ts = self.safe_ts(m.ts)
        batch.links = [(self.safe_id(a), self.safe_id(b), k) for a, b, k in batch.links]
        if batch.tail:
            batch.tail.session = self.safe_id(batch.tail.session)
        # carry is persisted as-is: string values in it get the same id treatment, so an adapter
        # that keeps its session id there (Codex, Pi) stores the sanitized form.
        batch.carry = {k: self._safe_native(v) if isinstance(v, str) else v for k, v in batch.carry.items()}

    def _upsert_session(self, info: SessionInfo, counts: Counter, file_id: int | None) -> None:
        fields: dict[str, Any] = {k: getattr(info, k, None) for k in _SESSION_FIELDS if k != "file_id"}
        fields["file_id"] = file_id
        self.enrich_session(info.id, title=info.title, title_rank=info.title_rank, _counts=counts, **fields)

    def enrich_session(
        self,
        sid: str,
        *,
        title: str | None = None,
        title_rank: int = -1,
        _counts: Counter | None = None,
        create: bool = True,
        **fields: Any,
    ) -> None:
        """Insert or update a session. None never overwrites; started_at only moves earlier,
        ended_at only later; a title replaces one of equal or lower rank.

        Broker rules apply to every text field: a title, cwd or resume command that matches a
        `deny_content` rule is dropped (not stored at all); the rest are redacted.
        create=False only updates an existing row (side metadata must not create sessions for
        transcripts that were never indexed, e.g. ones that `deny_paths` blocked).
        """
        counts = _counts if _counts is not None else Counter()
        original, sid = sid, self.safe_id(sid)
        if sid != original:  # the id held content: its native part and resume command would too
            fields["native_id"] = sid.rsplit(":", 1)[-1]
            fields["resume_cmd"] = None
        if fields.get("parent_id"):
            fields["parent_id"] = self.safe_id(fields["parent_id"])
        if fields.get("native_id"):
            fields["native_id"] = self._safe_native(str(fields["native_id"]))
        if fields.get("desktop_id"):
            fields["desktop_id"] = self._safe_native(str(fields["desktop_id"]))
        for key in ("started_at", "ended_at"):
            if key in fields:
                fields[key] = self.safe_ts(fields[key])
        unknown = set(fields) - set(_SESSION_FIELDS)
        if unknown:
            raise ValueError(f"unknown session fields: {sorted(unknown)}")
        dropped = 0
        for key in ("cwd", "branch", "resume_cmd"):
            if fields.get(key):
                if self._denied(fields[key]):
                    fields[key] = None
                    dropped += 1
                    if key == "cwd" and fields.get("resume_cmd"):
                        fields["resume_cmd"] = None  # it contains the denied cwd
                else:
                    fields[key] = self._clean(fields[key], counts)
        if title and self._denied(title):
            title, dropped = None, dropped + 1
        title = short(self._clean(title, counts)) if title else None  # deny-checked at full length
        if dropped:
            self.bump(Counter({"dropped_by_deny_content": dropped}))
        harness = fields.get("harness") or batch_harness(sid)
        if not create and not self.conn.execute("SELECT 1 FROM sessions WHERE id = ?", (sid,)).fetchone():
            return
        self.conn.execute("INSERT OR IGNORE INTO sessions(id, harness) VALUES (?, ?)", (sid, harness))
        sets, params = [], []
        for k, v in fields.items():
            if v is None or k == "harness":
                continue
            if k == "started_at":
                sets.append(
                    "started_at = CASE WHEN started_at IS NULL OR ? < started_at THEN ? ELSE started_at END"
                )
                params += [v, v]
            elif k == "ended_at":
                sets.append("ended_at = CASE WHEN ended_at IS NULL OR ? > ended_at THEN ? ELSE ended_at END")
                params += [v, v]
            elif k == "file_id":
                sets.append("file_id = COALESCE(file_id, ?)")
                params.append(v)
            else:
                sets.append(f"{k} = ?")
                params.append(v)
        if title:
            sets.append("title = CASE WHEN ? >= title_rank THEN ? ELSE title END")
            sets.append("title_rank = MAX(title_rank, ?)")
            params += [title_rank, title, title_rank]
        if sets:
            self.conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", [*params, sid])
        if _counts is None:
            self.bump(counts, "redacted:")

    # ------------------------------------------------------------------ bulk load

    def is_empty(self) -> bool:
        return self.conn.execute("SELECT 1 FROM messages LIMIT 1").fetchone() is None

    def begin_bulk(self) -> None:
        """First sync into an empty index: skip per-row FTS updates (rebuilt once at the end).

        Rebuilding the trigram index in one pass is about 3x faster than maintaining it row by
        row. Only safe while the index is empty, which is why sync() checks that first.
        """
        self.conn.execute("DROP TRIGGER IF EXISTS messages_ai")
        self.conn.execute("DROP TRIGGER IF EXISTS messages_ad")

    def end_bulk(self) -> None:
        """Rebuild the FTS index from the messages table and restore the triggers."""
        self.conn.execute("INSERT INTO fts(fts) VALUES ('rebuild')")
        self.conn.executescript(SCHEMA)  # CREATE ... IF NOT EXISTS: brings the triggers back
        self.conn.commit()

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def commit(self) -> None:
        self.conn.commit()


def denied(text: str | None, rules) -> bool:
    """True if a deny rule matches the text or any of its blank-line-separated blocks.

    Adapters join a message's content blocks (and an assistant turn's parts) with blank lines,
    so a rule anchored with `^` must also match a block that isn't first. The source view
    (`query.raw_lines`) uses the same function on every decoded string.
    """
    if not rules or not text:
        return False
    parts = [text, *(p.strip() for p in text.split("\n\n"))] if "\n\n" in text else [text]
    return any(rx.search(p) for rx in rules for p in parts)


def batch_harness(sid: str) -> str:
    """Harness part of a session id: "claude:x" -> "claude", "jsonl:bot:x" -> "jsonl:bot"."""
    head, _, rest = sid.partition(":")
    if head == "jsonl" and ":" in rest:
        return f"jsonl:{rest.split(':', 1)[0]}"
    return head
