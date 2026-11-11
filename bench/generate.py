"""Generate a deterministic synthetic transcript corpus for the priorlog benchmark.

    uv run python bench/generate.py OUT_DIR [--messages 55000] [--seed 20261105]
    uv run python bench/generate.py OUT_DIR --append          # one "1% growth" round

The corpus uses the real on-disk formats that priorlog's adapters read:

  OUT/claude/projects/-work-<proj>/<uuid>.jsonl                    Claude Code sessions
  OUT/claude/projects/-work-<proj>/<uuid>/subagents/agent-<id>.jsonl   (+ .meta.json)
  OUT/codex/sessions/2026/MM/DD/rollout-<ts>-<uuid>.jsonl           Codex CLI rollouts
  OUT/pi/sessions/--work-<proj>--/<ts>_<uuid>.jsonl                 Pi sessions
  OUT/jsonl/support-2026-MM-DD.jsonl                                a generic JSONL log

plus OUT/config.toml (every source pointed at OUT, index at OUT/data/index.sqlite3, auto sync
off) and OUT/manifest.json (how many messages priorlog should index, per harness).

`--messages` counts *indexed* messages: after an assistant turn's text, tool calls and
tool results are merged into one message, and after tool results and injected context are
dropped. Every random choice comes from one seeded `random.Random`, so the same seed and the
same Python version produce byte-identical files. Text is drawn from a Zipf-distributed
vocabulary of prose words, code identifiers, file paths, error names and technical phrases, so
trigram matching sees realistic common, mid-frequency and rare substrings.
"""

from __future__ import annotations

import argparse
import base64
import itertools
import json
import math
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

SEED = 20261105
TARGET_MESSAGES = 55_000
SHARES = {"claude": 0.55, "codex": 0.20, "pi": 0.15, "jsonl": 0.10}
EPOCH = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

# --------------------------------------------------------------------------- vocabulary

PROSE = [
    "the",
    "to",
    "a",
    "of",
    "and",
    "is",
    "in",
    "it",
    "that",
    "for",
    "this",
    "we",
    "on",
    "with",
    "be",
    "not",
    "as",
    "but",
    "if",
    "so",
    "can",
    "should",
    "will",
    "when",
    "then",
    "there",
    "now",
    "just",
    "also",
    "it's",
    "I",
    "you",
    "let",
    "me",
    "check",
    "run",
    "test",
    "fix",
    "change",
    "update",
    "file",
    "line",
    "error",
    "value",
    "function",
    "call",
    "return",
    "issue",
    "problem",
    "case",
    "way",
    "time",
    "need",
    "use",
    "look",
    "add",
    "remove",
    "move",
    "keep",
    "make",
    "work",
    "try",
    "see",
    "find",
    "seems",
    "instead",
    "because",
    "before",
    "after",
    "again",
    "first",
    "last",
    "next",
    "still",
    "already",
    "only",
    "maybe",
    "probably",
    "actually",
    "happens",
    "wrong",
    "right",
    "correct",
    "missing",
    "failing",
    "passing",
    "slow",
    "fast",
    "clean",
    "simple",
    "small",
    "large",
    "old",
    "new",
    "same",
    "different",
    "other",
    "each",
    "every",
    "all",
    "some",
    "any",
    "more",
    "less",
    "than",
    "both",
    "either",
    "into",
    "from",
    "about",
    "between",
    "without",
    "within",
    "through",
    "over",
    "under",
    "while",
    "until",
    "since",
    "please",
    "thanks",
    "okay",
    "good",
    "bad",
    "better",
    "worse",
    "done",
    "ready",
    "broken",
    "fixed",
    "works",
    "now",
    "here",
    "why",
    "how",
    "what",
    "which",
    "where",
    "who",
    "rather",
    "pretty",
    "quite",
    "very",
    "really",
    "likely",
    "unlikely",
    "expected",
    "unexpected",
    "output",
    "input",
    "result",
    "results",
    "setup",
    "teardown",
    "local",
    "remote",
    "production",
    "staging",
    "default",
    "custom",
    "manual",
    "automatic",
    "explicit",
    "implicit",
    "nothing",
    "everything",
    "something",
    "someone",
    "server",
    "client",
    "request",
    "response",
    "data",
    "state",
    "cache",
    "config",
    "build",
    "release",
    "deploy",
    "rollback",
    "review",
    "commit",
    "branch",
    "merge",
    "rebase",
    "push",
    "pull",
    "version",
    "upgrade",
    "downgrade",
    "dependency",
    "library",
    "package",
    "module",
    "script",
    "command",
    "flag",
    "option",
    "argument",
    "parameter",
    "variable",
    "constant",
    "field",
    "method",
    "class",
    "object",
    "instance",
    "type",
    "interface",
    "struct",
    "enum",
    "trait",
    "generic",
    "async",
    "await",
    "thread",
    "process",
    "memory",
    "disk",
    "network",
    "latency",
    "throughput",
    "timeout",
    "retry",
    "limit",
    "queue",
    "worker",
    "job",
    "task",
    "schedule",
    "event",
    "handler",
    "callback",
    "promise",
]

