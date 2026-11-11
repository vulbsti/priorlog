import shutil
from pathlib import Path

import pytest

from priorlog.config import Config, load

FIXTURES = Path(__file__).parent / "fixtures"


def write_config(root: Path, extra: str = "") -> Path:
    """A config that points every source at the copied fixtures under `root`."""
    cfg = root / "config.toml"
    cfg.write_text(f"""
[sources.claude]
roots = ["{root}/claude/projects"]
desktop_roots = ["{root}/claude/desktop"]
[sources.codex]
roots = ["{root}/codex/sessions"]
[sources.pi]
roots = ["{root}/pi/sessions"]
[[sources.jsonl]]
name = "supportbot"
paths = ["{root}/jsonl/*.jsonl"]
text = "body.text"
role = "speaker"
session = "conversation_id"
timestamp = "ts"
role_map = {{ customer = "user", bot = "assistant" }}
[index]
db_path = "{root}/data/index.sqlite3"
auto_sync_seconds = 0
{extra}
""")
    return cfg


@pytest.fixture
def data(tmp_path, monkeypatch) -> Path:
    """Fixture transcripts copied into a throwaway HOME (so nothing real is ever touched)."""
    root = tmp_path / "home"
    shutil.copytree(FIXTURES, root)
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("PRIORLOG_HOME", str(root / "data"))
    monkeypatch.delenv("PRIORLOG_CONFIG", raising=False)
    return root


@pytest.fixture
def cfg(data) -> Config:
    return load(write_config(data))
