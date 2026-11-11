"""Path policy: which files the broker may open, decided before a single byte is read.

A path is readable only if (1) it resolves inside a configured source root, or matches a
configured JSONL glob, and (2) no deny glob matches it. Symlinks are resolved first, so a link
inside a root that points at ~/.ssh is still denied.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from .config import Config


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


class Policy:
    def __init__(self, config: Config) -> None:
        self.roots = config.roots
        self.globs = config.jsonl_globs
        self.deny = tuple(p.casefold() for p in config.deny_paths)
        self._dirs: dict[str, str | None] = {}  # directory -> deny rule that matched it, or None

    def check(self, path: Path | str) -> Decision:
        try:
            real = Path(path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            return Decision(False, f"cannot resolve path: {type(exc).__name__}")
        text = str(real)
        inside = any(real == r or r in real.parents for r in self.roots) or any(
            fnmatch.fnmatchcase(text, str(Path(g).resolve(strict=False))) or fnmatch.fnmatchcase(text, g)
            for g in self.globs
        )
        if not inside:
            return Decision(False, "outside configured source roots")
        # A rule that matches a directory denies everything below it, so test every ancestor.
        # Sibling files share ancestors, so each directory's verdict is computed once.
        rule = self._denied_by(text.casefold()) or next(
            (r for r in map(self._dir_rule, real.parents) if r), None
        )
        if rule:
            return Decision(False, f"matches deny rule {rule!r}")
        return Decision(True, "allowed")

    def _denied_by(self, folded: str) -> str | None:
        return next((p for p in self.deny if fnmatch.fnmatchcase(folded, p)), None)

    def _dir_rule(self, directory: Path) -> str | None:
        key = str(directory).casefold()
        if key not in self._dirs:
            self._dirs[key] = self._denied_by(key)
        return self._dirs[key]

    def allowed(self, path: Path | str) -> bool:
        return self.check(path).allowed
