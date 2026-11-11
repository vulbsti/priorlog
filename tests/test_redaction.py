"""Redaction and deny rules are enforced in the broker: secrets never reach the index or a client.

Secret-shaped strings are assembled at runtime so the repository itself contains none
(the gitleaks scan of the history stays at zero findings).
"""

import json
import random
import string

import pytest

from priorlog import query
from priorlog.config import Config, load
from priorlog.redact import Redactor
from priorlog.store import Store
from priorlog.sync import sync

from .conftest import write_config

J = "".join
_rng = random.Random(1234)  # fixed seed: same strings every run, none of them stored in the repo


def fake(n: int, alphabet: str = string.ascii_letters + string.digits) -> str:
    return J(_rng.choice(alphabet) for _ in range(n))


SECRETS = {
    "anthropic_key": J(["sk-", "ant-", "api03-", fake(40)]),
    "openai_key": J(["sk-", "proj-", fake(36)]),
    "github_token": J(["gh", "p_", fake(36)]),
    "aws_access_key": J(["AK", "IA", fake(16, string.ascii_uppercase + string.digits)]),
    "jwt": J(["ey", "J", fake(20), ".ey", "J", fake(30), ".", fake(43)]),
}
BEARER_VALUE = fake(32)
EMAIL = J(["alex.morgan", "@", "example.org"])
_KEY_BODY = fake(64, string.ascii_letters + string.digits + "+/")
URL_PASS = fake(12)
PRIVATE_KEY = J(
    ["-----BEGIN ", "OPENSSH PRIVATE KEY-----\n", _KEY_BODY, "\n-----END ", "OPENSSH PRIVATE KEY-----"]
)
ENV_VALUE = fake(14)


def test_redactor_masks_each_kind_and_leaves_ordinary_text():
    r = Redactor(Config())
    text = (
        f"key {SECRETS['anthropic_key']} and {SECRETS['openai_key']}; gh {SECRETS['github_token']}; "
        f"aws {SECRETS['aws_access_key']}; jwt {SECRETS['jwt']}\n"
        f"curl -H 'Authorization: Bearer {BEARER_VALUE}' https://api.example.org\n"
        f"mail {EMAIL} about it\n{PRIVATE_KEY}\nDB_PASSWORD={ENV_VALUE}\n"
        "git clone https://deploy:" + URL_PASS + "@git.example.org/repo.git\n"
        # must survive: commit hashes, token counts, prose about tokens
        "commit 3f786850e387550fdab836ed7e6dc881de23001b set max_tokens: 100000 and tokenizer = 'trigram'"
    )
    res = r.redact(text)
    for kind, value in SECRETS.items():
        assert value not in res.text, kind
        assert f"[REDACTED:{kind}]" in res.text
    assert BEARER_VALUE not in res.text and "Bearer [REDACTED:bearer_token]" in res.text
    assert EMAIL not in res.text and "[REDACTED:email]" in res.text
    assert "BEGIN OPENSSH" not in res.text and "[REDACTED:private_key]" in res.text
    assert ENV_VALUE not in res.text and "DB_PASSWORD=[REDACTED:secret_assignment]" in res.text
    assert URL_PASS not in res.text and "https://deploy:[REDACTED:url_credentials]@git" in res.text
    assert "3f786850e387550fdab836ed7e6dc881de23001b" in res.text
    assert "max_tokens: 100000" in res.text and "tokenizer = 'trigram'" in res.text
    assert res.counts["email"] == 1 and sum(res.counts.values()) >= 10
    assert r.redact(res.text).text == res.text  # idempotent: placeholders are left alone


# One sample per token rule that SECRETS doesn't already cover.
MORE_TOKENS = {
    "gitlab_token": J(["gl", "pat-", fake(20)]),
    "google_api_key": J(["AI", "za", fake(35)]),
    "slack_token": J(["xo", "xb-", fake(24)]),
    "stripe_key": J(["sk", "_live_", fake(24)]),
    "huggingface_token": J(["hf", "_", fake(34)]),
}


