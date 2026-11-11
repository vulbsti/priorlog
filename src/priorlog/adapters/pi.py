"""Pi coding agent sessions: `~/.pi/agent/sessions/--<cwd>--/<timestamp>_<uuid>.jsonl`.

The first line is `{"type": "session", "id", "cwd", "timestamp"}`. Conversation lines are
`{"type": "message", "timestamp", "message": {"role", "content"}}` with roles `user`,
`assistant` and `toolResult`. Assistant content is a list of `text`, `thinking` and `toolCall`
blocks; thinking and tool results are not indexed, tool calls become `[tool: name]` markers.
Model and thinking-level changes are ignored.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .base import Adapter, Batch, Msg, TurnBuilder, iter_lines, loads

IGNORED = {"model_change", "thinking_level_change", "compaction", "branch_summary", "label", "custom"}


def _user_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n\n".join(
        b["text"]
        for b in content or ()
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    )


class PiAdapter(Adapter):
    harness = "pi"

    def __init__(self, roots: tuple[Path, ...]) -> None:
        self.roots = roots

    def discover(self) -> list[Path]:
        out: list[Path] = []
        for root in self.roots:
            root = root.expanduser()
            if root.is_dir():
                out += sorted(root.rglob("*.jsonl"))
        return out

    def parse(self, path: Path, offset: int, line: int, carry: dict[str, Any]) -> Batch:
        b = Batch(carry=dict(carry))
        native = b.carry.get("native") or path.stem.rsplit("_", 1)[-1]
        sid = f"pi:{native}"
        info = b.session(sid, self.harness, native_id=native)
        turn = TurnBuilder(b, sid)
        for no, pos, raw in iter_lines(path, offset, line):
            if raw == b"":
                b.end_line, b.end_offset = no, pos
                break
            d = loads(raw)
            if d is None:
                b.malformed += 1
                continue
            t = d.get("type")
            if t == "session":
                if isinstance(d.get("id"), str) and d["id"] != native and not b.messages:
                    b.sessions.pop(sid, None)
                    native, sid = d["id"], f"pi:{d['id']}"
                    info = b.session(sid, self.harness, native_id=native)
                    turn.session = sid
                if isinstance(d.get("cwd"), str):
                    info.cwd = d["cwd"]
                info.seen(d.get("timestamp") if isinstance(d.get("timestamp"), str) else None)
                b.carry["native"] = native
                continue
            if t != "message":
                if t not in IGNORED:
                    b.unknown_types.add(str(t))
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            role, ts = msg.get("role"), d.get("timestamp")
            if role == "user":
                text = _user_text(msg.get("content")).strip()
                if text:
                    info.seen(ts)
                    turn.flush()
                    b.messages.append(Msg(sid, "user", text, ts, no, no))
            elif role == "assistant":
                info.seen(ts)
                content = msg.get("content")
                if isinstance(content, str):
                    turn.add("text", content, ts, no, pos)
                for blk in content if isinstance(content, list) else ():
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") == "text" and isinstance(blk.get("text"), str) and blk["text"].strip():
                        turn.add("text", blk["text"], ts, no, pos)
                    elif blk.get("type") == "toolCall":
                        turn.add("tool", str(blk.get("name") or "?"), ts, no, pos)
            # toolResult / bashExecution: outputs are not indexed
        turn.finish()
        if info.cwd:
            info.resume_cmd = f"cd {shlex.quote(info.cwd)} && pi --session {shlex.quote(str(path))}"
        return b