VERBS = [
    "get",
    "set",
    "load",
    "save",
    "parse",
    "build",
    "make",
    "create",
    "update",
    "delete",
    "fetch",
    "read",
    "write",
    "init",
    "reset",
    "validate",
    "normalize",
    "resolve",
    "render",
    "compute",
    "handle",
    "process",
    "flush",
    "sync",
    "merge",
    "split",
    "apply",
    "check",
    "ensure",
    "emit",
    "dispatch",
    "register",
    "encode",
    "decode",
    "serialize",
    "migrate",
    "index",
    "search",
    "sort",
    "filter",
    "map",
    "reduce",
    "collect",
    "spawn",
    "join",
    "close",
    "open",
    "lock",
    "unlock",
    "retry",
    "refresh",
    "rotate",
    "prune",
    "compact",
]

NOUNS = [
    "user",
    "session",
    "token",
    "config",
    "cache",
    "request",
    "response",
    "handler",
    "client",
    "server",
    "worker",
    "queue",
    "job",
    "task",
    "event",
    "message",
    "payload",
    "record",
    "row",
    "column",
    "index",
    "schema",
    "table",
    "query",
    "result",
    "buffer",
    "stream",
    "file",
    "path",
    "node",
    "tree",
    "graph",
    "edge",
    "store",
    "repo",
    "commit",
    "branch",
    "test",
    "fixture",
    "mock",
    "adapter",
    "parser",
    "lexer",
    "router",
    "middleware",
    "auth",
    "permission",
    "policy",
    "rule",
    "limit",
    "bucket",
    "window",
    "retry",
    "backoff",
    "timeout",
    "deadline",
    "clock",
    "timer",
    "metric",
    "counter",
    "gauge",
    "span",
    "trace",
    "logger",
    "error",
    "exception",
    "state",
    "context",
    "manager",
    "factory",
    "provider",
    "service",
    "controller",
    "model",
    "view",
    "template",
    "widget",
    "layout",
    "theme",
    "asset",
    "bundle",
    "chunk",
    "module",
    "package",
    "plugin",
    "hook",
    "signal",
    "channel",
    "socket",
    "pool",
    "connection",
    "transaction",
    "migration",
    "tenant",
    "order",
    "invoice",
    "payment",
    "account",
    "webhook",
    "export",
    "import",
    "upload",
    "download",
    "report",
    "snapshot",
]

QUALS = [
    "id",
    "ids",
    "map",
    "list",
    "count",
    "size",
    "key",
    "value",
    "name",
    "type",
    "kind",
    "mode",
    "flag",
    "opts",
    "args",
    "meta",
    "info",
    "data",
    "cfg",
    "ctx",
    "url",
    "uri",
    "ref",
    "refs",
    "hash",
    "len",
    "idx",
    "num",
    "ms",
    "secs",
    "bytes",
    "total",
]

SUFFIXES = [
    "Manager",
    "Service",
    "Error",
    "Handler",
    "Factory",
    "Config",
    "Client",
    "Store",
    "Builder",
    "Provider",
    "Registry",
    "Adapter",
]

DIRS = [
    "src",
    "lib",
    "app",
    "pkg",
    "internal",
    "cmd",
    "tests",
    "scripts",
    "docs",
    "api",
    "core",
    "utils",
    "services",
    "models",
    "web",
    "cli",
    "handlers",
    "routes",
    "db",
    "migrations",
    "config",
    "jobs",
    "workers",
    "fixtures",
    "components",
    "hooks",
    "store",
]

EXTS = [
    ".py",
    ".py",
    ".py",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".md",
    ".toml",
    ".yaml",
    ".json",
    ".sql",
    ".sh",
    ".js",
]

ERRORS = [
    "ValueError",
    "KeyError",
    "TypeError",
    "AttributeError",
    "ImportError",
    "ModuleNotFoundError",
    "TimeoutError",
    "ConnectionResetError",
    "ConnectionRefusedError",
    "FileNotFoundError",
    "PermissionError",
    "RuntimeError",
    "AssertionError",
    "IndexError",
    "UnicodeDecodeError",
    "RecursionError",
    "OSError",
    "ECONNREFUSED",
    "ENOENT",
    "EACCES",
    "ETIMEDOUT",
    "EADDRINUSE",
    "SIGSEGV",
    "SIGKILL",
    "NullPointerException",
    "IllegalStateException",
    "OperationalError",
    "IntegrityError",
    "DeadlockDetected",
    "ReferenceError",
    "SyntaxError",
]