@pytest.mark.parametrize("kind", [*SECRETS, *MORE_TOKENS])
def test_token_glued_to_an_underscore_is_still_masked_as_its_own_kind(kind):
    # e.g. a tool name like mcp__<token>: \b sees no boundary between "_" and the token
    value = {**SECRETS, **MORE_TOKENS}[kind]
    out = Redactor(Config()).redact("tool mcp__" + value + " done").text
    assert value not in out and f"[REDACTED:{kind}]" in out, out


def _plant(data, lines):
    path = data / "claude/projects/-work-leak/dddddddd-4444-4444-8444-000000000004.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return path


def test_secrets_never_reach_the_index_search_or_source_view(data):
    leak = (
        f"here is my key {SECRETS['anthropic_key']}, the token Bearer {BEARER_VALUE}, "
        f"contact {EMAIL}\n{PRIVATE_KEY}"
    )
    _plant(
        data,
        [
            {
                "type": "user",
                "sessionId": "dddddddd-4444-4444-8444-000000000004",
                "timestamp": "2026-10-09T10:00:00Z",
                "cwd": "/work/leak",
                "message": {"role": "user", "content": "deploy failed: " + leak},
            },
            {"type": "custom-title", "customTitle": f"debug with {EMAIL}"},
        ],
    )
    cfg = load(write_config(data))
    sync(cfg)
    raw = cfg.db_path.read_bytes() + (
        cfg.db_path.with_name(cfg.db_path.name + "-wal").read_bytes()
        if cfg.db_path.with_name(cfg.db_path.name + "-wal").exists()
        else b""
    )
    for value in (
        SECRETS["anthropic_key"],
        BEARER_VALUE,
        EMAIL,
        _KEY_BODY,
    ):
        assert value.encode() not in raw
    with Store(cfg) as s:
        assert query.search(s, SECRETS["anthropic_key"][:20])["hits"] == []
        hit = query.search(s, "deploy failed")["hits"][0]
        assert "[REDACTED:anthropic_key]" in hit["snippet"]
        assert (
            s.conn.execute("SELECT title FROM sessions WHERE id LIKE 'claude:dddd%'").fetchone()[0]
            == "debug with [REDACTED:email]"
        )
        src = query.read(s, hit["cite"], source=True, config=cfg)["source_lines"]
        assert (
            src
            and SECRETS["anthropic_key"] not in src[0]["text"]
            and "[REDACTED:anthropic_key]" in src[0]["text"]
        )
        stats = query.status(s)["redactions"]
        assert stats["anthropic_key"] >= 1 and stats["email"] >= 2 and stats["private_key"] >= 1


def test_deny_rules_drop_messages_and_files(data):
    _plant(
        data,
        [
            {
                "type": "user",
                "sessionId": "dddddddd-4444-4444-8444-000000000004",
                "cwd": "/work/leak",
                "message": {"role": "user", "content": "PRIVATE: salary numbers for the team"},
            }
        ],
    )
    # transcripts inside credential directories under a configured root are never opened
    (data / "codex/sessions/.ssh").mkdir()
    (data / "codex/sessions/.ssh/stolen.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": "x"}}) + "\n"
    )
    (data / "pi/sessions/.env").mkdir()
    (data / "pi/sessions/.env/x.jsonl").write_text(
        json.dumps({"type": "message", "message": {"role": "user", "content": "should never be read"}}) + "\n"
    )
    cfg = load(
        write_config(data, '[policy]\ndeny_content = ["^PRIVATE:"]\ndeny_paths = ["*/-work-demo-app/bbbb*"]')
    )
    report = sync(cfg)
    assert report.files_denied == 3  # .ssh/, .env/ and the user's own deny_paths rule
    with Store(cfg) as s:
        assert query.search(s, "salary numbers")["hits"] == []
        assert query.search(s, "never be read")["hits"] == []
        assert query.search(s, "Retry-After")["hits"] == []  # the denied fork file
        assert query.status(s)["dropped_by_deny_content"] == 1
        # a dropped message must not leak through the session title either
        titles = [r[0] or "" for r in s.conn.execute("SELECT title FROM sessions")]
        assert not any("salary" in t for t in titles)


