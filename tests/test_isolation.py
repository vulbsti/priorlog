"""Installing and using priorlog changes nothing outside its own directories.

A throwaway HOME is seeded with what another local memory tool's install looks like (its
index, its systemd timer and service, its MCP registration in ~/.claude.json, its recall
skill) plus agent config files. Then the full CLI flow runs as a subprocess. Every file
outside priorlog's own config/data dirs (and the skill dir that `install-skill` is asked to write) must be
byte-for-byte unchanged, and nothing new may appear elsewhere.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from .conftest import FIXTURES

OTHER_TOOL_LOOKALIKE = {
    ".local/share/other-memory/index.sqlite": b"SQLite format 3\x00 pretend other-memory index",
    ".config/systemd/user/other-memory-sync.timer": b"[Timer]\nOnCalendar=*:0/15\n",
    ".config/systemd/user/other-memory-sync.service": b"[Service]\nExecStart=other-memory sync\n",
    ".claude/skills/recall/SKILL.md": b"---\nname: recall\n---\n",
    ".claude.json": json.dumps(
        {"mcpServers": {"other-memory": {"command": "other-memory", "args": ["mcp"]}}}
    ).encode(),
    ".claude/settings.json": b'{"cleanupPeriodDays": 36500}',
    ".codex/config.toml": b'model = "x"\n',
}


def snapshot(root: Path, skip: tuple[str, ...]) -> dict[str, str]:
    out = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not rel.startswith(skip):
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_full_install_flow_leaves_other_tools_untouched(tmp_path):
    home = tmp_path / "home"
    for rel, content in OTHER_TOOL_LOOKALIKE.items():
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_bytes(content)
    # real-looking transcript locations, so the default config finds data
    import shutil

    shutil.copytree(FIXTURES / "claude/projects", home / ".claude/projects")
    shutil.copytree(FIXTURES / "codex/sessions", home / ".codex/sessions")
    shutil.copytree(FIXTURES / "pi/sessions", home / ".pi/agent/sessions")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PRIORLOG_", "XDG_"))}
    env["HOME"] = str(home)

    own = (".config/priorlog/", ".local/share/priorlog/", ".claude/skills/priorlog/")
    before = snapshot(home, own)

    def run(*args):
        res = subprocess.run(
            [sys.executable, "-m", "priorlog", *args], env=env, capture_output=True, text=True
        )
        assert res.returncode == 0, res.stderr
        return res.stdout

    run("init")
    assert " 0 new messages" not in run("sync")  # it indexed the copied transcripts
    assert "token bucket" in run("search", "token", "bucket")
    run("status")
    run("install-skill", "--target", "claude")

    after = snapshot(home, own)
    assert after == before, "priorlog wrote outside its own directories"
    assert (home / ".config/priorlog/config.toml").exists()
    assert (home / ".local/share/priorlog/index.sqlite3").exists()
    assert oct((home / ".local/share/priorlog/index.sqlite3").stat().st_mode & 0o777) == "0o600"
    assert (home / ".claude/skills/priorlog/SKILL.md").read_text().startswith("---\nname: priorlog")