PHRASES = [
    "token bucket",
    "connection pool",
    "race condition",
    "rate limiter",
    "exponential backoff",
    "feature flag",
    "dead letter queue",
    "memory leak",
    "off by one",
    "cache invalidation",
    "flaky test",
    "integration test",
    "unit test",
    "merge conflict",
    "pull request",
    "code review",
    "database migration",
    "schema change",
    "lock contention",
    "query plan",
    "full table scan",
    "hot path",
    "cold start",
    "event loop",
    "thread pool",
    "back pressure",
    "circuit breaker",
    "health check",
    "load balancer",
    "connection reset",
    "stack trace",
    "build cache",
    "dependency upgrade",
    "breaking change",
    "release notes",
    "environment variable",
    "config file",
    "log level",
    "retry budget",
    "idempotency key",
    "write ahead log",
    "sliding window",
    "consistent hashing",
    "bloom filter",
    "binary search",
    "garbage collector",
    "file descriptor",
    "signal handler",
    "zombie process",
    "permission denied",
    "disk full",
    "out of memory",
    "segmentation fault",
    "infinite loop",
    "dead code",
    "unused import",
    "pre-commit hook",
    "ci pipeline",
    "docker image",
    "cron job",
    "time zone",
    "unicode normalization",
]

PROJECTS = [
    "orders-api",
    "billing-service",
    "web-dashboard",
    "data-pipeline",
    "auth-gateway",
    "search-indexer",
    "mobile-backend",
    "infra-terraform",
    "ml-training",
    "cli-tools",
    "docs-site",
    "event-bus",
    "notification-service",
    "inventory-sync",
    "analytics-etl",
    "payments-core",
    "admin-portal",
    "feature-store",
    "chat-widget",
    "image-resizer",
    "log-shipper",
    "scheduler",
    "report-builder",
    "customer-portal",
    "rate-gateway",
    "cache-proxy",
    "sdk-python",
    "sdk-typescript",
    "graph-service",
    "ledger",
]

CLAUDE_TOOLS = (
    ["Bash"] * 6 + ["Read"] * 5 + ["Edit"] * 4 + ["Grep"] * 3 + ["Glob", "Write", "TodoWrite", "Task"]
)
CODEX_TOOLS = ["shell"] * 8 + ["apply_patch"] * 2 + ["update_plan"]
PI_TOOLS = ["bash"] * 5 + ["read"] * 4 + ["edit"] * 3 + ["write"]


class Pool:
    """Zipf-weighted draws from a ranked list (rank 1 = most frequent), buffered for speed."""

    def __init__(self, rng: random.Random, items: list[str], s: float) -> None:
        self.rng, self.items = rng, items
        self.cum = list(itertools.accumulate(1.0 / (r**s) for r in range(1, len(items) + 1)))
        self.buf: list[str] = []

    def __call__(self) -> str:
        if not self.buf:
            self.buf = self.rng.choices(self.items, cum_weights=self.cum, k=4096)
        return self.buf.pop()


class Vocab:
    """Ranked vocabularies. Built from its own RNG so run.py can rebuild the same ranks."""

    def __init__(self, seed: int = SEED) -> None:
        r = random.Random(seed ^ 0x5EED)
        idents: dict[str, None] = {}
        while len(idents) < 6000:
            form = r.random()
            v, n, q = r.choice(VERBS), r.choice(NOUNS), r.choice(QUALS)
            if form < 0.45:
                ident = f"{v}_{n}" + (f"_{q}" if r.random() < 0.5 else "")
            elif form < 0.70:
                ident = v + n.capitalize() + (q.capitalize() if r.random() < 0.5 else "")
            elif form < 0.90:
                ident = n.capitalize() + r.choice(NOUNS).capitalize() + r.choice(SUFFIXES)
            else:
                ident = f"{n.upper()}_{q.upper()}" + (
                    f"_{r.choice(QUALS).upper()}" if r.random() < 0.5 else ""
                )
            idents[ident] = None
        self.idents = list(idents)
        r.shuffle(self.idents)
        paths: dict[str, None] = {}
        while len(paths) < 3000:
            depth = r.choice((1, 1, 2, 2, 3))
            parts = [r.choice(DIRS) for _ in range(depth)]
            name = f"{r.choice(VERBS)}_{r.choice(NOUNS)}" if r.random() < 0.6 else r.choice(NOUNS)
            paths["/".join(parts) + "/" + name + r.choice(EXTS)] = None
        self.paths = list(paths)
        r.shuffle(self.paths)
        self.prose = list(PROSE)
        self.errors = list(ERRORS)
        self.phrases = list(PHRASES)