def test_source_view_rechecks_policy(data):
    cfg = load(write_config(data))
    sync(cfg)
    with Store(cfg) as s:
        cite = query.search(s, "token bucket", harness="claude")["hits"][0]["cite"]
    stricter = load(write_config(data, '[policy]\ndeny_paths = ["*/-work-demo-app/*"]'))
    with Store(stricter) as s, pytest.raises(query.QueryError, match="not readable"):
        query.read(s, cite, source=True, config=stricter)


def test_bad_config_values_are_reported_not_crashed(data):
    import subprocess
    import sys

    cfg = write_config(data, '[redaction]\nemails = "no"')
    res = subprocess.run(
        [sys.executable, "-m", "priorlog", "--config", str(cfg), "status"], capture_output=True, text=True
    )
    assert res.returncode == 2 and "config error: redaction.emails must be true or false" in res.stderr


def test_deny_content_also_covers_titles_and_desktop_metadata(data):
    """A denied text can't surface as a session title, from any title source, and desktop
    metadata can't create a session for a transcript that deny_paths blocked."""
    fork = data / "claude/projects/-work-demo-app/bbbbbbbb-2222-4222-8222-000000000002.jsonl"
    with open(fork, "a") as f:
        f.write(json.dumps({"type": "ai-title", "aiTitle": "PRIVATE: payroll review"}) + "\n")
    desktop = next((data / "claude/desktop").rglob("local_*.json"))
    meta = json.loads(desktop.read_text())
    meta["title"] = "PRIVATE: board notes"
    desktop.write_text(json.dumps(meta))
    cfg = load(write_config(data, '[policy]\ndeny_content = ["^PRIVATE:"]'))
    sync(cfg)
    with Store(cfg) as s:
        titles = {r[0]: r[1] for r in s.conn.execute("SELECT id, title FROM sessions")}
        assert not any("PRIVATE" in (t or "") for t in titles.values())
        # the lower-ranked, allowed title survives instead
        assert titles["claude:aaaaaaaa-1111-4111-8111-000000000001"] == "Rate limiter design"

    path = write_config(data, '[policy]\ndeny_paths = ["*/aaaaaaaa-1111-4111-8111-000000000001.jsonl"]')
    path.write_text(path.read_text().replace("/data/index.sqlite3", "/data2/index.sqlite3"))
    blocked = load(path)
    sync(blocked)
    with Store(blocked) as s:
        with pytest.raises(query.QueryError, match="no session"):
            query.read(s, "local_0f0f0f0f-aaaa-4bbb-8ccc-000000000001")
        # the denied session's subagent transcripts are denied with it
        assert not s.conn.execute("SELECT 1 FROM sessions WHERE id = 'claude:agent-r1'").fetchone()


