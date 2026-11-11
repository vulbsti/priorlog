"""priorlog command line."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from importlib import resources
from pathlib import Path

from . import __version__, query, render
from .config import DEFAULT_TOML, Config, ConfigError, config_path
from .config import load as load_config
from .store import Store
from .sync import maybe_sync, sync

MCP_HINT = """\
Register the MCP server with your agent (priorlog never edits agent configs itself):
  claude mcp add --scope user priorlog -- priorlog mcp
  codex mcp add priorlog -- priorlog mcp
Add the agent skill (optional):  priorlog install-skill --target claude"""


def _load(args: argparse.Namespace) -> Config:
    return load_config(Path(args.config).expanduser() if args.config else None)


def _emit(args: argparse.Namespace, data: object, text: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(text)


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.config).expanduser() if args.config else config_path()
    if path.exists() and not args.force:
        print(f"config already exists: {path} (use --force to overwrite)")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_TOML)
        print(f"wrote {path}")
    cfg = load_config(path)
    for label, roots in (
        ("claude", cfg.claude_roots),
        ("claude desktop", cfg.claude_desktop_roots),
        ("codex", cfg.codex_roots),
        ("pi", cfg.pi_roots),
    ):
        for r in roots:
            print(f"  {label:<15} {r}  {'found' if r.expanduser().is_dir() else 'not found (skipped)'}")
    print(f"index will live at {cfg.db_path}")
    print("next: priorlog sync\n")
    print(MCP_HINT)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    report = sync(_load(args), harness=args.harness)
    _emit(
        args,
        {
            **report.__dict__,
            "unknown_types": dict(report.unknown_types),
            "per_harness": dict(report.per_harness),
        },
        report.line(),
    )
    return 0


def _with_store(args: argparse.Namespace, fn) -> int:
    cfg = _load(args)
    if not args.no_sync:
        maybe_sync(cfg)
    if not cfg.db_path.exists():
        print("index is empty: run `priorlog sync` first", file=sys.stderr)
        return 1
    with Store(cfg) as store:
        try:
            return fn(cfg, store) or 0
        except query.QueryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2


def cmd_search(args: argparse.Namespace) -> int:
    def run(cfg, store):
        res = query.search(
            store,
            " ".join(args.query),
            harness=args.harness,
            project=args.project,
            role=args.role,
            after=args.after,
            before=args.before,
            limit=args.limit,
        )
        _emit(args, res, render.search(res, cli=True))
        return 0 if res["hits"] else 3

    return _with_store(args, run)


def cmd_read(args: argparse.Namespace) -> int:
    def run(cfg, store):
        res = query.read(
            store, args.ref, page=args.page, context=args.context, source=args.source, config=cfg
        )
        _emit(args, res, render.read(res))

    return _with_store(args, run)


def cmd_sessions(args: argparse.Namespace) -> int:
    def run(cfg, store):
        rows = query.sessions(
            store, harness=args.harness, project=args.project, since=args.since, limit=args.limit
        )
        _emit(args, rows, render.sessions(rows))

    return _with_store(args, run)


def cmd_status(args: argparse.Namespace) -> int:
    args.no_sync = True

    def run(cfg, store):
        st = query.status(store)
        _emit(args, st, render.status(st))

    return _with_store(args, run)


def cmd_mcp(args: argparse.Namespace) -> int:
    from . import mcp_server

    mcp_server.main(_load(args))
    return 0


def cmd_install_skill(args: argparse.Namespace) -> int:
    targets = {
        "claude": Path.home() / ".claude/skills/priorlog",
        "codex": Path.home() / ".codex/skills/priorlog",
    }
    dest = targets.get(args.target, Path(args.target).expanduser()) / "SKILL.md"
    if dest.exists() and not args.force:
        print(f"{dest} exists (use --force to replace it)")
        return 1
    src = resources.files("priorlog").joinpath("skill/SKILL.md")
    if not src.is_file():  # running from a source checkout
        src = Path(__file__).resolve().parents[2] / "skills/priorlog/SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with resources.as_file(src) as p:
        shutil.copyfile(p, dest)
    print(f"installed skill: {dest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="priorlog", description="Search your past coding-agent sessions, with citations."
    )
    p.add_argument("--version", action="version", version=f"priorlog {__version__}")
    p.add_argument(
        "--config", help="config file (default: $PRIORLOG_CONFIG or ~/.config/priorlog/config.toml)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="write a default config and show what was found")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("sync", help="index new transcript lines (incremental)")
    s.add_argument("--harness", help="only this harness (claude, codex, pi, jsonl:<name>)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_sync)

    def common(s: argparse.ArgumentParser) -> None:
        s.add_argument("--json", action="store_true", help="machine-readable output")
        s.add_argument("--no-sync", action="store_true", help="skip the automatic incremental sync")

    s = sub.add_parser("search", help="full-text search; every hit has a citation")
    s.add_argument("query", nargs="+")
    s.add_argument("--harness")
    s.add_argument("--project", help="substring of the working directory or title")
    s.add_argument("--role", choices=["user", "assistant", "system"])
    s.add_argument("--after")
    s.add_argument("--before")
    s.add_argument("-n", "--limit", type=int, default=10)
    common(s)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("read", help="open a citation (<session>#<n>) or a whole session")
    s.add_argument("ref")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--context", type=int, default=4)
    s.add_argument("--source", action="store_true", help="also show the original transcript lines (redacted)")
    common(s)
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("sessions", help="list sessions, most recent first")
    s.add_argument("--harness")
    s.add_argument("--project")
    s.add_argument("--since")
    s.add_argument("-n", "--limit", type=int, default=20)
    common(s)
    s.set_defaults(fn=cmd_sessions)

    s = sub.add_parser("status", help="what is indexed, redaction counts")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status, no_sync=True)

    s = sub.add_parser("mcp", help="run the MCP server on stdio")
    s.set_defaults(fn=cmd_mcp)

    s = sub.add_parser("install-skill", help="copy the agent skill into ~/.claude or ~/.codex skills")
    s.add_argument("--target", default="claude", help="claude | codex | <directory>")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_install_skill)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