class Text:
    """Draws sentences, code blocks and tool output from a Vocab with one corpus RNG."""

    def __init__(self, rng: random.Random, vocab: Vocab) -> None:
        self.rng, self.v = rng, vocab
        self.prose = Pool(rng, vocab.prose, 1.0)
        self.ident = Pool(rng, vocab.idents, 1.07)
        self.path = Pool(rng, vocab.paths, 1.0)
        self.error = Pool(rng, vocab.errors, 1.1)
        self.phrase = Pool(rng, vocab.phrases, 1.0)

    def word(self) -> str:
        x = self.rng.random()
        if x < 0.66:
            return self.prose()
        if x < 0.78:
            return f"`{self.ident()}`"
        if x < 0.84:
            return self.ident()
        if x < 0.92:
            return self.path()
        if x < 0.95:  # technical phrases: the top one ends up in ~1 message in 4
            return self.phrase()
        if x < 0.98:
            return self.error()
        return str(self.rng.randint(0, 99999))

    def sentence(self) -> str:
        words = [self.word() for _ in range(self.rng.randint(5, 22))]
        s = " ".join(words)
        return s[:1].upper() + s[1:] + self.rng.choice("....?:")

    def para(self, n: int) -> str:
        return " ".join(self.sentence() for _ in range(n))

    def secret(self) -> str:
        """A fake credential or email, so redaction has realistic work to do (~0.5% of messages)."""
        alnum = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        val = "".join(self.rng.choice(alnum) for _ in range(32))
        return self.rng.choice(
            (
                f"export API_KEY={val}",
                f"curl -H 'Authorization: Bearer {val}' https://api.example.test/v1/orders",
                f"ping ops-{self.rng.randint(1, 99)}@example.com about it",
                f"DB_PASSWORD={val[:16]} in the staging env",
            )
        )

    def code(self, target: int) -> str:
        lines = [f"```{self.rng.choice(('python', 'ts', 'go', 'diff', 'sql', ''))}"]
        size = 0
        indent = 0
        while size < target:
            t = self.rng.random()
            a, b = self.ident(), self.ident()
            if t < 0.15:
                line = f"def {a}({b}, opts=None):"
                indent = 1
            elif t < 0.35:
                line = "    " * indent + f"{a} = {b}.get({self.path()!r})"
            elif t < 0.50:
                line = "    " * indent + f"if not {a}: raise {self.error()}(f'{self.prose()} {{{b}}}')"
            elif t < 0.62:
                line = "    " * indent + f"return {a}({b}, timeout={self.rng.randint(1, 120)})"
            elif t < 0.72:
                line = f"from {self.path().rsplit('.', 1)[0].replace('/', '.')} import {a}, {b}"
                indent = 0
            elif t < 0.82:
                line = "    " * indent + f"# {self.sentence()}"
            elif t < 0.92:
                line = f"{'+' if t < 0.87 else '-'}    {a}.{b}()"
            else:
                line = ""
            lines.append(line)
            size += len(line) + 1
        lines.append("```")
        return "\n".join(lines)

    def output(self, target: int) -> str:
        """Tool output (never indexed, but read and parsed by every sync)."""
        lines, size = [], 0
        while size < target:
            t = self.rng.random()
            if t < 0.4:
                line = (
                    f"{self.path()}:{self.rng.randint(1, 900)}: {self.ident()} {self.prose()} {self.ident()}"
                )
            elif t < 0.6:
                line = f'  File "{self.path()}", line {self.rng.randint(1, 900)}, in {self.ident()}'
            elif t < 0.75:
                line = f"{self.error()}: {self.sentence()}"
            else:
                line = f"{self.rng.randint(0, 99):>3} | {self.ident()}({self.ident()}) -> {self.ident()}"
            lines.append(line)
            size += len(line) + 1
        return "\n".join(lines)

    def user_text(self) -> str:
        x = self.rng.random()
        if x < 0.70:
            text = self.para(self.rng.randint(1, 3))
        elif x < 0.92:
            text = self.para(self.rng.randint(4, 10))
        else:
            text = self.para(1) + "\n\n" + self.code(self.rng.randint(800, 6000))
        if self.rng.random() < 0.005:
            text += " " + self.secret()
        return text

    def assistant_text(self) -> str:
        x = self.rng.random()
        if x < 0.55:
            text = self.para(self.rng.randint(1, 3))
        elif x < 0.88:
            text = self.para(self.rng.randint(4, 12))
        elif x < 0.99:
            text = self.para(2) + "\n\n" + self.code(self.rng.randint(1000, 8000)) + "\n\n" + self.para(1)
        else:
            text = self.para(3) + "\n\n" + self.code(self.rng.randint(20_000, 40_000))
        if self.rng.random() < 0.005:
            text += " " + self.secret()
        return text

    def output_size(self) -> int:
        x = self.rng.random()
        if x < 0.6:
            return self.rng.randint(40, 600)
        if x < 0.95:
            return self.rng.randint(600, 4000)
        return self.rng.randint(4000, 30_000)


def session_length(rng: random.Random) -> int:
    """Exchanges (user message + assistant turn) per session: most short, a long tail."""
    x = rng.random()
    if x < 0.70:
        return rng.randint(1, 8)
    if x < 0.95:
        return rng.randint(9, 40)
    return rng.randint(41, 200)