def test_source_view_withholds_denied_lines_inside_a_cited_range(data):
    """Non-message lines inside an assistant turn's line range are shown by `read --source`;
    a deny rule written against text (`^PRIVATE:`) must catch them inside the raw JSON too."""
    sid = "eeeeeeee-5555-4555-8555-000000000005"
    _plant(data, [])  # creates the -work-leak project dir
    path = data / f"claude/projects/-work-leak/{sid}.jsonl"
    secret = "PRIVATE: the codeword is " + fake(10)

    def assistant(text):
        return {
            "type": "assistant",
            "sessionId": sid,
            "timestamp": "2026-10-09T10:00:01Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }

    path.write_text(
        "".join(
            json.dumps(x) + "\n"
            for x in [
                {
                    "type": "user",
                    "sessionId": sid,
                    "cwd": "/work/leak",
                    "message": {"role": "user", "content": "start"},
                },
                assistant("thinking about the migration plan"),
                {"type": "queue-operation", "operation": "enqueue", "content": "note\n\n" + secret},
                {"type": "last-prompt", "lastPrompt": secret},
                assistant("migration plan is ready"),
                {"type": "user", "sessionId": sid, "message": {"role": "user", "content": secret}},
            ]
        )
    )
    cfg = load(write_config(data, '[policy]\ndeny_content = ["^PRIVATE:"]'))
    sync(cfg)
    with Store(cfg) as s:
        hit = query.search(s, "migration plan")["hits"][0]
        assert hit["locator"].endswith(":L2-L5")
        lines = query.read(s, hit["cite"], source=True, config=cfg)["source_lines"]
        shown = "\n".join(x["text"] for x in lines)
        assert secret.split()[-1] not in shown
        assert shown.count("[line withheld: matches a deny_content rule]") == 2


def test_session_metadata_is_redacted_and_carry_holds_no_raw_text(data):
    meta = (
        data
        / "codex/sessions/2026/10/02/rollout-2026-10-02T10-00-00-cccccccc-3333-4333-8333-000000000003.jsonl"
    )
    lines = meta.read_text().splitlines()
    first = json.loads(lines[0])
    first["payload"]["cwd"] = "/work/acme/" + EMAIL
    first["payload"]["git"]["branch"] = "PRIVATE-hiring-plan"
    meta.write_text("\n".join([json.dumps(first), *lines[1:]]) + "\n")
    cfg = load(write_config(data, '[policy]\ndeny_content = ["PRIVATE"]'))
    sync(cfg)
    with Store(cfg) as s:
        cwd, branch = s.conn.execute(
            "SELECT cwd, branch FROM sessions WHERE id = 'codex:cccccccc-3333-4333-8333-000000000003'"
        ).fetchone()
        assert cwd == "/work/acme/[REDACTED:email]" and branch is None
        carries = " ".join(r[0] or "" for r in s.conn.execute("SELECT carry FROM files"))
        assert EMAIL not in carries and "/work/acme" not in carries


def test_a_missing_sources_section_turns_that_harness_off(data):
    cfg_path = write_config(data)
    text = cfg_path.read_text()
    start, end = text.index("[sources.codex]"), text.index("[sources.pi]")
    cfg_path.write_text(text[:start] + text[end:])
    cfg = load(cfg_path)
    assert cfg.codex_roots == ()
    sync(cfg)
    with Store(cfg) as s:
        assert "codex" not in query.status(s)["harnesses"]


def test_transcript_ids_timestamps_and_blocks_cannot_carry_content(data):
    """Audit round 3: mapped ids and timestamps, later content blocks, full-length titles,
    line-type names and JSON-escaped raw lines all go through the broker rules."""
    key = SECRETS["anthropic_key"]
    (data / "jsonl/leaky.jsonl").write_text(
        json.dumps(
            {"conversation_id": EMAIL, "speaker": "customer", "ts": key, "body": {"text": "refund status"}}
        )
        + "\n"
        + json.dumps(
            {"conversation_id": "PRIVATE: c1", "speaker": "customer", "body": {"text": "invoice copy"}}
        )
        + "\n"
    )
    sid = "ffffffff-6666-4666-8666-000000000006"
    _plant(data, [])
    escaped_email = EMAIL.replace("@", "\\u0040")
    (data / f"claude/projects/-work-leak/{sid}.jsonl").write_text(
        "".join(
            json.dumps(x) + "\n"
            for x in [
                {
                    "type": "user",
                    "sessionId": sid,
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "<ide_opened_file>notes.md</ide_opened_file>"},
                            {"type": "text", "text": "PRIVATE: falcon merger terms"},
                        ],
                    },
                },
                {
                    "type": "user",
                    "sessionId": sid,
                    "cwd": "/work/secret-client/web",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "<ide_selection>quokka-selection</ide_selection>"},
                            {"type": "text", "text": "ordinary question"},
                        ],
                    },
                },
                {
                    "type": "assistant",
                    "sessionId": sid,
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "Here is the summary."},
                            {"type": "text", "text": "PRIVATE: board vote count"},
                        ],
                    },
                },
                {"type": "summary", "summary": "line one\nSECRETLINE: summary zebra"},
                {"type": "custom-title", "customTitle": "titleneedle " + "y" * 90 + " TAILMARK"},
                {"type": "privatexyz"},
                {"type": key},
            ]
        )
        + '{"type": "user", "sessionId": "'
        + sid
        + '", "message": {"role": "user", "content": "mail '
        + escaped_email
        + ' please"}}\n'
    )
    # Codex and Pi session ids and a desktop id that hold content, and a cwd a rule denies
    codex = (
        data
        / "codex/sessions/2026/10/02/rollout-2026-10-02T10-00-00-cccccccc-3333-4333-8333-000000000003.jsonl"
    )
    lines = codex.read_text().splitlines()
    meta = json.loads(lines[0])
    meta["payload"]["id"] = "codex-" + EMAIL
    meta["payload"]["cwd"] = "/work/acme-app"
    codex.write_text("\n".join([json.dumps(meta), *lines[1:]]) + "\n")
    pi = next((data / "pi/sessions").rglob("*.jsonl"))
    lines = pi.read_text().splitlines()
    first = json.loads(lines[0])
    first["id"] = key
    pi.write_text("\n".join([json.dumps(first), *lines[1:]]) + "\n")
    desktop = next((data / "claude/desktop").rglob("local_*.json"))
    dmeta = json.loads(desktop.read_text())
    dmeta["sessionId"] = "local_" + EMAIL
    desktop.write_text(json.dumps(dmeta))
    # a Claude transcript whose file stem (= session id) is token-shaped, plus its desktop file
    stem = SECRETS["github_token"]
    (data / f"claude/projects/-work-leak/{stem}.jsonl").write_text(
        json.dumps({"type": "user", "sessionId": stem, "message": {"role": "user", "content": "stem test"}})
        + "\n"
    )
    sub = data / f"claude/projects/-work-leak/{stem}/subagents/agent-s1.jsonl"
    sub.parent.mkdir(parents=True)
    sub.write_text(
        json.dumps({"type": "user", "sessionId": stem, "message": {"role": "user", "content": "sub test"}})
        + "\n"
    )
    (desktop.parent / "local_stem.json").write_text(
        json.dumps(
            {"sessionId": "local_stem", "cliSessionId": stem, "cwd": "/work/stem-app", "title": "stem"}
        )
    )
    # `^PRIVATE:` (no (?m)) only matches the private blocks above because each block is tested
    rules = '[policy]\ndeny_content = ["^PRIVATE:", "(?m)^SECRETLINE:", "^/work/secret-client", "(?i)privatexyz", "TAILMARK"]'
    cfg = load(write_config(data, rules))
    sync(cfg)
    raw = cfg.db_path.read_bytes()
    wal = cfg.db_path.with_name(cfg.db_path.name + "-wal")
    raw += wal.read_bytes() if wal.exists() else b""
    for leaked in (
        EMAIL,
        key,
        "falcon merger",
        "board vote",
        "summary zebra",
        "PRIVATE",
        "quokka",
        "secret-client",
        "titleneedle",
        "privatexyz",
    ):
        assert leaked.encode() not in raw, leaked
    with Store(cfg) as s:
        hit = query.search(s, "refund status")["hits"][0]
        assert hit["session"].startswith("jsonl:supportbot:h-") and hit["timestamp"] is None
        assert query.search(s, "ordinary question")["hits"]
        ids = [r[0] for r in s.conn.execute("SELECT id FROM sessions WHERE harness IN ('codex', 'pi')")]
        assert sorted(i.split(":")[1][:2] for i in ids) == ["h-", "h-"]
        carries = " ".join(r[0] or "" for r in s.conn.execute("SELECT carry FROM files"))
        assert "h-" in carries
        stem_row = s.conn.execute(
            "SELECT id, native_id, resume_cmd FROM sessions WHERE desktop_id = 'local_stem'"
        ).fetchone()
        assert stem_row[0].startswith("claude:h-") and stem_row[1].startswith("h-") and stem_row[2] is None
        # the subagent link points at the hashed parent id, never the token-shaped stem
        links = [
            tuple(r)
            for r in s.conn.execute("SELECT from_id, to_id FROM links WHERE to_id = 'claude:agent-s1'")
        ]
        assert links == [(stem_row[0], "claude:agent-s1")], links
        assert not any(stem in " ".join(r) for r in s.conn.execute("SELECT from_id, to_id FROM links"))
        # a hashed id can't be resumed, and the command would embed the original id
        assert s.conn.execute("SELECT resume_cmd FROM sessions WHERE harness = 'codex'").fetchone()[0] is None
        assert query.status(s)["unknown_types"] == {"claude:other": 2, "claude:some-future-type": 1}
        cite = query.search(s, "please")["hits"][0]["cite"]
        shown = query.read(s, cite, source=True, config=cfg)["source_lines"][0]["text"]
        assert "[REDACTED:email]" in shown and "alex.morgan" not in shown
