"""The real MCP server over stdio, driven by the real MCP client: search, then open the cite."""

import os
import re
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from priorlog.render import LABEL

from .conftest import write_config


async def _session(cfg_path, env):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "priorlog", "--config", str(cfg_path), "mcp"], env=env
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as client:
        await client.initialize()
        listed = (await client.list_tools()).tools
        assert all(t.annotations and t.annotations.read_only_hint for t in listed)
        tools = {t.name for t in listed}

        async def call(name, **args):
            res = await client.call_tool(name, args)
            assert not res.is_error
            return "".join(c.text for c in res.content)

        found = await call("search", query="rate limiter")
        cite = re.search(r"cite: (\S+)", found).group(1)
        return tools, found, await call("read", ref=cite, source=True), await call("status")


def test_mcp_search_then_read_citation(data):
    cfg_path = write_config(data).as_posix()
    # auto-sync on: the first tool call indexes the fixtures itself
    path = Path(cfg_path)
    path.write_text(path.read_text().replace("auto_sync_seconds = 0", "auto_sync_seconds = 60"))
    env = {**os.environ, "HOME": str(data)}
    tools, found, opened, status = anyio.run(_session, cfg_path, env)
    assert tools == {"search", "read", "sessions", "status"}
    for out in (found, opened, status):
        assert out.startswith(LABEL)
    assert "cite: claude:aaaaaaaa-1111-4111-8111-000000000001#" in found
    assert "source: ~/claude/projects/-work-demo-app/aaaaaaaa-1111-4111-8111-000000000001.jsonl:L" in found
    assert "▶ [" in opened and "token bucket per API key" in opened
    assert "Original transcript lines (redacted):" in opened
    assert "claude" in status and "codex" in status and "pi" in status