def _uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _dump(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- Claude Code


class ClaudeWriter:
    def __init__(self, rng: random.Random, text: Text, sid: str, cwd: str, branch: str) -> None:
        self.rng, self.t, self.sid, self.cwd, self.branch = rng, text, sid, cwd, branch
        self.parent: str | None = None

    def _base(self, kind: str, ts: datetime) -> dict:
        u = _uuid(self.rng)
        d = {
            "parentUuid": self.parent,
            "isSidechain": False,
            "userType": "external",
            "cwd": self.cwd,
            "sessionId": self.sid,
            "version": "2.1.3",
            "gitBranch": self.branch,
            "type": kind,
            "uuid": u,
            "timestamp": _iso(ts),
        }
        self.parent = u
        return d

    def _assistant(self, block: dict, ts: datetime) -> str:
        d = self._base("assistant", ts)
        d["requestId"] = "req_" + base64.b32encode(self.rng.randbytes(15)).decode().lower()
        d["message"] = {
            "id": "msg_" + base64.b32encode(self.rng.randbytes(15)).decode().lower(),
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-x",
            "content": [block],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": self.rng.randint(1, 50),
                "cache_creation_input_tokens": self.rng.randint(0, 5000),
                "cache_read_input_tokens": self.rng.randint(1000, 90_000),
                "output_tokens": self.rng.randint(5, 2000),
            },
        }
        return _dump(d)

    def exchange(self, ts: datetime) -> tuple[list[str], int, datetime]:
        """One user message and the assistant turn after it. Returns (lines, indexed, end ts)."""
        rng, t = self.rng, self.t
        lines: list[str] = []
        indexed = 0
        if rng.random() < 0.03:  # injected meta line: never indexed
            d = self._base("user", ts)
            d["isMeta"] = True
            d["message"] = {
                "role": "user",
                "content": "<local-command-caveat>Caveat: generated.</local-command-caveat>",
            }
            lines.append(_dump(d))
        d = self._base("user", ts)
        if rng.random() < 0.05:
            content = f"<command-name>/{rng.choice(('review', 'compact', 'init', 'test'))}</command-name><command-args>{t.sentence()}</command-args>"
        else:
            content = t.user_text()
            if rng.random() < 0.10:
                content = f"<system-reminder>{t.sentence()}</system-reminder>{content}"
        d["message"] = {"role": "user", "content": content}
        lines.append(_dump(d))
        indexed += 1
        ts += timedelta(seconds=rng.randint(2, 30))
        if rng.random() < 0.04:
            d = self._base("attachment", ts)
            d["attachment"] = {"type": "file", "path": t.path()}
            lines.append(_dump(d))
        if rng.random() < 0.5:
            lines.append(self._assistant({"type": "text", "text": t.para(rng.randint(1, 2))}, ts))
        x = rng.random()
        n_tools = 0 if x < 0.35 else rng.randint(1, 3) if x < 0.85 else rng.randint(4, 14)
        for _ in range(n_tools):
            tid = "toolu_" + base64.b32encode(rng.randbytes(15)).decode().lower()
            name = rng.choice(CLAUDE_TOOLS)
            inp = {"command": f"rg -n {t.ident()} {t.path()}"} if name == "Bash" else {"file_path": t.path()}
            lines.append(self._assistant({"type": "tool_use", "id": tid, "name": name, "input": inp}, ts))
            ts += timedelta(seconds=rng.randint(1, 20))
            out = t.output(t.output_size())
            d = self._base("user", ts)
            d["message"] = {
                "role": "user",
                "content": [{"tool_use_id": tid, "type": "tool_result", "content": out, "is_error": False}],
            }
            d["toolUseResult"] = {"stdout": out, "stderr": "", "interrupted": False, "isImage": False}
            lines.append(_dump(d))
        if n_tools == 0 or rng.random() < 0.85:
            lines.append(self._assistant({"type": "text", "text": t.assistant_text()}, ts))
        indexed += 1  # text and tool calls merge into one assistant message
        return lines, indexed, ts + timedelta(seconds=rng.randint(5, 600))


