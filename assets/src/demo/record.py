"""Record a real priorlog terminal session and render it to assets/demo.gif.

    python3 assets/src/demo/record.py                     # record -> typescript + timing -> GIF
    python3 assets/src/demo/record.py --reuse             # re-render the saved recording only
    python3 assets/src/demo/record.py --frames-only DIR   # keep the PNG frames for review

Then `python3 assets/src/diagrams/build.py` to refresh the citation diagram from capture.json.

1. Record. `script` (util-linux) runs session.sh in a real pseudo-terminal (100x30) and logs
   every byte the terminal receives with its timing, the same thing asciinema does. session.sh
   builds a throwaway HOME from tests/fixtures, then types each priorlog command a character
   at a time (as VHS does) and runs it for real. The raw recording is saved next to this file
   (session.typescript, session.timing; `scriptreplay -t session.timing session.typescript`
   plays it back in any terminal), plus capture.json for the diagram.
2. Render. A small terminal emulator (text, CR/LF, backspace, tab, autowrap, scrolling, SGR
   colours, CSI cursor moves and K/J clears) replays the typescript with its recorded timing
   and samples the screen at 20 fps. No colour or text is added: what the GIF shows is what
   the terminal showed. Frame 0 is a poster: the screen right after `priorlog search`
   finished, taken from the same recording; the full recording follows from the start.
   Frames are drawn with PIL and assembled with ffmpeg (palettegen/paletteuse).

Needs: python3 with PIL, util-linux `script`, ffmpeg, DejaVu Sans Mono, and the repo's .venv
(`uv sync`; priorlog is installed editable, so the recording uses the current src/).
"""

from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TYPESCRIPT = HERE / "session.typescript"
TIMING = HERE / "session.timing"
CAPTURE = HERE / "capture.json"  # read by assets/src/diagrams/build.py
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

COLS, ROWS = 100, 30  # must match `stty` in session.sh
W, SIZE, LINE_H = 960, 15, 19
PAD_TOP, PAD_BOTTOM, BAR = 14, 16, 34

BG, FG, DIM = "#0e1116", "#d5dae1", "#7f8894"
BAR_BG, BORDER, CURSOR = "#161b22", "#262c35", "#c9d1d9"
# SGR 30-37 / 90-97
PALETTE = ["#484f58", "#ff8a80", "#7ee787", "#f2cc60", "#a5b4fc", "#d2a8ff", "#79c0ff", "#d5dae1"]

FPS = 20
POSTER_S = 1.5  # frame 0 (the thumbnail GitHub shows): the finished search screen
FINAL_S = 7.0  # hold on the last screen (the recording ends when the shell exits)
POSTER_AT = rb"\$\x1b\[0m (?=priorlog read)"  # poster: the screen at the prompt before `read`

# --------------------------------------------------------------------------- record


