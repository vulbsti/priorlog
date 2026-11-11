"""Read side: search, read, list and status over the index. Returns plain dicts.

Every hit carries a citation:
  cite       "<session id>#<seq>"            what `read` takes to open the message
  session    "claude:6f1c..."                 harness-prefixed session id
  harness    "claude" | "codex" | "pi" | "jsonl:<name>"
  timestamp  ISO time of the message (or null if the source has none)
  locator    "<transcript path>:L<first>-L<last>"  the exact source lines
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from .config import Config
from .policy import Policy
from .redact import Redactor
from .store import Store, denied

SNIPPET_BEFORE, SNIPPET_AFTER = 90, 160
HITS_PER_SESSION = 2
PAGE_CHARS = 24_000
RAW_LINE_CHARS = 2_000
RAW_MAX_LINES = 12  # a long assistant turn can span many raw lines; show the first ones


class QueryError(ValueError):
    pass


def _home(path: str | None) -> str:
    if not path:
        return ""
    home = str(Path.home())
    return "~" + path[len(home) :] if path == home or path.startswith(home + os.sep) else path


def locator(path: str | None, start: int, end: int) -> str:
    lines = f"L{start}" if start == end else f"L{start}-L{end}"
    return f"{_home(path)}:{lines}"


def _like(s: str) -> str:
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def parse_query(query: str) -> list[str]:
    """Split into terms; "double quoted phrases" stay together."""
    terms = [a or b for a, b in re.findall(r'"([^"]+)"|(\S+)', query)]
    return list(dict.fromkeys(t for t in terms if t.strip()))


def snippet(text: str, terms: list[str]) -> str:
    marked = [t for t in terms if len(t) > 1] or terms
    pattern = re.compile("|".join(re.escape(t) for t in sorted(marked, key=len, reverse=True)), re.I)
    m = pattern.search(text)
    start = max(0, m.start() - SNIPPET_BEFORE) if m else 0
    end = min(len(text), (m.end() if m else 0) + SNIPPET_AFTER)
    if start > 0 and (sp := text.rfind(" ", 0, start)) != -1 and start - sp < 20:
        start = sp + 1
    if end < len(text) and (sp := text.find(" ", end)) != -1 and sp - end < 20:
        end = sp
    body = re.sub(r"\s+", " ", text[start:end]).strip()
    body = pattern.sub(lambda x: f"«{x.group(0)}»", body).replace("» «", " ")
    return ("…" if start > 0 else "") + body + ("…" if end < len(text) else "")


def _filters(
    harness: str | None, project: str | None, role: str | None, after: str | None, before: str | None
) -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    if harness:
        where.append("(s.harness = ? OR s.harness LIKE ?)")
        params += [harness, harness + ":%"]
    if project:
        where.append("(s.cwd LIKE ? ESCAPE '\\' OR s.title LIKE ? ESCAPE '\\')")
        params += [_like(project), _like(project)]
    if role:
        where.append("m.role = ?")
        params.append(role)
    if after:
        where.append("COALESCE(m.ts, s.started_at) >= ?")
        params.append(after)
    if before:
        where.append("COALESCE(m.ts, s.started_at) < ?")
        params.append(before)
    return where, params


def search(
    store: Store,
    query: str,
    *,
    harness: str | None = None,
    project: str | None = None,
    role: str | None = None,
    after: str | None = None,
    before: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    terms = parse_query(query)
    if not terms:
        raise QueryError("give search at least one word")
    limit = max(1, min(int(limit or 10), 100))
    where, params = _filters(harness, project, role, after, before)
    long_terms = [t for t in terms if len(t) >= 3]
    for t in (t for t in terms if len(t) < 3):  # trigrams can't match terms under 3 characters
        where.append("m.text LIKE ? ESCAPE '\\'")
        params.append(_like(t))
    if long_terms:
        match = " AND ".join('"' + t.replace('"', '""') + '"' for t in long_terms)
        # MATERIALIZED: run the FTS match and bm25 exactly once per query.
        head_cte = "h AS MATERIALIZED (SELECT rowid AS r, bm25(fts) AS score FROM fts WHERE fts MATCH ?), "
        source = "h JOIN messages m ON m.id = h.r"
        score = "h.score"
        head: list[Any] = [match]
    else:  # only short words: a LIKE scan, unranked
        head_cte, source, score, head = "", "messages m", "0.0", []
    where_sql = " AND ".join(where) or "1"
    # One statement does everything inside SQLite: bm25 (lower = better) with system notes
    # weighted down and newer messages first on ties, at most HITS_PER_SESSION per session,
    # the limit, and the totals (window functions over all matches). Only the returned rows
    # and their text reach Python.
    sql = (
        f"WITH {head_cte}"
        "r AS (SELECT m.id AS mid, m.session_id AS sid, COALESCE(m.ts, '') AS t, "
        f"{score} * CASE m.role WHEN 'system' THEN 0.7 ELSE 1.0 END AS adj "
        f"FROM {source} JOIN sessions s ON s.id = m.session_id WHERE {where_sql}), "
        "p AS (SELECT mid, adj, t, ROW_NUMBER() OVER (PARTITION BY sid ORDER BY adj, t DESC) AS rn FROM r), "
        "q AS (SELECT mid, adj, t, rn, COUNT(*) OVER () AS total, SUM(rn = 1) OVER () AS nsess FROM p) "
        "SELECT m.*, q.adj AS score, q.total, q.nsess, s.harness, s.title, s.cwd, f.path FROM q "
        "JOIN messages m ON m.id = q.mid JOIN sessions s ON s.id = m.session_id "
        "JOIN files f ON f.id = m.file_id "
        "WHERE q.rn <= ? ORDER BY q.adj, q.t DESC LIMIT ?"
    )
    try:
        rows = store.conn.execute(sql, head + params + [HITS_PER_SESSION, limit]).fetchall()
    except sqlite3.OperationalError as exc:
        raise QueryError(f"search failed: {exc}") from exc
    return {
        "query": query,
        "total_matches": rows[0]["total"] if rows else 0,
        "sessions_matched": rows[0]["nsess"] if rows else 0,
        "hits": [_hit(r, terms) for r in rows],
    }


def _hit(r: sqlite3.Row, terms: list[str]) -> dict[str, Any]:
    return {
        "cite": f"{r['session_id']}#{r['seq']}",
        "session": r["session_id"],
        "harness": r["harness"],
        "timestamp": r["ts"],
        "locator": locator(r["path"], r["line_start"], r["line_end"]),
        "role": r["role"],
        "title": r["title"],
        "cwd": _home(r["cwd"]),
        "snippet": snippet(r["text"], terms),
        "score": round(-r["score"], 3) if r["score"] else 0.0,
    }


def resolve(store: Store, ref: str) -> tuple[sqlite3.Row, int | None]:
    """Find a session from a cite ("id#seq"), full id, native id (or prefix), or desktop id."""
    ref = ref.strip()
    seq = None
    if "#" in ref:
        ref, _, s = ref.rpartition("#")
        if not s.isdigit():
            raise QueryError(f"bad citation {ref}#{s}: expected <session>#<number>")
        seq = int(s)
    conn = store.conn
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (ref,)).fetchone()
    if row is None:
        rows = (
            conn.execute(
                "SELECT * FROM sessions WHERE native_id = ? OR desktop_id = ? OR native_id LIKE ? ESCAPE '\\' LIMIT 6",
                (ref, ref, ref.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"),
            ).fetchall()
            if len(ref) >= 6
            else []
        )
        if len(rows) > 1:
            raise QueryError(f"{ref!r} matches several sessions: " + ", ".join(r["id"] for r in rows))
        if not rows:
            raise QueryError(f"no session {ref!r}; use search or sessions to find one")
        row = rows[0]
    return row, seq


def _session_meta(store: Store, s: sqlite3.Row) -> dict[str, Any]:
    n = store.conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (s["id"],)).fetchone()[0]
    path = (
        store.conn.execute("SELECT path FROM files WHERE id = ?", (s["file_id"],)).fetchone()
        if s["file_id"]
        else None
    )
    links = store.conn.execute(
        "SELECT kind, to_id AS other, 'to' AS dir FROM links WHERE from_id = ? "
        "UNION SELECT kind, from_id, 'from' FROM links WHERE to_id = ? ORDER BY 1, 2",
        (s["id"], s["id"]),
    ).fetchall()
    return {
        "session": s["id"],
        "harness": s["harness"],
        "title": s["title"],
        "cwd": _home(s["cwd"]),
        "branch": s["branch"],
        "started_at": s["started_at"],
        "ended_at": s["ended_at"],
        "messages": n,
        "source": _home(path[0]) if path else None,
        "resume": s["resume_cmd"],
        "desktop_id": s["desktop_id"],
        "links": [{"kind": r["kind"], "direction": r["dir"], "session": r["other"]} for r in links],
    }


def read(
    store: Store,
    ref: str,
    *,
    page: int = 1,
    context: int = 4,
    source: bool = False,
    config: Config | None = None,
) -> dict[str, Any]:
    s, seq = resolve(store, ref)
    meta = _session_meta(store, s)
    rows_sql = (
        "SELECT m.*, f.path FROM messages m JOIN files f ON f.id = m.file_id "
        "WHERE m.session_id = ? {extra} ORDER BY m.seq"
    )
    if seq is not None:
        rows = store.conn.execute(
            rows_sql.format(extra="AND m.seq BETWEEN ? AND ?"), (s["id"], seq - context, seq + context)
        ).fetchall()
        if not any(r["seq"] == seq for r in rows):
            raise QueryError(
                f"{s['id']} has no message #{seq} (it has {meta['messages']} messages, #0-#{meta['messages'] - 1})"
            )
        out = {**meta, "cited": seq, "messages_shown": [_msg(r, cited=r["seq"] == seq) for r in rows]}
        if source:
            cited = next(r for r in rows if r["seq"] == seq)
            out["source_lines"] = raw_lines(
                config or store.config, cited["path"], cited["line_start"], cited["line_end"]
            )
        return out
    rows = store.conn.execute(rows_sql.format(extra=""), (s["id"],)).fetchall()
    pages: list[list[sqlite3.Row]] = [[]]
    size = 0
    for r in rows:
        if size > PAGE_CHARS and pages[-1]:
            pages.append([])
            size = 0
        pages[-1].append(r)
        size += len(r["text"]) + 60
    page = int(page or 1)
    if not 1 <= page <= len(pages):
        raise QueryError(f"{s['id']} has {len(pages)} page(s); page {page} does not exist")
    return {**meta, "page": page, "pages": len(pages), "messages_shown": [_msg(r) for r in pages[page - 1]]}


def _msg(r: sqlite3.Row, cited: bool = False) -> dict[str, Any]:
    return {
        "cite": f"{r['session_id']}#{r['seq']}",
        "role": r["role"],
        "timestamp": r["ts"],
        "locator": locator(r["path"], r["line_start"], r["line_end"]),
        "text": r["text"],
        "cited": cited,
    }


def _strings(value: Any, depth: int = 0) -> list[str]:
    """Every string inside a decoded JSON value (keys included), depth-limited."""
    if depth > 64:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*_strings(k, depth + 1), *_strings(v, depth + 1))]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v, depth + 1)]
    return []


def _line_denied(text: str, cfg: Config) -> bool:
    """A raw line is withheld if the line, or any string value inside it, matches a deny rule.

    Rules are written against message text (e.g. `^PRIVATE:`), so they must also be tried on
    the decoded values: in the raw JSON the text sits mid-line and is escaped.
    """
    if not cfg.deny_content:
        return False
    candidates = [text]
    with contextlib.suppress(ValueError, RecursionError):
        candidates += _strings(json.loads(text))
    return any(denied(c, cfg.deny_content) for c in candidates)


def _redact_value(value: Any, redactor: Redactor, depth: int = 0) -> Any:
    if depth > 64:
        return "[REDACTED:too_deep]"
    if isinstance(value, str):
        return redactor(value)
    if isinstance(value, dict):
        return {redactor(k): _redact_value(v, redactor, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v, redactor, depth + 1) for v in value]
    return value


def _redact_line(text: str, redactor: Redactor) -> str:
    """Redact a raw transcript line. JSON lines are redacted value by value on the decoded
    strings (escapes like \\u0040 can't hide a secret) and re-serialised; the result is then
    redacted once more as plain text."""
    try:
        decoded = json.loads(text)
    except (ValueError, RecursionError):
        return redactor(text)
    return redactor(json.dumps(_redact_value(decoded, redactor), ensure_ascii=False))


def raw_lines(cfg: Config, path: str, start: int, end: int) -> list[dict[str, Any]]:
    """The cited lines straight from the transcript file, re-checked by policy and redacted."""
    decision = Policy(cfg).check(path)
    if not decision.allowed:
        raise QueryError(f"source file is not readable under the current policy ({decision.reason})")
    redactor = Redactor(cfg)
    out = []
    try:
        with open(path, "rb") as fh:
            for no, raw in enumerate(fh, 1):
                if no < start:
                    continue
                if no > end:
                    break
                if len(out) == RAW_MAX_LINES:
                    out.append({"line": 0, "text": f"… {end - no + 1} more line(s) up to L{end} not shown"})
                    break
                text = raw.decode("utf-8", errors="replace").rstrip("\n")
                if _line_denied(text, cfg):
                    text = "[line withheld: matches a deny_content rule]"
                text = _redact_line(text, redactor)
                if len(text) > RAW_LINE_CHARS:
                    text = text[:RAW_LINE_CHARS] + f"… [{len(text) - RAW_LINE_CHARS} more chars]"
                out.append({"line": no, "text": text})
    except FileNotFoundError as exc:
        raise QueryError(f"source file no longer exists: {_home(path)}") from exc
    return out


def sessions(
    store: Store,
    *,
    harness: str | None = None,
    project: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    where, params = _filters(harness, project, None, None, None)
    if since:
        where.append("COALESCE(s.ended_at, s.started_at) >= ?")
        params.append(since)
    rows = store.conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS n FROM sessions s "
        f"WHERE {' AND '.join(where) or '1'} AND EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id) "
        "ORDER BY COALESCE(s.ended_at, s.started_at) DESC LIMIT ?",
        [*params, max(1, min(int(limit or 20), 500))],
    ).fetchall()
    return [
        {
            "session": r["id"],
            "harness": r["harness"],
            "title": r["title"],
            "cwd": _home(r["cwd"]),
            "started_at": r["started_at"],
            "ended_at": r["ended_at"],
            "messages": r["n"],
            "resume": r["resume_cmd"],
        }
        for r in rows
    ]


def status(store: Store) -> dict[str, Any]:
    c = store.conn
    per = {
        r[0]: {"sessions": r[1], "messages": r[2]}
        for r in c.execute(
            "SELECT s.harness, COUNT(DISTINCT s.id), COUNT(m.id) FROM sessions s "
            "LEFT JOIN messages m ON m.session_id = s.id GROUP BY s.harness ORDER BY s.harness"
        )
    }
    stats = {r[0]: r[1] for r in c.execute("SELECT key, value FROM stats ORDER BY key")}
    return {
        "db": _home(str(store.path)),
        "db_bytes": store.path.stat().st_size if store.path.exists() else 0,
        "last_sync": store.get_meta("last_sync"),
        "files": c.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        "harnesses": per,
        "redactions": {k.removeprefix("redacted:"): v for k, v in stats.items() if k.startswith("redacted:")},
        "dropped_by_deny_content": stats.get("dropped_by_deny_content", 0),
        "malformed_lines": stats.get("malformed_lines", 0),
        "unknown_types": json.loads(store.get_meta("unknown_types", "{}") or "{}"),
    }


def total_messages(store: Store) -> int:
    return store.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


__all__ = ["QueryError", "read", "resolve", "search", "sessions", "status"]