def write_claude(out: Path, rng: random.Random, t: Text, budget: int, start: datetime) -> tuple[int, int]:
    """Claude Code project dirs until `budget` indexed messages exist. Returns (messages, files)."""
    root = out / "claude" / "projects"
    count = files = 0
    ts = start
    while count < budget:
        proj = rng.choice(PROJECTS)
        cwd = f"/work/{proj}"
        sid = _uuid(rng)
        branch = rng.choice(("main", "main", "dev", f"feat/{rng.choice(NOUNS)}-{rng.choice(VERBS)}"))
        n = min(session_length(rng), max(1, math.ceil((budget - count) / 2)))
        w = ClaudeWriter(rng, t, sid, cwd, branch)
        pdir = root / f"-work-{proj}"
        pdir.mkdir(parents=True, exist_ok=True)
        lines = [_dump({"type": "permission-mode", "permissionMode": "default", "sessionId": sid})]
        lines.append(
            _dump(
                {
                    "type": "file-history-snapshot",
                    "messageId": _uuid(rng),
                    "snapshot": {"trackedFileBackups": {}},
                }
            )
        )
        for i in range(n):
            chunk, k, ts = w.exchange(ts)
            lines += chunk
            count += k
            if i == 0:
                lines.append(_dump({"type": "ai-title", "aiTitle": t.sentence()[:60], "sessionId": sid}))
        (pdir / f"{sid}.jsonl").write_text("".join(lines))
        files += 1
        if rng.random() < 0.10 and count < budget:  # subagents of this session
            sub = pdir / sid / "subagents"
            sub.mkdir(parents=True, exist_ok=True)
            for _ in range(rng.randint(1, 3)):
                aid = base64.b32encode(rng.randbytes(10)).decode().lower()
                sw = ClaudeWriter(rng, t, sid, cwd, branch)  # subagent lines carry the parent's id
                slines: list[str] = []
                for _ in range(rng.randint(2, 10)):
                    chunk, k, ts = sw.exchange(ts)
                    slines += chunk
                    count += k
                (sub / f"agent-{aid}.jsonl").write_text("".join(slines))
                (sub / f"agent-{aid}.meta.json").write_text(json.dumps({"description": t.sentence()[:60]}))
                files += 1
        ts += timedelta(minutes=rng.randint(10, 600))
    return count, files


# --------------------------------------------------------------------------- Codex CLI


def codex_exchange(rng: random.Random, t: Text, ts: datetime) -> tuple[list[str], int, datetime]:
    def item(payload: dict, kind: str = "response_item") -> str:
        return _dump({"timestamp": _iso(ts), "type": kind, "payload": payload})

    lines = []
    text = t.user_text()
    lines.append(item({"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}))
    lines.append(item({"type": "user_message", "message": text, "images": []}, "event_msg"))
    ts += timedelta(seconds=rng.randint(2, 30))
    x = rng.random()
    n_tools = 0 if x < 0.3 else rng.randint(1, 3) if x < 0.85 else rng.randint(4, 12)
    for _ in range(n_tools):
        enc = base64.b64encode(rng.randbytes(rng.randint(200, 1200))).decode()
        lines.append(item({"type": "reasoning", "summary": [], "content": None, "encrypted_content": enc}))
        cid = "call_" + base64.b32encode(rng.randbytes(12)).decode().lower()
        name = rng.choice(CODEX_TOOLS)
        args = json.dumps({"command": ["bash", "-lc", f"rg -n {t.ident()} {t.path()}"], "workdir": "/work"})
        lines.append(item({"type": "function_call", "name": name, "arguments": args, "call_id": cid}))
        out = json.dumps(
            {"output": t.output(t.output_size()), "metadata": {"exit_code": 0, "duration_seconds": 0.2}}
        )
        lines.append(item({"type": "function_call_output", "call_id": cid, "output": out}))
        ts += timedelta(seconds=rng.randint(1, 20))
    answer = t.assistant_text()
    lines.append(
        item({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": answer}]})
    )
    lines.append(item({"type": "agent_message", "message": answer}, "event_msg"))
    lines.append(
        item(
            {
                "type": "token_count",
                "info": {"total_token_usage": {"input_tokens": rng.randint(1000, 90000)}},
            },
            "event_msg",
        )
    )
    return lines, 2, ts + timedelta(seconds=rng.randint(5, 600))


def write_codex(out: Path, rng: random.Random, t: Text, budget: int, start: datetime) -> tuple[int, int]:
    count = files = 0
    ts = start
    while count < budget:
        sid = _uuid(rng)
        proj = rng.choice(PROJECTS)
        n = min(session_length(rng), max(1, math.ceil((budget - count) / 2)))
        day = out / "codex" / "sessions" / ts.strftime("%Y/%m/%d")
        day.mkdir(parents=True, exist_ok=True)
        meta = {
            "id": sid,
            "timestamp": _iso(ts),
            "cwd": f"/work/{proj}",
            "originator": "codex_cli_rs",
            "cli_version": "0.50.0",
            "instructions": None,
            "git": {"commit_hash": rng.randbytes(20).hex(), "branch": "main"},
        }
        lines = [_dump({"timestamp": _iso(ts), "type": "session_meta", "payload": meta})]
        lines.append(
            _dump(
                {
                    "timestamp": _iso(ts),
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "developer",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "<permissions instructions>sandboxed</permissions instructions>",
                            }
                        ],
                    },
                }
            )
        )
        env = (
            f"<environment_context>\n  <cwd>/work/{proj}</cwd>\n  <shell>bash</shell>\n</environment_context>"
        )
        lines.append(
            _dump(
                {
                    "timestamp": _iso(ts),
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": env}],
                    },
                }
            )
        )
        lines.append(
            _dump(
                {
                    "timestamp": _iso(ts),
                    "type": "turn_context",
                    "payload": {"cwd": f"/work/{proj}", "model": "gpt-x"},
                }
            )
        )
        for _ in range(n):
            chunk, k, ts = codex_exchange(rng, t, ts)
            lines += chunk
            count += k
        name = f"rollout-{ts.strftime('%Y-%m-%dT%H-%M-%S')}-{sid}.jsonl"
        (day / name).write_text("".join(lines))
        files += 1
        ts += timedelta(minutes=rng.randint(10, 600))
    return count, files


# --------------------------------------------------------------------------- Pi


def pi_exchange(rng: random.Random, t: Text, ts: datetime, prev: str) -> tuple[list[str], int, datetime, str]:
    lines = []

    def msg(message: dict) -> str:
        nonlocal prev
        eid = rng.randbytes(4).hex()
        line = _dump(
            {"type": "message", "id": eid, "parentId": prev, "timestamp": _iso(ts), "message": message}
        )
        prev = eid
        return line

    lines.append(msg({"role": "user", "content": [{"type": "text", "text": t.user_text()}], "timestamp": 1}))
    ts += timedelta(seconds=rng.randint(2, 30))
    x = rng.random()
    n_tools = 0 if x < 0.3 else rng.randint(1, 3) if x < 0.85 else rng.randint(4, 12)
    for _ in range(n_tools):
        tcid = "tc_" + rng.randbytes(6).hex()
        name = rng.choice(PI_TOOLS)
        blocks = [
            {"type": "thinking", "thinking": t.sentence()},
            {"type": "toolCall", "id": tcid, "name": name, "arguments": {"command": f"rg {t.ident()}"}},
        ]
        lines.append(
            msg(
                {
                    "role": "assistant",
                    "content": blocks,
                    "provider": "x",
                    "model": "y",
                    "stopReason": "toolUse",
                }
            )
        )
        ts += timedelta(seconds=rng.randint(1, 20))
        out = t.output(t.output_size())
        lines.append(
            msg(
                {
                    "role": "toolResult",
                    "toolCallId": tcid,
                    "toolName": name,
                    "content": [{"type": "text", "text": out}],
                    "isError": False,
                }
            )
        )
    lines.append(
        msg(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": t.assistant_text()}],
                "provider": "x",
                "model": "y",
                "stopReason": "stop",
            }
        )
    )
    return lines, 2, ts + timedelta(seconds=rng.randint(5, 600)), prev