def record() -> None:
    """Run session.sh under `script`, check it, and save typescript, timing and capture.json."""
    work = Path(tempfile.mkdtemp(prefix="priorlog-demo-"))
    ts, tm = work / "session.typescript", work / "session.timing"
    env = {
        "PATH": "/usr/bin:/bin",
        "SHELL": "/bin/bash",
        "LANG": "C.UTF-8",
        "TERM": "xterm-256color",
        "TZ": "UTC",
        "DEMO_WORK": str(work),  # via env, so the path stays out of script's header line
    }
    subprocess.run(
        ["script", "-q", "-E", "never", "-m", "classic", "-T", str(tm), "-O", str(ts)]
        + ["-c", "bash assets/src/demo/session.sh"],
        cwd=REPO,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    steps = split_steps(ts.read_bytes())
    hits = json.loads((work / "hits.json").read_text())["hits"]
    cite = steps[-1]["cmd"].split()[2]
    capture = {"steps": steps, "hit": next(h for h in hits if h["cite"] == cite)}
    blob = json.dumps(capture, indent=2, ensure_ascii=False)
    for text in (ts.read_text(errors="replace"), blob):
        for leak in (str(Path.home()), os.environ.get("USER") or "\0", str(work)):
            if leak in text:
                raise SystemExit(f"refusing to save: recording contains {leak!r}")
    shutil.copyfile(ts, TYPESCRIPT)
    shutil.copyfile(tm, TIMING)
    CAPTURE.write_text(blob + "\n")
    print(f"recorded {TYPESCRIPT.name} ({TYPESCRIPT.stat().st_size} B), {TIMING.name}, {CAPTURE.name}")


def body(ts: bytes) -> bytes:
    """The terminal output: script's first line is its own 'Script started' header."""
    return ts[ts.index(b"\n") + 1 :]


def split_steps(ts: bytes) -> list[dict[str, str]]:
    """Commands and their output as plain text, cut at each prompt."""
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", body(ts).decode()).replace("\r", "")
    steps: list[dict[str, list[str]]] = []
    for line in text.split("\n"):
        if line.startswith("Script done on"):
            break
        if line.startswith("~ $ "):
            if line[4:]:
                steps.append({"cmd": line[4:], "out": []})
        elif steps:
            steps[-1]["out"].append(line)
    return [{"cmd": s["cmd"], "out": "\n".join(s["out"]).rstrip("\n")} for s in steps]


def events(ts: bytes, timing: str) -> list[tuple[float, bytes]]:
    """(seconds since the first output, chunk) from a classic `script` timing log."""
    data, pos, t, out = body(ts), 0, 0.0, []
    for line in timing.splitlines():
        delay, n = line.split()
        t += float(delay)
        out.append((t, data[pos : pos + int(n)]))
        pos += int(n)
    t0 = out[0][0]
    return [(t - t0, chunk) for t, chunk in out]


# --------------------------------------------------------------------------- terminal emulator


class Screen:
    """Just enough of a VT100 for a shell running plain-text commands."""

    def __init__(self) -> None:
        self.grid = [self.blank() for _ in range(ROWS)]
        self.x = self.y = 0
        self.wrap_next = False  # xterm-style deferred autowrap
        self.attr: tuple[str, bool] = (FG, False)
        self.state, self.seq = "text", ""
        self.utf8 = codecs.getincrementaldecoder("utf-8")("replace")

    def blank(self) -> list[tuple[str, str, bool]]:
        return [(" ", FG, False)] * COLS

    def snapshot(self) -> tuple:
        return tuple(tuple(r) for r in self.grid), self.x, self.y

    def linefeed(self) -> None:
        if self.y == ROWS - 1:
            self.grid = self.grid[1:] + [self.blank()]
        else:
            self.y += 1

    def put(self, ch: str) -> None:
        if self.wrap_next:
            self.x, self.wrap_next = 0, False
            self.linefeed()
        self.grid[self.y][self.x] = (ch, *self.attr)
        if self.x == COLS - 1:
            self.wrap_next = True
        else:
            self.x += 1

    def feed(self, chunk: bytes) -> None:
        for ch in self.utf8.decode(chunk):
            if self.state == "esc":
                self.state, self.seq = {"[": ("csi", ""), "]": ("osc", "")}.get(ch, ("text", ""))
            elif self.state == "csi":
                if "@" <= ch <= "~":
                    self.csi(self.seq, ch)
                    self.state = "text"
                else:
                    self.seq += ch
            elif self.state == "osc":
                if ch == "\x07" or ch == "\\":
                    self.state = "text"
            elif ch == "\x1b":
                self.state = "esc"
            elif ch == "\r":
                self.x, self.wrap_next = 0, False
            elif ch == "\n":
                self.wrap_next = False
                self.linefeed()
            elif ch == "\b":
                self.x, self.wrap_next = max(0, self.x - 1), False
            elif ch == "\t":
                self.x = min(COLS - 1, (self.x // 8 + 1) * 8)
            elif ch >= " ":
                self.put(ch)

    def csi(self, seq: str, final: str) -> None:
        if seq.startswith("?"):
            return  # private modes (cursor visibility, bracketed paste): nothing to draw
        args = [int(a) if a.isdigit() else 0 for a in seq.split(";")] if seq else []
        n = max(1, args[0]) if args else 1
        row = self.grid[self.y]
        if final == "m":
            for a in args or [0]:
                if a == 0:
                    self.attr = (FG, False)
                elif a == 1:
                    self.attr = (self.attr[0], True)
                elif a == 22:
                    self.attr = (self.attr[0], False)
                elif a == 2:
                    self.attr = (DIM, self.attr[1])
                elif 30 <= a <= 37 or 90 <= a <= 97:
                    self.attr = (PALETTE[a % 10], self.attr[1])
                elif a == 39:
                    self.attr = (FG, self.attr[1])
        elif final == "K":
            mode = args[0] if args else 0
            a, b = {0: (self.x, COLS), 1: (0, self.x + 1)}.get(mode, (0, COLS))
            row[a:b] = [(" ", FG, False)] * (b - a)
        elif final == "J":
            mode = args[0] if args else 0
            if mode == 0:
                row[self.x :] = [(" ", FG, False)] * (COLS - self.x)
                self.grid[self.y + 1 :] = [self.blank() for _ in range(ROWS - self.y - 1)]
            elif mode == 1:
                self.grid[: self.y] = [self.blank() for _ in range(self.y)]
            else:
                self.grid = [self.blank() for _ in range(ROWS)]
        elif final in "ABCDGH":
            self.wrap_next = False
            if final == "A":
                self.y = max(0, self.y - n)
            elif final == "B":
                self.y = min(ROWS - 1, self.y + n)
            elif final == "C":
                self.x = min(COLS - 1, self.x + n)
            elif final == "D":
                self.x = max(0, self.x - n)
            elif final == "G":
                self.x = min(COLS - 1, n - 1)
            else:
                r, c = (args + [1, 1])[:2]
                self.y, self.x = min(ROWS - 1, max(1, r) - 1), min(COLS - 1, max(1, c) - 1)


# --------------------------------------------------------------------------- drawing


class Painter:
    def __init__(self) -> None:
        self.font = ImageFont.truetype(FONT, SIZE)
        self.bold = ImageFont.truetype(FONT_BOLD, SIZE)
        self.cw = self.font.getlength("M")
        self.pad_x = round((W - COLS * self.cw) / 2)
        self.h = BAR + PAD_TOP + ROWS * LINE_H + PAD_BOTTOM

    def draw(self, s: Screen) -> Image.Image:
        img = Image.new("RGB", (W, self.h), BG)
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, BAR), fill=BAR_BG)
        d.line((0, BAR, W, BAR), fill=BORDER)
        for i in range(3):
            x = 18 + i * 20
            d.ellipse((x, BAR / 2 - 6, x + 12, BAR / 2 + 6), fill="#3a3f47")
        title = "priorlog demo · bash · 100×30"
        d.text((W / 2 - self.font.getlength(title) / 2, BAR / 2 - 9), title, font=self.font, fill=DIM)
        for r, row in enumerate(s.grid):
            y = BAR + PAD_TOP + r * LINE_H
            i = 0
            while i < COLS:  # runs of the same attributes
                j = i
                while j < COLS and row[j][1:] == row[i][1:]:
                    j += 1
                text = "".join(c for c, _, _ in row[i:j])
                if text.strip():
                    font = self.bold if row[i][2] else self.font
                    d.text((self.pad_x + i * self.cw, y), text, font=font, fill=row[i][1])
                i = j
        cx = self.pad_x + s.x * self.cw
        cy = BAR + PAD_TOP + s.y * LINE_H
        d.rectangle((cx + 1, cy + 1, cx + self.cw - 1, cy + LINE_H - 1), fill=CURSOR)
        ch, _, bold = s.grid[s.y][s.x]
        if ch != " ":
            d.text((cx, cy), ch, font=self.bold if bold else self.font, fill=BG)
        return img


def render(ts: bytes, timing: str, frames: Path) -> list[tuple[Path, float]]:
    """Sample the replayed screen at FPS; identical consecutive frames are merged."""
    frames.mkdir(parents=True, exist_ok=True)
    paint = Painter()
    seq: list[tuple[Path, float]] = []

    def emit(img: Image.Image, secs: float) -> None:
        p = frames / f"f{len(seq):04d}.png"
        img.save(p)
        seq.append((p, secs))

    ev = events(ts, timing)

    poster, upto = Screen(), re.search(POSTER_AT, body(ts)).end()
    pos = 0
    for _, chunk in ev:
        if pos >= upto:
            break
        poster.feed(chunk[: upto - pos])
        pos += len(chunk)
    emit(paint.draw(poster), POSTER_S)

    s, k, last = Screen(), 0, None
    end = ev[-1][0]
    i = 0
    while k / FPS <= end:
        while i < len(ev) and ev[i][0] <= k / FPS:
            s.feed(ev[i][1])
            i += 1
        snap = s.snapshot()
        if snap == last:
            seq[-1] = (seq[-1][0], seq[-1][1] + 1 / FPS)
        else:
            emit(paint.draw(s), 1 / FPS)
            last = snap
        k += 1
    for _, chunk in ev[i:]:
        s.feed(chunk)
    emit(paint.draw(s), FINAL_S)
    return seq


def assemble(seq: list[tuple[Path, float]], out: Path) -> None:
    lst = seq[0][0].parent / "frames.txt"
    with open(lst, "w") as fh:
        for p, secs in seq:
            fh.write(f"file '{p.name}'\nduration {secs:.3f}\n")
        fh.write(f"file '{seq[-1][0].name}'\n")
    vf = "split[a][b];[a]palettegen=max_colors=96:stats_mode=full:reserve_transparent=0[p];[b][p]paletteuse=dither=none"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
        + ["-vf", vf, "-fps_mode", "vfr", "-loop", "0", str(out)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=REPO / "assets" / "demo.gif")
    ap.add_argument("--reuse", action="store_true", help="re-render the saved recording, do not record")
    ap.add_argument("--frames-only", type=Path, help="write PNG frames here and stop")
    a = ap.parse_args()
    if not a.reuse:
        record()
    frames = a.frames_only or Path(tempfile.mkdtemp(prefix="priorlog-gif-")) / "frames"
    seq = render(TYPESCRIPT.read_bytes(), TIMING.read_text(), frames)
    if a.frames_only:
        print(f"{len(seq)} frames in {frames}")
        return
    assemble(seq, a.out)
    print(
        f"wrote {a.out} ({a.out.stat().st_size / 1e6:.2f} MB, {len(seq)} frames, "
        f"{sum(s for _, s in seq):.1f}s)"
    )


if __name__ == "__main__":
    main()
