"""Configuration: where priorlog keeps its data, which transcripts it reads, and its rules.

priorlog only ever writes inside its own two directories:

  config  $PRIORLOG_CONFIG  or  $XDG_CONFIG_HOME/priorlog/config.toml  (~/.config/...)
  data    $PRIORLOG_HOME    or  $XDG_DATA_HOME/priorlog/             (~/.local/share/...)

Everything else (transcript folders, desktop-app session files) is opened read-only.
"""

from __future__ import annotations

import os
import platform
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Paths that are never read, even when they sit under a configured root. Matched with
# fnmatch against the absolute, resolved path, case-insensitively. Credentials used by the
# harnesses themselves (Claude's .credentials.json, Codex's auth.json) are on this list, so a
# misconfigured root can never pull a sign-in token into the index.
DEFAULT_DENY_PATHS = (
    "*/.ssh/*",
    "*/.gnupg/*",
    "*/.aws/*",
    "*/.azure/*",
    "*/.kube/*",
    "*/.docker/*",
    "*/.config/gcloud/*",
    "*/.config/gh/*",
    "*/.env",
    "*/.env.*",
    "*/.netrc",
    "*/.pypirc",
    "*/.npmrc",
    "*/.credentials.json",
    "*/credentials.json",
    "*/auth.json",
    "*/token.json",
    "*/cookies*",
    "*/login data*",
    "*.pem",
    "*.key",
    "*/id_rsa*",
    "*/id_ed25519*",
)


def _env_path(var: str, fallback: Path) -> Path:
    value = os.environ.get(var)
    return Path(value).expanduser() if value else fallback


def config_path() -> Path:
    if os.environ.get("PRIORLOG_CONFIG"):
        return Path(os.environ["PRIORLOG_CONFIG"]).expanduser()
    return _env_path("XDG_CONFIG_HOME", Path.home() / ".config") / "priorlog" / "config.toml"


def data_dir() -> Path:
    if os.environ.get("PRIORLOG_HOME"):
        return Path(os.environ["PRIORLOG_HOME"]).expanduser()
    return _env_path("XDG_DATA_HOME", Path.home() / ".local" / "share") / "priorlog"


def _desktop_default() -> str:
    if platform.system() == "Darwin":
        return "~/Library/Application Support/Claude/claude-code-sessions"
    return "~/.config/Claude/claude-code-sessions"


@dataclass(frozen=True)
class JsonlSource:
    """A user-mapped JSONL format. Field values are dotted paths into each JSON line."""

    name: str
    paths: tuple[str, ...]
    text: str
    role: str | None = None
    session: str | None = None
    timestamp: str | None = None
    role_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CustomPattern:
    name: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Config:
    claude_roots: tuple[Path, ...] = ()
    claude_desktop_roots: tuple[Path, ...] = ()
    codex_roots: tuple[Path, ...] = ()
    pi_roots: tuple[Path, ...] = ()
    jsonl_sources: tuple[JsonlSource, ...] = ()
    deny_paths: tuple[str, ...] = DEFAULT_DENY_PATHS
    deny_content: tuple[re.Pattern[str], ...] = ()
    redact_emails: bool = True
    redact_high_entropy: bool = False
    custom_patterns: tuple[CustomPattern, ...] = ()
    auto_sync_seconds: int = 300
    db_path: Path = field(default_factory=lambda: data_dir() / "index.sqlite3")
    source_file: Path | None = None

    @property
    def roots(self) -> tuple[Path, ...]:
        """Directories priorlog may read from (JSONL sources add their globs; see policy.py)."""
        return tuple(
            p.expanduser().resolve(strict=False)
            for p in (*self.claude_roots, *self.claude_desktop_roots, *self.codex_roots, *self.pi_roots)
        )

    @property
    def jsonl_globs(self) -> tuple[str, ...]:
        return tuple(str(Path(p).expanduser()) for s in self.jsonl_sources for p in s.paths)


DEFAULT_TOML = f"""\
# priorlog configuration. Every path is opened read-only.
# Docs: https://github.com/vulbsti/priorlog/blob/main/docs/configuration.md

[sources.claude]
enabled = true
roots = ["~/.claude/projects"]
# Claude desktop app session files (local_*.json): titles and desktop ids for CLI sessions.
desktop_roots = ["{_desktop_default()}"]

[sources.codex]
enabled = true
roots = ["~/.codex/sessions"]

[sources.pi]
enabled = true
roots = ["~/.pi/agent/sessions"]

# Any other JSONL log, mapped field by field (dotted paths). Example:
# [[sources.jsonl]]
# name = "mybot"
# paths = ["~/logs/mybot/*.jsonl"]
# text = "body.text"
# role = "speaker"
# session = "conversation_id"
# timestamp = "ts"
# role_map = {{ human = "user", bot = "assistant" }}

[policy]
# Extra path globs never to read (added to the built-in list of credential files).
deny_paths = []
# Regexes: a message matching any of these is dropped entirely and never indexed.
deny_content = []

[redaction]
emails = true
# Also mask long random-looking mixed-case strings (32+ chars). Off by default: it can
# hide legitimate base64 data and identifiers you may want to search for.
high_entropy = false
# Extra patterns, e.g. {{ name = "ticket", pattern = "ACME-[0-9]{{6}}" }}
custom = []

[index]
# search/read run a quick incremental sync first when the index is older than this.
# 0 turns it off (then run `priorlog sync` yourself).
auto_sync_seconds = 300
"""


