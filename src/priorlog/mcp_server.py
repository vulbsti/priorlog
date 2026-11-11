"""MCP server (stdio): search, read, sessions and status over the priorlog index.

Read-only except for the incremental sync that search/read run when the index is older than
`auto_sync_seconds`. Every result starts with a label saying it is retrieved context.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.types import ToolAnnotations

from . import query as q
from . import render
from .config import Config
from .config import load as load_config
from .store import Store
from .sync import maybe_sync

try:  # mcp >= 2 names the high-level server MCPServer
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as _Server

server = _Server("priorlog")
_config: Config | None = None


def _cfg() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


# Read-only, idempotent, local: lets clients such as `codex exec` call the tools without an
# approval prompt. (The auto-sync only appends to priorlog's own index.)
_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


def _tool(fn: Callable[..., str]) -> Callable[..., str]:
    try:
        return server.tool(structured_output=False, annotations=_ANNOTATIONS)(fn)
    except TypeError:  # pragma: no cover - SDKs without structured_output
        return server.tool()(fn)


def _run(fn: Callable[[Store], str]) -> str:
    cfg = _cfg()
    try:
        maybe_sync(cfg)
    except Exception as exc:  # noqa: BLE001 - report, but still answer from the existing index
        note = f"(auto-sync failed: {type(exc).__name__}: {exc}; answering from the existing index)\n\n"
    else:
        note = ""
    if not cfg.db_path.exists():
        return render.labelled(note + "The index is empty. Run `priorlog sync` first.")
    with Store(cfg) as store:
        try:
            return render.labelled(note + fn(store))
        except q.QueryError as exc:
            return render.labelled(note + f"Error: {exc}")


@_tool
def search(
    query: str,
    harness: str | None = None,
    project: str | None = None,
    role: str | None = None,
    after: str | None = None,
    before: str | None = None,
    limit: int = 10,
) -> str:
    """Full-text search over past coding-agent sessions (Claude Code, Codex CLI, Pi and any
    configured JSONL logs) on this machine. Use it when the user refers to earlier work ("last
    time", "what did we decide about X", "how did we fix Y") or before asking them for context
    they probably gave in another session.

    Every word must appear (case-insensitive substring; "deploy" also finds "deployment").
    Use 2-4 distinctive words such as names, file names or error text; "quote phrases".
    Each hit has a `cite` (pass it to `read`) and a `source` locator (file and line range).

    Args:
        query: words to find.
        harness: claude | codex | pi | jsonl:<name>.
        project: substring of the session's working directory or title.
        role: user | assistant | system.
        after: ISO date/time; only messages at or after it.
        before: ISO date/time; only messages before it.
        limit: maximum hits (default 10, max 100).
    """
    return _run(
        lambda s: render.search(
            q.search(
                s, query, harness=harness, project=project, role=role, after=after, before=before, limit=limit
            )
        )
    )


@_tool
def read(ref: str, page: int = 1, context: int = 4, source: bool = False) -> str:
    """Open a citation or a whole session.

    `ref` is a `cite` from search ("claude:<id>#12": shows that message with `context`
    messages either side, the cited one marked ▶) or a session id (pages through the whole
    session, ~6k tokens per page). With source=true and a cite, also returns the original
    transcript lines the message came from, re-read from disk and redacted.

    Args:
        ref: cite ("<session>#<n>"), session id, or a native session id / prefix.
        page: page number when reading a whole session.
        context: messages to show either side of a cited message (default 4).
        source: include the original transcript lines for a cite.
    """
    return _run(
        lambda s: render.read(q.read(s, ref, page=page, context=context, source=source, config=_cfg()))
    )


@_tool
def sessions(
    harness: str | None = None, project: str | None = None, since: str | None = None, limit: int = 20
) -> str:
    """List past sessions, most recent first (title, id, harness, dates, message count).
    Use it to browse recent work when there are no good search words.

    Args:
        harness: claude | codex | pi | jsonl:<name>.
        project: substring of the working directory or title.
        since: ISO date/time; only sessions active at or after it.
        limit: maximum sessions (default 20).
    """
    return _run(
        lambda s: render.sessions(q.sessions(s, harness=harness, project=project, since=since, limit=limit))
    )


@_tool
def status() -> str:
    """What is indexed: sessions and messages per harness, last sync time, and how many
    secrets were redacted (counts per kind only)."""
    return _run(lambda s: render.status(q.status(s)))


def main(config: Config | None = None) -> None:
    global _config
    if config is not None:
        _config = config
    server.run("stdio")


def tool_names() -> list[str]:
    return ["search", "read", "sessions", "status"]


__all__: list[Any] = ["main", "server", "tool_names"]
