"""Claude Code transcripts, plus the Claude desktop app's session files.

Layout (CLI and desktop app share it):
  <root>/<project-dir>/<uuid>.jsonl                        one session; file stem = session uuid
  <root>/<project-dir>/<uuid>/subagents/agent-<id>.jsonl   a subagent of that session
  <root>/<project-dir>/<uuid>/subagents/agent-<id>.meta.json  {"description": ...}

Every line is a JSON object with a top-level `type`. Only `user` and `assistant` lines carry
conversation text; `custom-title`, `ai-title` and `summary` give titles. Everything else
(attachments, hook output, snapshots, ...) is ignored and, if unfamiliar, counted.

A resumed or forked session starts with a copy of its parent's lines, still carrying the
parent's `sessionId`. Lines naming another session we also have a file for are skipped and
recorded as a `fork` link, so each message is stored once.

Desktop app: `<desktop_root>/*/*/local_*.json` maps a desktop id (`local_...`) to the CLI
session (`cliSessionId`) with its title and cwd. Only those local fields are used; cloud and
Remote Control fields in the same file are deliberately ignored (local sources only).
"""

from __future__ import annotations

import contextlib
import json
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import (
    RANK_DESKTOP,
    RANK_GENERATED,
    RANK_USER,
    Adapter,
    Batch,
    Msg,
    TurnBuilder,
    iter_lines,
    loads,
)

IGNORED_TYPES = {
    "attachment",
    "last-prompt",
    "api-request",
    "api-request-blob",
    "api-request-shape",
    "queue-operation",
    "mode",
    "agent-name",
    "system",
    "file-history-snapshot",
    "file-history-delta",
    "cost-state",
    "frame-link",
    "permission-mode",
    "relocated",
    "tools-used",
    "session-owner",
    "progress",
    "pr-link",
    "bridge-session",
    "atis-latch",
    "artifact-comment-monitor",
    "artifact-autoreact-ledger",
}

# Context the IDE integrations prepend to a prompt (open file, selection): not the user's words.
_IDE_CONTEXT = re.compile(r"<(ide_[a-z_]+)>.*?(?:</\1>|\Z)", re.DOTALL)
_REMINDER = re.compile(r"<system-reminder>.*?(?:</system-reminder>|\Z)", re.DOTALL)
_COMMAND = re.compile(r"<command-name>\s*/?(.*?)\s*</command-name>", re.DOTALL)
# Searched separately: the args tag usually sits on its own line after the name tag.
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
_DROP_PREFIXES = (
    "<task-notification>",
    "[SYSTEM NOTIFICATION",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<local-command-caveat>",
    "<bash-stdout>",
    "<bash-stderr>",
    "[Request interrupted by user",
)
_RELAY_PREFIXES = ("<relay from=", "Another Claude session sent a message", "The coordinator sent a message")
_WAKE_MSG = re.compile(r"<message\b[^>]*\bfrom=\"human\"[^>]*>(.*?)</message>", re.DOTALL)
# Tools whose input is a message to a person or another session: keep what was said.
MESSAGE_TOOLS = {"reply", "post_message", "send_message", "SendMessage", "SubagentHandback"}
_GENERIC_DESKTOP_TITLES = ("Remote Control session", "New session")


def _blocks_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n\n".join(t for t in texts if t) or None


def user_message(d: dict) -> tuple[str, str] | None:
    """(role, text) for a user line worth indexing; None for tool results and injected lines.

    Kept: what the person typed (slash commands as `/name args`), human messages arriving
    through wake-ups, and, as role `system`, messages relayed from other sessions (peer or
    coordinator notes), which are useful context but not the user speaking.
    """
    if "toolUseResult" in d:
        return None
    text = _blocks_text((d.get("message") or {}).get("content"))
    if not text:
        return None
    origin = d.get("origin")
    kind = origin.get("kind") if isinstance(origin, dict) else None
    stripped = text.lstrip()
    if kind == "task-notification" or stripped.startswith(_DROP_PREFIXES[:2]):
        return None
    if kind in ("peer", "coordinator") or stripped.startswith(_RELAY_PREFIXES):
        return "system", _REMINDER.sub("", stripped).strip()
    if d.get("isMeta") or d.get("isCompactSummary"):
        return None
    text = _IDE_CONTEXT.sub("", _REMINDER.sub("", text)).strip()
    if not text or text.startswith(_DROP_PREFIXES):
        return None
    if text.startswith(("<command-name>", "<command-message>")):
        m = _COMMAND.search(text)
        if not m:
            return None
        a = _COMMAND_ARGS.search(text)
        return "user", f"/{m.group(1)} {(a.group(1) if a else '').strip()}".strip()
    if text.startswith("<bash-input>"):
        return "user", "! " + re.sub(r"</?bash-input>", "", text).strip()
    if text.startswith("<wake "):
        bodies = [b.strip() for b in _WAKE_MSG.findall(text) if b.strip()]
        return ("user", "\n\n".join(bodies)) if bodies else ("system", text)
    return "user", text


def assistant_parts(d: dict) -> list[tuple[str, str]] | None:
    msg = d.get("message") or {}
    if msg.get("model") == "<synthetic>" or d.get("isApiErrorMessage"):
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return [("text", content)]
    parts: list[tuple[str, str]] = []
    for b in content or ():
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and (b.get("text") or "").strip():
            parts.append(("text", b["text"]))
        elif b.get("type") in ("tool_use", "server_tool_use"):
            name = b.get("name") or "?"
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            said = inp.get("text") or inp.get("message")
            if name.rsplit("__", 1)[-1] in MESSAGE_TOOLS and isinstance(said, str) and said.strip():
                parts.append(("text", f"[{name.rsplit('__', 1)[-1]}] {said.strip()}"))
            else:
                parts.append(("tool", name))
    return parts


