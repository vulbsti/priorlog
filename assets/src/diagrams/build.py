"""Build the README diagrams, one light and one dark variant of each.

    python3 assets/src/diagrams/build.py        # writes assets/architecture-*.svg, citation-anatomy-*.svg

Hand-laid-out SVG (real <text>, no fonts embedded). The citation example is the real search hit
in assets/src/demo/capture.json, which assets/src/demo/record.py extracts from the recorded demo
session, so the diagram shows what the CLI actually prints.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parents[1]

SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif'
MONO = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace'

THEMES = {
    "light": {
        "fg": "#1f2328",
        "muted": "#59636e",
        "faint": "#818b98",
        "line": "#d1d9e0",
        "box": "#f6f8fa",
        "box2": "#ffffff",
        "edge": "#8c959f",
        "accent": "#b45309",
        "accent_bg": "#fff7ed",
        "accent_line": "#f3c58f",
        "hl": "#fde68a",
        "hl_fg": "#1f2328",
        "red": "#b42318",
        "red_bg": "#fee4e2",
        "term": "#f6f8fa",
    },
    "dark": {
        "fg": "#e6edf3",
        "muted": "#9198a1",
        "faint": "#6e7681",
        "line": "#3d444d",
        "box": "#151b23",
        "box2": "#0d1117",
        "edge": "#768390",
        "accent": "#f0a04b",
        "accent_bg": "#21170b",
        "accent_line": "#7a4b17",
        "hl": "#5c4813",
        "hl_fg": "#fff3c4",
        "red": "#ff8e85",
        "red_bg": "#3d1714",
        "term": "#161b22",
    },
}


def style(t: dict[str, str]) -> str:
    return f"""<style>
  text {{ font-family: {SANS}; fill: {t["fg"]}; }}
  .mono {{ font-family: {MONO}; }}
  .t {{ font-size: 14px; font-weight: 600; }}
  .b {{ font-size: 12.5px; fill: {t["muted"]}; }}
  .m {{ font-family: {MONO}; font-size: 12px; fill: {t["muted"]}; }}
  .h {{ font-size: 11px; font-weight: 600; letter-spacing: 0.08em; fill: {t["faint"]}; }}
  .acc {{ fill: {t["accent"]}; }}
  .box {{ fill: {t["box"]}; stroke: {t["line"]}; stroke-width: 1; }}
  .edge {{ stroke: {t["edge"]}; stroke-width: 1.4; fill: none; }}
  .bound {{ fill: none; stroke: {t["edge"]}; stroke-width: 1; stroke-dasharray: 5 4; }}
</style>"""


def defs(t: dict[str, str]) -> str:
    return f"""<defs>
  <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="{t["edge"]}"/>
  </marker>
  <marker id="arrA" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="{t["accent"]}"/>
  </marker>
