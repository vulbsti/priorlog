"""Each adapter against its synthetic fixture: what is kept, what is dropped, and where it came from."""

from priorlog.store import Store
from priorlog.sync import sync

A = "claude:aaaaaaaa-1111-4111-8111-000000000001"
B = "claude:bbbbbbbb-2222-4222-8222-000000000002"


def messages(cfg, sid):
    with Store(cfg) as s:
        return [
            dict(r)
            for r in s.conn.execute(
                "SELECT role, text, ts, line_start, line_end FROM messages WHERE session_id = ? ORDER BY seq",
                (sid,),
            )
        ]


def session(cfg, sid):
    with Store(cfg) as s:
        return dict(s.conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone())


def test_claude_transcript_subagent_fork_and_desktop(cfg):
    report = sync(cfg)
    assert report.files_denied == 0
    msgs = messages(cfg, A)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    # system reminder stripped; the whole tool-using turn is one message with merged markers
    assert msgs[0]["text"] == "The API is getting hammered. Design a rate limiter for /v1/orders."
    assert msgs[1]["text"].startswith(
        "Let me look at the current middleware first.\n\n[tool: Bash x2]\n\nDecision: use a token bucket"
    )
    assert (msgs[1]["line_start"], msgs[1]["line_end"]) == (3, 8)  # first and last assistant line of the turn
    assert msgs[2]["text"] == "/review middleware/ratelimit.py"

    s = session(cfg, A)
    assert s["title"] == "Orders API rate limiting"  # desktop title outranks the custom title
    assert s["desktop_id"] == "local_0f0f0f0f-aaaa-4bbb-8ccc-000000000001"
    assert s["cwd"] == "/work/demo-app" and s["branch"] == "main"
    assert "claude --resume aaaaaaaa-1111-4111-8111-000000000001" in s["resume_cmd"]

    # subagent: own session, titled from its meta file, linked to the parent
    sub = session(cfg, "claude:agent-r1")
    assert sub["parent_id"] == A and sub["title"] == "Benchmark limiter algorithms"

    # fork: the copied history of A is not stored twice
    fork = messages(cfg, B)
    assert [m["text"][:9] for m in fork] == ["Follow-up", "Added Ret"]

    with Store(cfg) as st:
        links = set(st.conn.execute("SELECT from_id, to_id, kind FROM links").fetchall())
        assert (A, "claude:agent-r1", "subagent") in {tuple(x) for x in links}
        assert (A, B, "fork") in {tuple(x) for x in links}
        # cloud / Remote Control ids in the desktop file are ignored: local sources only
        assert not st.conn.execute("SELECT 1 FROM sessions WHERE id LIKE '%cse_%'").fetchone()
        assert "some-future-type" in (st.get_meta("unknown_types") or "")
        assert st.conn.execute("SELECT value FROM stats WHERE key = 'malformed_lines'").fetchone()[0] == 1


def test_codex_rollout(cfg):
    sync(cfg)
    sid = "codex:cccccccc-3333-4333-8333-000000000003"
    msgs = messages(cfg, sid)
    # developer instructions and <environment_context> dropped; event_msg duplicates ignored
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["text"] == "Migrate CI from Travis to GitHub Actions and keep the Postgres service."
    assert msgs[1]["text"].startswith("[tool: shell]\n\nWrote .github/workflows/ci.yml")
    assert (msgs[1]["line_start"], msgs[1]["line_end"]) == (7, 9)
    s = session(cfg, sid)
    assert (s["cwd"], s["branch"]) == ("/work/demo-app", "ci-migration")


def test_pi_session(cfg):
    sync(cfg)
    sid = "pi:019f0000-0000-7000-8000-000000000004"
    msgs = messages(cfg, sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["text"] == "test_payment_retry is flaky on CI, find out why"
    # thinking and the tool result are not indexed; the tool call is a marker
    assert msgs[1]["text"] == (
        "[tool: bash]\n\nRoot cause: the retry backoff uses time.sleep with real time, "
        "so the test races the 2 s timeout. Fixed by injecting a fake clock."
    )
    assert "hidden" not in msgs[1]["text"] and "1 failed" not in msgs[1]["text"]
    assert session(cfg, sid)["cwd"] == "/work/demo-api"


def test_generic_jsonl_mapping(cfg):
    sync(cfg)
    msgs = messages(cfg, "jsonl:supportbot:conv-7")
    assert [(m["role"], m["line_start"]) for m in msgs] == [("user", 1), ("assistant", 2)]
    assert msgs[1]["text"].startswith("Exports over 50k rows")
    assert msgs[1]["ts"] == "2026-10-05T12:00:03Z"
    # a line whose mapped text field is missing is skipped, not stored as "null"
    assert len(messages(cfg, "jsonl:supportbot:conv-8")) == 1