def _iso_ms(ms: Any) -> str | None:
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class ClaudeAdapter(Adapter):
    harness = "claude"

    def __init__(self, roots: tuple[Path, ...], desktop_roots: tuple[Path, ...] = ()) -> None:
        self.roots = roots
        self.desktop_roots = desktop_roots
        self.known: set[str] = set()

    def discover(self) -> list[Path]:
        out: list[Path] = []
        for root in self.roots:
            root = root.expanduser()
            if root.is_dir():
                out += sorted(root.glob("*/*.jsonl"))
                out += sorted(root.glob("*/*/subagents/agent-*.jsonl"))
        return out

    def allowed(self, path: Path) -> bool:
        """A subagent transcript is denied whenever its parent session's transcript is."""
        if not super().allowed(path):
            return False
        if path.parent.name == "subagents":
            session_dir = path.parent.parent
            return super().allowed(session_dir.parent / f"{session_dir.name}.jsonl")
        return True

    def prepare(self, paths: list[Path]) -> None:
        self.known = {p.stem for p in paths if p.parent.name != "subagents"}

    def parse(self, path: Path, offset: int, line: int, carry: dict[str, Any]) -> Batch:
        b = Batch(carry=dict(carry))
        subagent = path.stem.removeprefix("agent-") if path.parent.name == "subagents" else None
        owner = path.parent.parent.name if subagent else path.stem
        sid = f"claude:agent-{subagent}" if subagent else f"claude:{owner}"
        info = b.session(sid, self.harness, native_id=subagent or owner)
        if subagent:
            info.parent_id = f"claude:{owner}"
            b.links.append((info.parent_id, sid, "subagent"))
            meta = path.with_name(path.name[: -len(".jsonl")] + ".meta.json")
            if offset == 0 and meta.exists() and (self.policy is None or self.policy.allowed(meta)):
                with contextlib.suppress(OSError, ValueError, AttributeError):
                    info.set_title(json.loads(meta.read_text()).get("description"), RANK_USER)
        turn = TurnBuilder(b, sid)
        fork_parent = None
        seen_own = False
        for no, pos, raw in iter_lines(path, offset, line):
            if raw == b"":
                b.end_line, b.end_offset = no, pos
                break
            d = loads(raw)
            if d is None or "type" not in d:
                b.malformed += 1
                continue
            t = d["type"]
            line_sid = d.get("sessionId")
            if line_sid and line_sid != owner and line_sid in self.known:
                if not subagent:
                    fork_parent = fork_parent or line_sid
                continue
            if t in ("user", "assistant"):
                seen_own = True
                ts = d.get("timestamp")
                info.seen(ts)
                if not info.cwd and d.get("cwd"):
                    info.cwd = d["cwd"]
                if d.get("gitBranch") and d["gitBranch"] != "HEAD":
                    info.branch = d["gitBranch"]
                if t == "assistant":
                    parts = assistant_parts(d)
                    for kind, value in parts or ():
                        turn.add(kind, value, ts, no, pos)
                    continue
                um = user_message(d)
                if um is None:
                    continue  # tool results don't break an assistant turn
                turn.flush()
                role, text = um
                b.messages.append(Msg(sid, role, text, ts, no, no))
            elif t == "custom-title":
                title = (d.get("customTitle") or "").strip()
                if title and title != "New session":
                    info.set_title(title, RANK_USER)
            elif t == "summary":
                info.set_title(d.get("summary"), RANK_USER)
            elif t == "ai-title":
                info.set_title(d.get("aiTitle"), RANK_GENERATED)
            elif t not in IGNORED_TYPES:
                b.unknown_types.add(str(t))
        turn.finish()
        if fork_parent:
            b.links.append((f"claude:{fork_parent}", sid, "fork"))
        if not subagent and info.cwd:
            info.resume_cmd = f"cd {shlex.quote(info.cwd)} && claude --resume {owner}"
        if not seen_own and not subagent and offset == 0:
            # Only copied history so far: don't create an empty session row for it.
            b.sessions.pop(sid, None)
            b.links = [link for link in b.links if link[1] != sid]
        return b

    def post_sync(self, store: Any, policy: Any) -> None:
        """Join desktop `local_*.json` files onto their CLI sessions (title, desktop id)."""
        for root in self.desktop_roots:
            root = root.expanduser()
            if not root.is_dir():
                continue
            for f in sorted(root.glob("*/*/local_*.json")):
                if not policy.allowed(f):
                    continue
                try:
                    d = json.loads(f.read_text())
                except (OSError, ValueError):
                    continue
                if not isinstance(d, dict):
                    continue
                cli, local_id = d.get("cliSessionId"), d.get("sessionId")
                if not isinstance(cli, str) or not isinstance(local_id, str):
                    continue
                title = (d.get("title") or "").strip() if isinstance(d.get("title"), str) else ""
                if title.startswith(_GENERIC_DESKTOP_TITLES):
                    title = ""
                cwd = d.get("cwd") if isinstance(d.get("cwd"), str) else None
                store.enrich_session(
                    f"claude:{cli}",
                    create=False,  # never create a session whose transcript wasn't indexed
                    harness=self.harness,
                    native_id=cli,
                    desktop_id=local_id,
                    title=title or None,
                    title_rank=RANK_DESKTOP,
                    cwd=cwd,
                    started_at=_iso_ms(d.get("createdAt")),
                    resume_cmd=f"cd {shlex.quote(cwd)} && claude --resume {cli}" if cwd else None,
                )
