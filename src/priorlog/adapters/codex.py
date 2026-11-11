"""Codex CLI rollout files: `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl`.

Current format: each line is an envelope `{"timestamp", "type", "payload"}`. The first is
`session_meta` (payload has `id`, `cwd`, `timestamp`). Conversation lives in `response_item`
lines whose payload `type` is `message` (roles user / assistant / developer), or a tool call
(`function_call`, `custom_tool_call`, `local_shell_call`, `web_search_call`). `event_msg` lines
repeat the same conversation for the TUI and are ignored, as are reasoning items.

Older rollouts have no envelope: the payload is the line itself. Both are accepted.

Codex puts injected context (environment, AGENTS.md, notifications) into `user` messages as
whole-message XML-ish blocks; those are dropped, the person's own words are kept.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import Adapter, Batch, Msg, TurnBuilder, is_injected, iter_lines, loads

TOOL_TYPES = {"function_call", "custom_tool_call", "local_shell_call", "web_search_call", "tool_call"}
IGNORED = {"function_call_output", "custom_tool_call_output", "reasoning", "tool_result", "additional_tools"}
_UUID = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)


def _texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    out = []
    for blk in content or ():
        if isinstance(blk, dict) and isinstance(blk.get("text"), str) and blk["text"].strip():
            out.append(blk["text"])
    return out


class CodexAdapter(Adapter):
    harness = "codex"

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
        m = _UUID.search(path.stem)
        native = b.carry.get("native") or (m.group(1) if m else path.stem)
        sid = f"codex:{native}"
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
            env_type = d.get("type")
            payload = d.get("payload") if isinstance(d.get("payload"), dict) else d
            ts = d.get("timestamp") or payload.get("timestamp")
            if env_type == "session_meta" or (no == 1 and "instructions" in d and "id" in d):
                new_native = payload.get("id") or payload.get("session_id")
                if isinstance(new_native, str) and no == 1 and new_native != native and not b.messages:
                    # The file name had no id, or a different one: trust the session record.
                    b.sessions.pop(sid, None)
                    native, sid = new_native, f"codex:{new_native}"
                    info = b.session(sid, self.harness, native_id=native)
                    turn.session = sid
                if isinstance(payload.get("cwd"), str):
                    info.cwd = payload["cwd"]
                git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
                if isinstance(git.get("branch"), str):
                    info.branch = git["branch"]
                info.seen(payload.get("timestamp") if isinstance(payload.get("timestamp"), str) else None)
                b.carry["native"] = native  # ids only: carry is stored as-is, so no raw text in it
                continue
            if env_type == "turn_context" and isinstance(payload.get("cwd"), str) and not info.cwd:
                info.cwd = payload["cwd"]
                continue
            if env_type not in (None, "response_item", "message", *TOOL_TYPES):
                continue  # event_msg, token counts, world_state, ...
            ptype = payload.get("type")
            if ptype == "message":
                role = payload.get("role")
                if role == "assistant":
                    info.seen(ts)
                    for text in _texts(payload.get("content")):
                        turn.add("text", text, ts, no, pos)
                elif role == "user":
                    texts = [t for t in _texts(payload.get("content")) if not is_injected(t)]
                    if texts:
                        info.seen(ts)
                        turn.flush()
                        text = "\n\n".join(texts).strip()
                        b.messages.append(Msg(sid, "user", text, ts, no, no))
                # developer / system messages are harness instructions: not indexed
            elif ptype in TOOL_TYPES:
                name = payload.get("name") or ptype.removesuffix("_call")
                turn.add("tool", str(name), ts, no, pos)
            elif ptype not in IGNORED and ptype is not None:
                b.unknown_types.add(str(ptype))
        turn.finish()
        if info.cwd:
            info.resume_cmd = f"codex resume {native}"
        return b