def write_pi(out: Path, rng: random.Random, t: Text, budget: int, start: datetime) -> tuple[int, int]:
    count = files = 0
    ts = start
    while count < budget:
        sid = _uuid(rng)
        proj = rng.choice(PROJECTS)
        n = min(session_length(rng), max(1, math.ceil((budget - count) / 2)))
        d = out / "pi" / "sessions" / f"--work-{proj}--"
        d.mkdir(parents=True, exist_ok=True)
        lines = [
            _dump({"type": "session", "version": 3, "id": sid, "timestamp": _iso(ts), "cwd": f"/work/{proj}"})
        ]
        lines.append(
            _dump(
                {
                    "type": "model_change",
                    "id": "m0",
                    "parentId": None,
                    "timestamp": _iso(ts),
                    "provider": "x",
                    "modelId": "y",
                }
            )
        )
        prev = "m0"
        for _ in range(n):
            chunk, k, ts, prev = pi_exchange(rng, t, ts, prev)
            lines += chunk
            count += k
        (d / f"{ts.strftime('%Y-%m-%dT%H-%M-%S-000Z')}_{sid}.jsonl").write_text("".join(lines))
        files += 1
        ts += timedelta(minutes=rng.randint(10, 600))
    return count, files


# --------------------------------------------------------------------------- generic JSONL


def jsonl_line(rng: random.Random, t: Text, conv: str, ts: datetime, speaker: str) -> str:
    text = t.para(rng.randint(1, 4)) if rng.random() < 0.9 else t.para(rng.randint(5, 15))
    return _dump(
        {
            "conversation_id": conv,
            "speaker": speaker,
            "ts": _iso(ts),
            "channel": "web",
            "body": {"text": text},
        }
    )


def write_jsonl(out: Path, rng: random.Random, t: Text, budget: int, start: datetime) -> tuple[int, int]:
    d = out / "jsonl"
    d.mkdir(parents=True, exist_ok=True)
    count = files = 0
    ts = start
    conv_no = 0
    while count < budget:
        lines = []
        for _ in range(rng.randint(5, 40)):  # conversations that day
            conv_no += 1
            for j in range(rng.randint(2, 12)):
                lines.append(jsonl_line(rng, t, f"conv-{conv_no}", ts, "customer" if j % 2 == 0 else "bot"))
                ts += timedelta(seconds=rng.randint(5, 120))
                count += 1
        (d / f"support-{ts.strftime('%Y-%m-%d')}-{files:04d}.jsonl").write_text("".join(lines))
        files += 1
        ts += timedelta(days=1)
    return count, files


# --------------------------------------------------------------------------- config / main


