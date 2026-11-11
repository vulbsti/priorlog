"""Mask secrets and personal data before anything is stored or returned.

Redaction runs inside the broker: the store calls `Redactor.redact` on every message, title
and working directory before writing, and `read --source` runs it again on raw transcript
lines. No adapter or client can skip it. Raw transcript files are never modified.

Each match becomes `[REDACTED:<kind>]`. Only per-kind counts are kept; matched values are
never logged or stored.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .config import Config, CustomPattern

# Token rules use (?<![A-Za-z0-9]) rather than \b, so a token glued to "_" (e.g. inside a
# tool name like mcp__ghp_...) is still caught.
# (kind, pattern, keep_group): when keep_group is set, that leading group (a label such as
# "Bearer " or "API_KEY=") is kept and only the value after it is masked.
_BUILTIN: list[tuple[str, re.Pattern[str], bool]] = [
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)"
        ),
        False,
    ),
    ("anthropic_key", re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_\-]{10,}"), False),
    ("openai_key", re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}"), False),
    (
        "github_token",
        re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
        False,
    ),
    ("gitlab_token", re.compile(r"(?<![A-Za-z0-9])glpat-[A-Za-z0-9_\-]{20,}"), False),
    ("aws_access_key", re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}\b"), False),
    ("google_api_key", re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}"), False),
    ("slack_token", re.compile(r"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9\-]{10,}"), False),
    ("stripe_key", re.compile(r"(?<![A-Za-z0-9])[rs]k_(?:live|test)_[A-Za-z0-9]{16,}"), False),
    ("huggingface_token", re.compile(r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{30,}"), False),
    (
        "jwt",
        re.compile(r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
        False,
    ),
    ("bearer_token", re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=\-]{12,}"), True),
    ("basic_auth", re.compile(r"(?i)(\bauthorization:\s*basic\s+)[A-Za-z0-9+/=]{8,}"), True),
    ("url_credentials", re.compile(r"(\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:)[^\s@/]+(?=@)"), True),
    ("cookie", re.compile(r"(?im)^(\s*(?:set-)?cookie:\s*).+$"), True),
    # KEY=value / KEY: value assignments as printed by env, .env files, shell exports and
    # JSON/YAML, when the key name says it holds a secret.
    (
        "secret_assignment",
        re.compile(
            r"""(?ix)
        ( \b[\w.\-]*?(?:api[_\-]?key|secret(?:[_\-]?key)?|token|passw(?:or)?d|passwd|pwd|credential|private[_\-]?key|access[_\-]?key)s?
          ["']?\s*[:=]\s*["']? )
        (?!\[REDACTED)(?!\d+\b)[^\s"',;}{]{6,}"""
        ),
        True,
    ),
]

_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}\b")
_HIGH_ENTROPY = re.compile(r"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{32,}={0,2}(?![A-Za-z0-9+/_\-])")
_PLACEHOLDER = re.compile(r"\[REDACTED:[a-z_0-9]+\]")


def _entropy(s: str) -> float:
    counts = Counter(s)
    return -sum(c / len(s) * math.log2(c / len(s)) for c in counts.values())


def _looks_random(s: str) -> bool:
    has_upper = any(c.isupper() for c in s)
    has_lower = any(c.islower() for c in s)
    has_digit = any(c.isdigit() for c in s)
    return has_upper + has_lower + has_digit >= 3 and _entropy(s) >= 4.0


@dataclass
class RedactionResult:
    text: str
    counts: Counter = field(default_factory=Counter)


class Redactor:
    def __init__(self, config: Config | None = None) -> None:
        cfg = config or Config()
        self.rules: list[tuple[str, re.Pattern[str], bool]] = list(_BUILTIN)
        if cfg.redact_emails:
            self.rules.append(("email", _EMAIL, False))
        self.rules.extend(
            (f"custom_{c.name}", c.pattern, False)
            for c in cfg.custom_patterns
            if isinstance(c, CustomPattern)
        )
        self.high_entropy = cfg.redact_high_entropy

    def redact(self, text: str) -> RedactionResult:
        counts: Counter = Counter()
        if not text:
            return RedactionResult(text or "", counts)
        for kind, rx, keep in self.rules:

            def sub(m: re.Match[str], kind: str = kind, keep: bool = keep) -> str:
                if _PLACEHOLDER.fullmatch(m.group(0)):
                    return m.group(0)
                counts[kind] += 1
                return (m.group(1) if keep else "") + f"[REDACTED:{kind}]"

            text = rx.sub(sub, text)
        if self.high_entropy:

            def sub_entropy(m: re.Match[str]) -> str:
                if not _looks_random(m.group(0)):
                    return m.group(0)
                counts["high_entropy"] += 1
                return "[REDACTED:high_entropy]"

            text = _HIGH_ENTROPY.sub(sub_entropy, text)
        return RedactionResult(text, counts)

    def __call__(self, text: str) -> str:
        return self.redact(text).text
