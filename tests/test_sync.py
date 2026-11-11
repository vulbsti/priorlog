"""Incremental sync: unchanged files cost nothing, growth is read once, rewrites are re-indexed."""

import json
import os

from priorlog.store import Store
from priorlog.sync import sync

A_FILE = "claude/projects/-work-demo-app/aaaaaaaa-1111-4111-8111-000000000001.jsonl"
A = "claude:aaaaaaaa-1111-4111-8111-000000000001"


def texts(cfg, sid=A):
    with Store(cfg) as s:
        return [
            r[0]
            for r in s.conn.execute("SELECT text FROM messages WHERE session_id = ? ORDER BY seq", (sid,))
        ]


def append(path, *rows):
    with open(path, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def assistant(text, ts="2026-10-01T10:00:00Z"):
    return {
        "type": "assistant",
        "sessionId": A.split(":")[1],
        "timestamp": ts,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def test_second_sync_is_a_no_op(cfg):
    first = sync(cfg)
    assert first.new_messages > 0
    again = sync(cfg)
    assert (again.files_changed, again.new_messages) == (0, 0)


def test_appended_lines_and_growing_turn(cfg, data):
    sync(cfg)
    before = texts(cfg)
    path = data / A_FILE
    # a new user message and the start of an assistant turn
    append(
        path,
        {
            "type": "user",
            "sessionId": A.split(":")[1],
            "timestamp": "2026-10-01T10:00:00Z",
            "message": {"role": "user", "content": "Should the limit be per tenant too?"},
        },
        assistant("Yes: add a second bucket keyed by tenant id."),
    )
    r = sync(cfg)
    assert r.new_messages == 2
    assert texts(cfg)[: len(before)] == before
    # the same assistant turn keeps growing on the next lines: it is replaced, not duplicated
    append(path, assistant("Tenant bucket: capacity 200, refill 50/s."))
    sync(cfg)
    after = texts(cfg)
    assert (
        after[-1]
        == "Yes: add a second bucket keyed by tenant id.\n\nTenant bucket: capacity 200, refill 50/s."
    )
    assert len(after) == len(before) + 2
    with Store(cfg) as s:  # the FTS index (bulk-built on the first sync) still matches the table
        s.conn.execute("INSERT INTO fts(fts, rank) VALUES ('integrity-check', 1)")
        assert s.conn.execute("SELECT COUNT(*) FROM fts WHERE fts MATCH 'tenant'").fetchone()[0] == 2


def test_partial_last_line_waits_for_newline(cfg, data):
    sync(cfg)
    path = data / A_FILE
    with open(path, "a") as f:
        f.write(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": A.split(":")[1],
                    "message": {"role": "user", "content": "half written"},
                }
            )
        )  # no newline yet
    assert sync(cfg).new_messages == 0
    with open(path, "a") as f:
        f.write("\n")
    assert sync(cfg).new_messages == 1
    assert texts(cfg)[-1] == "half written"


def test_rewritten_file_is_reindexed(cfg, data):
    sync(cfg)
    path = data / A_FILE
    replacement = path.with_suffix(".new")
    replacement.write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": A.split(":")[1],
                "message": {"role": "user", "content": "compacted history"},
            }
        )
        + "\n"
    )
    os.replace(replacement, path)  # new inode, smaller file
    sync(cfg)
    assert texts(cfg) == ["compacted history"]