def write_config(corpus: Path, db_path: Path) -> Path:
    """A priorlog config that reads only this corpus and keeps the index at `db_path`."""
    c = corpus.resolve()
    cfg = corpus / "config.toml"
    cfg.write_text(f"""\
# priorlog benchmark config (generated by bench/generate.py). Reads only this corpus.
[sources.claude]
roots = ["{c}/claude/projects"]
desktop_roots = []
[sources.codex]
roots = ["{c}/codex/sessions"]
[sources.pi]
roots = ["{c}/pi/sessions"]
[[sources.jsonl]]
name = "supportbot"
paths = ["{c}/jsonl/*.jsonl"]
text = "body.text"
role = "speaker"
session = "conversation_id"
timestamp = "ts"
role_map = {{ customer = "user", bot = "assistant" }}
[index]
db_path = "{db_path.resolve()}"
auto_sync_seconds = 0
""")
    return cfg


def generate(out: Path, messages: int = TARGET_MESSAGES, seed: int = SEED) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    t = Text(rng, Vocab(seed))
    counts, files = {}, {}
    writers = {"claude": write_claude, "codex": write_codex, "pi": write_pi, "jsonl": write_jsonl}
    for name, fn in writers.items():
        counts[name], files[name] = fn(out, rng, t, math.ceil(messages * SHARES[name]), EPOCH)
    total_bytes = sum(p.stat().st_size for p in out.rglob("*.jsonl"))
    manifest = {
        "seed": seed,
        "python": sys.version.split()[0],
        "expected_messages": counts,
        "expected_total": sum(counts.values()),
        "files": files,
        "files_total": sum(files.values()),
        "jsonl_bytes": total_bytes,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    write_config(out, out / "data" / "index.sqlite3")
    return manifest


# --------------------------------------------------------------------------- append round


def append_round(corpus: Path, n_files: int = 50, fraction: float = 0.01, seed: int = SEED) -> dict:
    """Append about `fraction` of the corpus's messages, spread over `n_files` transcript files.

    Files are chosen deterministically across all four formats; each gets the same number of
    new exchanges in its own format. Returns the number of messages priorlog should add.
    """
    manifest = json.loads((corpus / "manifest.json").read_text())
    rng = random.Random(seed + 1)
    t = Text(rng, Vocab(seed))
    pools = {
        "claude": sorted((corpus / "claude" / "projects").glob("*/*.jsonl")),
        "codex": sorted((corpus / "codex" / "sessions").rglob("*.jsonl")),
        "pi": sorted((corpus / "pi" / "sessions").rglob("*.jsonl")),
        "jsonl": sorted((corpus / "jsonl").glob("*.jsonl")),
    }
    share = {k: max(1, round(n_files * SHARES[k])) for k in pools}
    share["claude"] += n_files - sum(share.values())
    per_file = math.ceil(manifest["expected_total"] * fraction / n_files)
    exchanges = math.ceil(per_file / 2)
    ts = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
    added = 0
    chosen = []
    for kind, paths in pools.items():
        for path in rng.sample(paths, min(share[kind], len(paths))):
            chosen.append(str(path.relative_to(corpus)))
            lines: list[str] = []
            if kind == "claude":
                first = next(json.loads(x) for x in path.open() if '"cwd"' in x)
                w = ClaudeWriter(rng, t, path.stem, first["cwd"], first.get("gitBranch", "main"))
                for _ in range(exchanges):
                    chunk, k, ts = w.exchange(ts)
                    lines += chunk
                    added += k
            elif kind == "codex":
                for _ in range(exchanges):
                    chunk, k, ts = codex_exchange(rng, t, ts)
                    lines += chunk
                    added += k
            elif kind == "pi":
                prev = "x0"
                for _ in range(exchanges):
                    chunk, k, ts, prev = pi_exchange(rng, t, ts, prev)
                    lines += chunk
                    added += k
            else:
                last = json.loads(path.read_text().splitlines()[-1])
                for j in range(per_file):
                    lines.append(
                        jsonl_line(rng, t, last["conversation_id"], ts, "customer" if j % 2 == 0 else "bot")
                    )
                    ts += timedelta(seconds=30)
                    added += 1
            with path.open("a") as fh:
                fh.write("".join(lines))
    return {"files": len(chosen), "expected_new_messages": added, "paths": chosen}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("out", type=Path, help="corpus directory (created; must be empty)")
    p.add_argument("--messages", type=int, default=TARGET_MESSAGES, help="indexed messages to generate")
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--append", action="store_true", help="append one ~1%% growth round to an existing corpus")
    args = p.parse_args(argv)
    if args.append:
        print(json.dumps({k: v for k, v in append_round(args.out, seed=args.seed).items() if k != "paths"}))
        return 0
    if args.out.exists() and any(args.out.iterdir()):
        print(f"{args.out} is not empty; pick a new directory", file=sys.stderr)
        return 1
    m = generate(args.out, args.messages, args.seed)
    print(json.dumps(m, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
