"""Any JSONL log, mapped by the user field by field.

Only files matching a configured `[[sources.jsonl]]` glob are read; nothing is guessed. Each
line is one message. Mapping values are dotted paths into the JSON object (`body.text`,
`messages.0.content`). Without a `session` field, the whole file is one session.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any

from ..config import JsonlSource
from .base import Adapter, Batch, Msg, dig, iter_lines, loads

ROLES = {"user", "assistant", "system"}


class JsonlAdapter(Adapter):
    def __init__(self, source: JsonlSource) -> None:
        self.source = source
        self.harness = f"jsonl:{source.name}"

    def discover(self) -> list[Path]:
        out: set[Path] = set()
        for pattern in self.source.paths:
            for match in glob.glob(str(Path(pattern).expanduser()), recursive=True):
                p = Path(match)
                if p.is_file():
                    out.add(p)
        return sorted(out)

    def _role(self, value: Any) -> str:
        role = str(value) if value is not None else "user"
        role = self.source.role_map.get(role, role)
        return role if role in ROLES else "system"

    def parse(self, path: Path, offset: int, line: int, carry: dict[str, Any]) -> Batch:
        b = Batch(carry=dict(carry))
        src = self.source
        for no, pos, raw in iter_lines(path, offset, line):
            if raw == b"":
                b.end_line, b.end_offset = no, pos
                break
            d = loads(raw)
            if d is None:
                b.malformed += 1
                continue
            value = dig(d, src.text)
            if value is None:
                continue
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            if not text.strip():
                continue
            native = dig(d, src.session) if src.session else None
            native = str(native) if native not in (None, "") else path.stem
            sid = f"{self.harness}:{native}"
            ts = dig(d, src.timestamp) if src.timestamp else None
            ts = str(ts) if ts is not None else None
            info = b.session(sid, self.harness, native_id=native)
            info.seen(ts)
            role = self._role(dig(d, src.role) if src.role else None)
            b.messages.append(Msg(sid, role, text, ts, no, no))
        return b