class ConfigError(ValueError):
    pass


def _paths(values: Any, key: str, base: Path | None = None) -> tuple[Path, ...]:
    if values is None:
        return ()
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ConfigError(f"{key} must be a list of path strings")
    return tuple(_resolve(v, base) for v in values)


def _resolve(value: str, base: Path | None) -> Path:
    """`~` expands to home; other relative paths are relative to the config file's folder."""
    path = Path(value).expanduser()
    return path if path.is_absolute() or base is None else Path(os.path.normpath(base / path))


def _bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false, not {value!r}")
    return value


def _int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{key} must be a whole number of seconds (0 or more), not {value!r}")
    return value


_DEFAULT_ROOTS = {
    ("claude", "roots"): ("~/.claude/projects",),
    ("claude", "desktop_roots"): (_desktop_default(),),
    ("codex", "roots"): ("~/.codex/sessions",),
    ("pi", "roots"): ("~/.pi/agent/sessions",),
}


def _section(data: dict, *keys: str) -> dict:
    cur: Any = data
    for k in keys:
        cur = cur.get(k, {}) if isinstance(cur, dict) else {}
    return cur if isinstance(cur, dict) else {}


def _regex(pattern: Any, where: str) -> re.Pattern[str]:
    if not isinstance(pattern, str):
        raise ConfigError(f"{where} must be a regex string")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"{where}: invalid regex {pattern!r}: {exc}") from exc


def parse(data: dict, source_file: Path | None = None) -> Config:
    """Build a Config from parsed TOML. Unknown keys are ignored; wrong types raise ConfigError."""
    base = source_file.parent.resolve() if source_file else None

    def harness_roots(name: str, key: str = "roots") -> tuple[Path, ...]:
        if name not in _section(data, "sources"):
            return ()  # no [sources.<name>] section: that harness is off (no config file = DEFAULT_TOML)
        sec = _section(data, "sources", name)
        if not _bool(sec.get("enabled", True), f"sources.{name}.enabled"):
            return ()
        if key not in sec:  # section present but this key omitted: use the default location
            return tuple(Path(p).expanduser() for p in _DEFAULT_ROOTS[(name, key)])
        return _paths(sec.get(key), f"sources.{name}.{key}", base)

    jsonl = []
    for i, raw in enumerate(_section(data, "sources").get("jsonl", []) or []):
        where = f"sources.jsonl[{i}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where} must be a table")
        name, paths, text = raw.get("name"), raw.get("paths"), raw.get("text")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ConfigError(f"{where}.name must be a short identifier (letters, digits, _ . -)")
        if isinstance(paths, str):
            paths = [paths]
        if not paths or not all(isinstance(p, str) for p in paths):
            raise ConfigError(f"{where}.paths must be a list of file paths or globs")
        if not isinstance(text, str) or not text:
            raise ConfigError(f"{where}.text must name the field holding the message text")
        role_map = raw.get("role_map") or {}
        if not isinstance(role_map, dict):
            raise ConfigError(f"{where}.role_map must be a table")
        jsonl.append(
            JsonlSource(
                name=name,
                paths=tuple(str(_resolve(p, base)) for p in paths),
                text=text,
                role=raw.get("role"),
                session=raw.get("session"),
                timestamp=raw.get("timestamp"),
                role_map={str(k): str(v) for k, v in role_map.items()},
            )
        )

    policy = _section(data, "policy")
    redaction = _section(data, "redaction")
    custom = []
    for i, item in enumerate(redaction.get("custom", []) or []):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ConfigError(f"redaction.custom[{i}] needs a name and a pattern")
        custom.append(
            CustomPattern(item["name"], _regex(item.get("pattern"), f"redaction.custom[{i}].pattern"))
        )
    extra_deny = policy.get("deny_paths", []) or []
    if not all(isinstance(p, str) for p in extra_deny):
        raise ConfigError("policy.deny_paths must be a list of glob strings")

    index = _section(data, "index")
    db_path = index.get("db_path")
    return Config(
        claude_roots=harness_roots("claude"),
        claude_desktop_roots=harness_roots("claude", "desktop_roots"),
        codex_roots=harness_roots("codex"),
        pi_roots=harness_roots("pi"),
        jsonl_sources=tuple(jsonl),
        deny_paths=DEFAULT_DENY_PATHS + tuple(extra_deny),
        deny_content=tuple(
            _regex(p, f"policy.deny_content[{i}]") for i, p in enumerate(policy.get("deny_content", []) or [])
        ),
        redact_emails=_bool(redaction.get("emails", True), "redaction.emails"),
        redact_high_entropy=_bool(redaction.get("high_entropy", False), "redaction.high_entropy"),
        custom_patterns=tuple(custom),
        auto_sync_seconds=_int(index.get("auto_sync_seconds", 300), "index.auto_sync_seconds"),
        db_path=_resolve(db_path, base) if isinstance(db_path, str) else data_dir() / "index.sqlite3",
        source_file=source_file,
    )


def load(path: Path | None = None) -> Config:
    """Load the config file, or the built-in defaults when there is none yet."""
    path = path or config_path()
    if path.exists():
        with open(path, "rb") as fh:
            try:
                return parse(tomllib.load(fh), path)
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(f"{path}: {exc}") from exc
    return parse(tomllib.loads(DEFAULT_TOML), None)