</defs>"""


def text(x, y, s, cls="b", anchor="start", extra=""):
    return f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}"{extra}>{escape(s)}</text>'


def box(x, y, w, h, cls="box", rx=8, extra=""):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" class="{cls}"{extra}/>'


# --------------------------------------------------------------------------- architecture


def architecture(t: dict[str, str]) -> str:
    W, H = 960, 700
    o: list[str] = []
    A, AW = 24, 236  # sources column
    B, BW = 300, 344  # write path
    C, CW = 680, 256  # read path

    # machine boundary
    o.append(f'<rect x="4" y="4" width="{W - 8}" height="{H - 8}" rx="14" class="bound"/>')
    o.append(
        text(
            W - 22,
            682,
            "your machine · priorlog makes no network calls; MCP runs over stdio",
            "b",
            "end",
            ' style="font-style: italic"',
        )
    )

    # column headers
    o.append(text(A, 34, "SOURCES", "h"))
    o.append(text(B, 34, "WRITE PATH  ·  priorlog sync", "h"))
    o.append(text(C, 34, "READ PATH", "h"))

    # sources (read-only boundary)
    o.append(f'<rect x="{A - 10}" y="46" width="{AW + 20}" height="404" rx="10" class="bound"/>')
    srcs = [
        ("Claude Code", "~/.claude/projects/**.jsonl"),
        ("Claude desktop app", "…/Claude/**/local_*.json"),
        ("Codex CLI", "~/.codex/sessions/**.jsonl"),
        ("Pi", "~/.pi/agent/sessions/**.jsonl"),
        ("Any JSONL log", "[[sources.jsonl]] field map"),
    ]
    ys = []
    for i, (name, path) in enumerate(srcs):
        y = 60 + i * 70
        o.append(box(A, y, AW, 58))
        o.append(text(A + 14, y + 24, name, "t"))
        o.append(text(A + 14, y + 44, path, "m"))
        ys.append(y + 29)
    o.append(
        text(A + AW / 2, 438, "opened read-only · never modified", "b", "middle", ' style="font-weight:600"')
    )

    # bus from sources into adapters
    bus = A + AW + 20
    for y in ys:
        o.append(f'<path d="M{A + AW},{y} H{bus}" class="edge"/>')
    o.append(f'<path d="M{bus},{ys[0]} V{ys[-1]}" class="edge"/>')
    o.append(f'<path d="M{bus},{ys[0]} H{B - 2}" class="edge" marker-end="url(#arr)"/>')

    # write path
    o.append(box(B, 60, BW, 80))
    o.append(text(B + 16, 86, "Adapters", "t"))
    o.append(text(B + 16, 106, "claude · codex · pi · jsonl", "m"))
    o.append(text(B + 16, 126, "each line → message + its L-range locator", "b"))

    o.append(f'<path d="M{B + BW / 2},140 V164" class="edge" marker-end="url(#arr)"/>')
    o.append(box(B, 166, BW, 80))
    o.append(text(B + 16, 192, "Sync engine", "t"))
    o.append(text(B + 16, 212, "byte offset + inode per file, file lock", "b"))
    o.append(text(B + 16, 232, "unchanged file = one stat · open tail re-read", "b"))

    o.append(f'<path d="M{B + BW / 2},246 V270" class="edge" marker-end="url(#arr)"/>')
    # broker: the accent block
    by, bh = 272, 196
    o.append(
        f'<rect x="{B}" y="{by}" width="{BW}" height="{bh}" rx="8" fill="{t["accent_bg"]}" '
        f'stroke="{t["accent"]}" stroke-width="2"/>'
    )
    o.append(text(B + 16, by + 26, "Broker / Store", "t"))
    o.append(
        text(B + BW - 16, by + 26, "every write", "b", "end", f' style="fill:{t["accent"]};font-weight:600"')
    )
    items = [
        ("1", "Path policy", "source roots only; ~/.ssh, .env, auth.json denied"),
        ("2", "Deny rules", "lines matching deny_content are dropped"),
        ("3", "Redaction", "keys, tokens, emails → [REDACTED:kind]"),
    ]
    for i, (n, name, detail) in enumerate(items):
        y = by + 48 + i * 46
        o.append(
            f'<circle cx="{B + 26}" cy="{y + 10}" r="9" fill="none" stroke="{t["accent"]}" stroke-width="1.4"/>'
        )
        o.append(text(B + 26, y + 14, n, "t", "middle", f' style="font-size:11px;fill:{t["accent"]}"'))
        o.append(text(B + 44, y + 15, name, "t", extra=' style="font-size:13px"'))
        o.append(text(B + 44, y + 33, detail, "b"))

    o.append(f'<path d="M{B + BW / 2},{by + bh} V{by + bh + 24}" class="edge" marker-end="url(#arr)"/>')
    sy, sh = by + bh + 26, 112
    o.append(box(B, sy, BW, sh))
    o.append(text(B + 16, sy + 26, "SQLite index", "t"))
    o.append(text(B + BW - 16, sy + 26, "FTS5 · trigram", "m", "end"))
    o.append(text(B + 16, sy + 46, "~/.local/share/priorlog/index.sqlite3", "m"))
    x = B + 16
    for tb in ("files", "sessions", "messages", "links", "stats"):
        w = 10 + len(tb) * 7.4
        o.append(
            f'<rect x="{x}" y="{sy + 64}" width="{w}" height="22" rx="4" fill="{t["box2"]}" stroke="{t["line"]}"/>'
        )
        o.append(text(x + w / 2, sy + 79, tb, "m", "middle"))
        x += w + 8

    # read path (data flows up to the agents)
    o.append(box(C, 60, CW, 80))
    o.append(text(C + 16, 86, "Agents", "t"))
    o.append(text(C + 16, 106, "Claude Code · Codex · Pi", "b"))
    o.append(text(C + 16, 126, "any MCP client", "b"))

    o.append(f'<path d="M{C + CW / 2},164 V142" class="edge" marker-end="url(#arr)"/>')
    iy = 166
    rows = [
        ("MCP server", "tools: search · read · sessions · status"),
        ("CLI", "priorlog search | read | …"),
        ("Agent skill", "SKILL.md: when to look back"),
    ]
    o.append(box(C, iy, CW, 162))
    for i, (name, detail) in enumerate(rows):
        y = iy + 10 + i * 50
        if i:
            o.append(f'<path d="M{C + 14},{y - 2} H{C + CW - 14}" stroke="{t["line"]}"/>')
        o.append(text(C + 16, y + 20, name, "t", extra=' style="font-size:13px"'))
        o.append(text(C + 16, y + 38, detail, "b" if detail.startswith("tools") else "m"))

    o.append(f'<path d="M{C + CW / 2},352 V330" class="edge" marker-end="url(#arr)"/>')
    qy, qh = 354, sy + sh - 354
    o.append(box(C, qy, CW, qh))
    o.append(text(C + 16, qy + 26, "Query", "t"))
    q = [
        ("search", "bm25-ranked FTS5 match"),
        ("read", "cite → message ± context"),
        ("read --source", "exact raw lines"),
    ]
    for i, (k, v) in enumerate(q):
        y = qy + 50 + i * 22
        o.append(text(C + 16, y, k, "mono", extra=f' style="font-size:12px;fill:{t["fg"]};font-weight:600"'))
        o.append(text(C + 16 + len(k) * 7.4 + 8, y, v, "b"))
    o.append(f'<path d="M{C + 14},{qy + 128} H{C + CW - 14}" stroke="{t["line"]}"/>')
    o.append(text(C + 16, qy + 154, "every hit carries a citation", "b"))
    for i, (k, v) in enumerate((("cite", "claude:aaaaaaaa-…#0"), ("source", "…/aaaaaaaa-….jsonl:L2"))):
        o.append(text(C + 16, qy + 176 + i * 20, k, "b"))
        o.append(text(C + 66, qy + 176 + i * 20, v, "m", extra=f' style="fill:{t["accent"]}"'))

    # index -> query
    o.append(f'<path d="M{B + BW},{sy + sh / 2} H{C - 2}" class="edge" marker-end="url(#arr)"/>')

    # read --source goes back to the transcript lines
    yb = sy + sh + 40
    o.append(
        f'<path d="M{C + CW / 2},{qy + qh} V{yb} H{A + AW / 2} V{454}" fill="none" '
        f'stroke="{t["accent"]}" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#arrA)"/>'
    )
    o.append(
        text(
            (A + AW / 2 + C + CW / 2) / 2,
            yb - 8,
            "read --source re-opens the cited lines, re-checks the policy and redacts again",
            "b",
            "middle",
            f' style="fill:{t["accent"]}"',
        )
    )

    body = "\n".join(s for s in o if s)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-labelledby="ttl">\n<title id="ttl">priorlog architecture: transcripts from Claude Code, '
        f"Claude desktop, Codex, Pi and JSONL logs pass through adapters, the sync engine and the broker "
        f"(path policy, deny rules, redaction) into a SQLite FTS5 index, which the query layer serves to "
        f"agents through the MCP server, CLI and skill.</title>\n{style(t)}\n{defs(t)}\n{body}\n</svg>\n"
    )


# --------------------------------------------------------------------------- citation anatomy

CW = 7.8  # mono advance at 13px; every mono run gets textLength so columns line up in any font
CAP = HERE.parent / "demo" / "capture.json"


def mono(
    x0: float,
    y: float,
    line: str,
    spans: list[tuple[int, int, str]],
    t: dict[str, str],
    size: float = 13,
    cw: float = CW,
) -> list[str]:
    """One terminal line; spans (start, end, kind) get a background and/or colour."""
    out = []
    colour = {
        "fg": t["fg"],
        "dim": t["muted"],
        "hl": t["hl_fg"],
        "red": t["red"],
        "acc": t["accent"],
        "bold": t["fg"],
    }
    for a, b, kind in spans:
        if kind == "hl":
            out.append(
                f'<rect x="{x0 + a * cw - 1:.1f}" y="{y - size + 1}" width="{(b - a) * cw + 2:.1f}" '
                f'height="{size + 5}" rx="3" fill="{t["hl"]}"/>'
            )
        if kind == "red":
            out.append(
                f'<rect x="{x0 + a * cw - 1:.1f}" y="{y - size + 1}" width="{(b - a) * cw + 2:.1f}" '
                f'height="{size + 5}" rx="3" fill="{t["red_bg"]}"/>'
            )
    cuts = sorted({0, len(line), *[a for a, _, _ in spans], *[b for _, b, _ in spans]})
    for a, b in zip(cuts, cuts[1:], strict=False):
        seg = line[a:b]
        kind = next((k for s0, s1, k in spans if s0 <= a and b <= s1), "fg")
        lead = len(seg) - len(seg.lstrip(" "))
        seg2 = seg.strip(" ")
        if not seg2:
            continue
        x = x0 + (a + lead) * cw
        weight = ' font-weight="700"' if kind == "bold" else ""
        out.append(
            f'<text x="{x:.1f}" y="{y}" class="mono" style="font-size:{size}px;white-space:pre" '
            f'xml:space="preserve" fill="{colour[kind]}"{weight} textLength="{len(seg2) * cw:.1f}" '
            f'lengthAdjust="spacingAndGlyphs">{escape(seg2)}</text>'
        )
    return out


def bracket(
    x0: float, y: float, a: int, b: int, label: str, t: dict[str, str], cw: float = CW, anchor: str = "middle"
) -> list[str]:
    xa, xb = x0 + a * cw, x0 + b * cw
    yy = y + 6
    lx = {"middle": (xa + xb) / 2, "start": xa, "end": xb}[anchor]
    return [
        f'<path d="M{xa + 1:.1f},{yy} v5 H{xb - 1:.1f} v-5" fill="none" stroke="{t["accent"]}" stroke-width="1.3"/>',
        f'<path d="M{(xa + xb) / 2:.1f},{yy + 5} v4" stroke="{t["accent"]}" stroke-width="1.3"/>',
        text(lx, yy + 23, label, "b", anchor, f' style="fill:{t["accent"]};font-weight:600;font-size:12px"'),
    ]


def find(line: str, needle: str) -> tuple[int, int]:
    i = line.index(needle)
    return i, i + len(needle)


def wrap_at(s: str, width: int, indent: int, first_width: int | None = None) -> list[str]:
    out, cur = [], s
    first = True
    while cur:
        w = (first_width or width) if first else width - indent
        if len(cur) <= w:
            piece, cur = cur, ""
        else:
            cut = cur.rfind(" ", 0, w)
            cut = cut if cut > w // 2 else w
            piece, cur = cur[:cut], cur[cut:].lstrip(" ")
        out.append(piece if first else " " * indent + piece)
        first = False
    return out


def anatomy(t: dict[str, str]) -> str:
    cap = json.loads(CAP.read_text())
    hit = cap["hit"]
    search_out = next(s for s in cap["steps"] if s["cmd"].startswith("priorlog search"))["out"].split("\n")
    read_step = next(s for s in cap["steps"] if s["cmd"].startswith("priorlog read"))
    raw = next(x for x in read_step["out"].split("\n") if x.lstrip().startswith("L1: "))

    i = next(n for n, x in enumerate(search_out) if x.startswith("[") and hit["title"] in x)
    head, snip, cites = search_out[i], search_out[i + 1], search_out[i + 2]
    cite_line, src_line = cites.split("   source: ")
    src_line = "    source: " + src_line
    snip_lines = wrap_at(snip, 100, 6, first_width=82)

    W = 960
    X = 44
    o: list[str] = []
    o.append(text(24, 30, "ONE SEARCH HIT, TAKEN APART", "h"))
    o.append(
        text(
            W - 24, 30, "real output of the demo run", "b", "end", ' style="font-style:italic;font-size:12px"'
        )
    )

    # card with the hit
    card_y = 44
    y = card_y + 36
    o_card: list[str] = []
    o_card += mono(X, y, "$ priorlog search rate limiter", [(0, 1, "dim"), (2, 30, "dim")], t)
    y += 40
    # title row
    spans = []
    for needle, lab in (
        (hit["title"], "session title"),
        (hit["harness"] + " ·", "harness"),
        (hit["timestamp"][:16].replace("T", " "), "timestamp"),
        ("· " + hit["role"], "role"),
    ):
        a, b = find(head, needle)
        if needle.endswith(" ·"):
            b -= 2
        if needle.startswith("· "):
            a += 2
        spans.append((a, b, lab))
    o_card += mono(X, y, head, [(0, len(head), "bold")], t)
    for a, b, lab in spans:
        o_card += bracket(X, y, a, b, lab, t)
    y += 56
    # snippet
    for _k, line in enumerate(snip_lines):
        sp: list[tuple[int, int, str]] = [(0, len(line), "fg")]
        if "«" in line:
            a, b = find(line, line[line.index("«") : line.index("»") + 1])
            sp.append((a, b, "hl"))
        if "[REDACTED:" in line:
            a = line.index("[REDACTED:")
            b = line.index("]", a) + 1
            sp.append((a, b, "red"))
        if line.lstrip().startswith(">"):
            j = line.index(">")
            sp.append((j, j + 1, "dim"))
        sp = [s for s in sp if s[2] != "fg"]
        o_card += mono(X, y, line, sp, t)
        for a, b, kind in sp:
            if kind == "hl":
                o_card += bracket(X, y, a, b, "every search word, marked «»", t)
            if kind == "red":
                o_card += bracket(X, y, a, b, "secret masked in the broker before indexing", t)
        y += 56 if any(k2 in ("hl", "red") for _, _, k2 in sp) else 22
    # cite
    a0 = cite_line.index("cite: ")
    o_card += mono(X, y, cite_line, [(a0, a0 + 5, "dim")], t)
    c0 = cite_line.index("claude:")
    sid = hit["session"].split(":", 1)[1]
    s0, s1 = find(cite_line, sid)
    h0 = cite_line.index("#")
    o_card += bracket(X, y, c0, c0 + 6, "harness", t)
    o_card += bracket(X, y, s0, s1, "session id", t)
    o_card += bracket(X, y, h0, h0 + len(cite_line) - h0, "message #0", t)
    y += 56
    p0 = src_line.index("~")
    l0 = src_line.rindex(":L")
    o_card += mono(X, y, src_line, [(4, 11, "dim"), (l0 + 1, len(src_line), "acc")], t)
    o_card += bracket(X, y, p0, l0, "the transcript file this message came from", t)
    o_card += bracket(X, y, l0 + 1, len(src_line), "exact lines", t)
    src_y = y
    y += 44
    card_h = y - card_y
    o.append(
        f'<rect x="20" y="{card_y}" width="{W - 40}" height="{card_h}" rx="10" fill="{t["term"]}" '
        f'stroke="{t["line"]}"/>'
    )
    o += o_card

    # arrow from the line range to the raw lines
    lx = X + (l0 + 2) * CW
    ay0 = src_y + 36
    ay1 = card_y + card_h + 62
    o.append(
        f'<path d="M{lx:.1f},{ay0} V{ay1 - 2}" stroke="{t["accent"]}" stroke-width="1.6" fill="none" '
        f'marker-end="url(#arrA)"/>'
    )
    cmd = f"priorlog read {hit['cite']} --source"
    o.append(
        text(
            lx - 14,
            card_y + card_h + 36,
            cmd,
            "mono",
            "end",
            f' style="font-size:12.5px;fill:{t["accent"]};font-weight:600"',
        )
    )

    # raw lines panel
    ry = ay1 + 2
    rx_ = 20
    path = hit["locator"].rsplit(":", 1)[0]
    raw_lines = wrap_at(raw, 112, 6)
    rh = 52 + len(raw_lines) * 19 + 16
    o.append(
        f'<rect x="{rx_}" y="{ry}" width="{W - 40}" height="{rh}" rx="10" fill="{t["term"]}" stroke="{t["accent"]}" '
        f'stroke-width="1.4"/>'
    )
    o.append(f'<path d="M{rx_},{ry + 34} H{W - 20}" stroke="{t["line"]}"/>')
    o += mono(X, ry + 22, path, [(0, len(path), "dim")], t, size=12, cw=7.2)
    o.append(
        text(
            W - 40,
            ry + 22,
            "opened read-only, policy re-checked, redacted again",
            "b",
            "end",
            ' style="font-size:12px"',
        )
    )
    yy = ry + 56
    cw2 = 7.2
    for line in raw_lines:
        sp = []
        if "[REDACTED:" in line:
            a = line.index("[REDACTED:")
            sp.append((a, line.index("]", a) + 1, "red"))
        if line.lstrip().startswith("L1:"):
            j = line.index("L1:")
            sp.append((j, j + 3, "acc"))
        o += mono(X - 14, yy, line, sp, t, size=12, cw=cw2)
        yy += 19
    H = ry + rh + 44
    o.append(
        text(
            W / 2,
            H - 14,
            "The transcript keeps the original. The index, search results and read output only ever "
            "contain the placeholder.",
            "b",
            "middle",
            ' style="font-size:12.5px"',
        )
    )

    body = "\n".join(o)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
        f'aria-labelledby="ttl">\n<title id="ttl">Anatomy of a priorlog search hit: session title, harness, '
        f"timestamp and role; the snippet with the matched words marked and a secret shown as "
        f"[REDACTED:anthropic_key]; the cite (harness, session id, message number); and the source locator "
        f"(transcript file and line range), which priorlog read --source opens to show the exact raw line, "
        f"redacted.</title>\n{style(t)}\n{defs(t)}\n{body}\n</svg>\n"
    )


def main() -> None:
    for name, t in THEMES.items():
        (ASSETS / f"architecture-{name}.svg").write_text(architecture(t))
        (ASSETS / f"citation-anatomy-{name}.svg").write_text(anatomy(t))
    print("wrote architecture-{light,dark}.svg, citation-anatomy-{light,dark}.svg")


if __name__ == "__main__":
    main()
