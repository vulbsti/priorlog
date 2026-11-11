"""What every adapter returns, and the helpers they share.

An adapter turns one transcript file into messages. It is called with the byte offset and line
number where the previous sync stopped, plus a small `carry` dict it returned last time, and
reads only complete lines from there. That makes every sync incremental: an unchanged file
costs one `stat`, and a file that grew costs only its new lines.

An assistant turn can still be growing when we read it (more text or tool calls arrive on later
lines). Adapters therefore report the last assistant turn as an open `tail`; the store keeps it
but re-reads it from its first line on the next sync and replaces it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_LINE_BYTES = 32 * 1024 * 1024  # a line bigger than this is skipped, never parsed
TITLE_LEN = 80

# Title ranks, weakest first. A new title replaces the stored one when its rank is equal or
# higher, so a later rename of the same kind wins. RANK_FIRST_MESSAGE is set only by the Store,
# from the first user message it actually accepted (never from a message deny_content dropped).
RANK_FIRST_MESSAGE, RANK_GENERATED, RANK_USER, RANK_DESKTOP = 0, 1, 2, 3


@dataclass
class Msg:
    session: str
    role: str  # user | assistant | system
    text: str
    ts: str | None
    line_start: int
    line_end: int


@dataclass
class SessionInfo:
    """Fields an adapter learned about a session. None means "unknown, keep what is stored"."""

    id: str
    harness: str
    native_id: str | None = None
    title: str | None = None
    title_rank: int = -1
    cwd: str | None = None
    branch: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    parent_id: str | None = None
    resume_cmd: str | None = None

    def set_title(self, text: str | None, rank: int) -> None:
        # Kept at full length: the store checks deny rules on the whole title, then shortens it.
        if text and text.strip() and rank >= self.title_rank:
            self.title, self.title_rank = text.strip(), rank

    def seen(self, ts: str | None) -> None:
        if ts:
            if self.started_at is None or ts < self.started_at:
                self.started_at = ts
            if self.ended_at is None or ts > self.ended_at:
                self.ended_at = ts


@dataclass
class Tail:
    """An open region at the end of the file: re-read from (offset, line) next time."""

    offset: int
    line: int
    session: str
    first_index: int  # index in Batch.messages of the first message in the open region


@dataclass
class Batch:
    messages: list[Msg] = field(default_factory=list)
    sessions: dict[str, SessionInfo] = field(default_factory=dict)
    links: list[tuple[str, str, str]] = field(default_factory=list)
    end_offset: int = 0
    end_line: int = 0
    carry: dict[str, Any] = field(default_factory=dict)
    tail: Tail | None = None
    malformed: int = 0
    unknown_types: set[str] = field(default_factory=set)

    def session(self, sid: str, harness: str, **kw: Any) -> SessionInfo:
        info = self.sessions.get(sid)
        if info is None:
            info = self.sessions[sid] = SessionInfo(sid, harness)
        for k, v in kw.items():
            if v is not None and getattr(info, k) is None:
                setattr(info, k, v)
        return info


class Adapter:
    """Base class. Subclasses set `harness` and implement `discover` and `parse`."""

    harness = "base"
    # Set by the sync engine before discover(). Adapters that open any file other than the one
    # passed to parse() (side metadata) must check it first.
    policy: Any = None

    def discover(self) -> list[Path]:
        raise NotImplementedError

    def allowed(self, path: Path) -> bool:
        """May this discovered file be read? Adapters can tighten (never loosen) the policy."""
        return self.policy is None or self.policy.allowed(path)

    def prepare(self, paths: list[Path]) -> None:
        """Called once per sync with every discovered path, before any parse()."""

    def parse(self, path: Path, offset: int, line: int, carry: dict[str, Any]) -> Batch:
        raise NotImplementedError

    def post_sync(self, store: Any, policy: Any) -> None:
        """Called after all files are parsed (e.g. to join side metadata)."""


def iter_lines(path: Path, offset: int, line: int) -> Iterator[tuple[int, int, bytes | None]]:
    """Yield (line_no, byte_offset, raw) for complete lines from `offset`.

    `raw` is None for lines over MAX_LINE_BYTES. The last item is (lines_consumed, end_offset,
    b"") marking where the next sync should start; a final line without "\\n" is still being
    written and is left for next time.
    """
    with open(path, "rb") as fh:
        fh.seek(offset)
        pos, no = offset, line
        for raw in fh:
            if not raw.endswith(b"\n"):
                break
            no += 1
            yield no, pos, (raw if len(raw) <= MAX_LINE_BYTES else None)
            pos += len(raw)
    yield no, pos, b""


def loads(raw: bytes | None) -> dict | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def short(text: str, n: int = TITLE_LEN) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def dig(value: Any, path: str | None) -> Any:
    """Follow a dotted path ("a.b.0.c") into nested dicts and lists."""
    if not path:
        return None
    cur = value
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


_WRAPPED = re.compile(r"^\s*<([A-Za-z_][\w\-]*)(?:\s[^>]*)?>[\s\S]*</\1>\s*$")


def is_injected(text: str) -> bool:
    """True for harness-injected context blocks (one XML-ish tag wrapping the whole text)."""
    return bool(_WRAPPED.match(text)) or text.lstrip().startswith("# AGENTS.md instructions")


class TurnBuilder:
    """Merge consecutive assistant pieces (text and tool calls) into one message per turn.

    Tool calls become markers such as `[tool: Bash x3]`; tool outputs are not indexed.
    """

    def __init__(self, batch: Batch, session: str) -> None:
        self.batch, self.session = batch, session
        self.parts: list[tuple[str, str]] = []
        self.ts: str | None = None
        self.start = self.end = 0
        self.start_offset = 0

    def add(self, kind: str, value: str, ts: str | None, line_no: int, offset: int) -> None:
        if not self.parts:
            self.ts, self.start, self.start_offset = ts, line_no, offset
        self.parts.append((kind, value))
        self.end = line_no

    def flush(self) -> None:
        if self.parts:
            text = render(self.parts)
            if text.strip():
                self.batch.messages.append(
                    Msg(self.session, "assistant", text, self.ts, self.start, self.end)
                )
            self.parts = []

    def finish(self) -> None:
        """At end of input: keep the last turn, but mark it open so it is re-read next time."""
        if self.parts:
            first = len(self.batch.messages)
            self.batch.tail = Tail(self.start_offset, self.start - 1, self.session, first)
            self.flush()


def render(parts: list[tuple[str, str]]) -> str:
    out: list[str] = []
    tools: list[list] = []

    def flush_tools() -> None:
        if tools:
            out.append(" ".join(f"[tool: {n}{f' x{c}' if c > 1 else ''}]" for n, c in tools))
            tools.clear()

    for kind, value in parts:
        if kind == "tool":
            if tools and tools[-1][0] == value:
                tools[-1][1] += 1
            else:
                tools.append([value, 1])
        else:
            flush_tools()
            out.append(value.strip())
    flush_tools()
    return "\n\n".join(p for p in out if p)
