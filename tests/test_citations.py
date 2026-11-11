"""Every search hit carries a citation that `read` can open, down to the source lines."""

import json
import os

from priorlog import query
from priorlog.store import Store
from priorlog.sync import sync


def test_every_hit_has_a_citation_that_read_opens(cfg, data):
    sync(cfg)
    with Store(cfg) as s:
        res = query.search(s, "token bucket")
        assert res["hits"]
        for hit in res["hits"]:
            assert hit["cite"].startswith(hit["session"] + "#")
            assert hit["harness"] == hit["session"].split(":")[0]
            assert hit["timestamp"]
            path, _, lines = hit["locator"].rpartition(":")
            assert lines.startswith("L")
            opened = query.read(s, hit["cite"], source=True, config=cfg)
            cited = [m for m in opened["messages_shown"] if m["cited"]]
            assert len(cited) == 1 and cited[0]["locator"] == hit["locator"]
            # the locator points at real lines of the real file
            first, last = (int(x.lstrip("L")) for x in (lines.split("-") * 2)[:2])
            real = os.path.expanduser(path)
            with open(real) as fh:
                raw = fh.read().splitlines()[first - 1 : last]
            assert [x["line"] for x in opened["source_lines"]] == list(range(first, last + 1))
            assert json.loads(raw[-1])["type"] in ("assistant", "user")


def test_search_across_harnesses_with_filters(cfg):
    sync(cfg)
    with Store(cfg) as s:

        def harnesses(q, **kw):
            return {h["harness"] for h in query.search(s, q, **kw)["hits"]}

        # totals count every match, not just the returned hits
        res = query.search(s, "bucket", limit=1)
        direct = s.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT m.session_id) FROM fts JOIN messages m ON m.id = fts.rowid "
            "WHERE fts MATCH 'bucket'"
        ).fetchone()
        assert (res["total_matches"], res["sessions_matched"]) == tuple(direct) and len(res["hits"]) == 1
        assert direct[0] > 1
        assert harnesses("Postgres") == {"codex"}
        assert harnesses("fake clock") == {"pi"}
        assert harnesses("background job") == {"jsonl:supportbot"}
        assert harnesses("token bucket", harness="codex") == set()
        assert harnesses("bucket", project="demo-app") == {"claude"}
        assert query.search(s, "bucket", before="2026-10-02")["hits"]
        assert not query.search(s, "Retry-After", before="2026-10-02")["hits"]
        # short words (under 3 characters) still work through the substring fallback
        assert query.search(s, "CI is")["hits"]


def test_read_resolves_short_ids_and_pages(cfg):
    sync(cfg)
    with Store(cfg) as s:
        by_prefix = query.read(s, "aaaaaaaa-1111")
        assert by_prefix["session"] == "claude:aaaaaaaa-1111-4111-8111-000000000001"
        assert by_prefix["page"] == 1 and by_prefix["pages"] == 1
        assert query.read(s, "local_0f0f0f0f-aaaa-4bbb-8ccc-000000000001")["session"] == by_prefix["session"]
        assert {x["kind"] for x in by_prefix["links"]} == {"subagent", "fork"}
