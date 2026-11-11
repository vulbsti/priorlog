# Hero image: prompts and selection

`assets/hero.jpg` (1600x640) is a crop of a gpt-6-luna image generated through `codex exec`
(ChatGPT plan, no per-image cost), the same lean one-shot call used for other image work,
but landscape and without reference images.

## Command

```bash
# one candidate per prompt file (1536x1024 PNG)
bash assets/src/hero/gen_hero.sh out/hero_b.png prompt_b.txt
# crop the 2.5:1 band and compress
python3 assets/src/hero/finish_hero.py out/hero_b.png assets/hero.jpg --top 170
```

`gen_hero.sh` asks codex to "Call your image generation tool directly, exactly once, landscape
1536x1024" and to pass the prompt word for word, with `-m gpt-6-luna -c model_reasoning_effort=low
-s read-only`, then copies the PNG from `~/.codex/generated_images/<session>/`.

## Chosen: B

Why B: it reads as a real photograph (plywood grain, paper fibre, soft overcast light, real
depth of field) and the metaphor lands without explanation: one long transcript, a line under
the loupe, yellow highlights for matches, black marker for redaction, ticked flags for
citations. The printed text is blurred, so there is no fake lettering to spot. The right
40% is calm, empty wood, so the banner never competes with the README title. The 2.5:1 band
(rows 170-784) drops the coffee mug at the bottom edge.

### Prompt B

```text
Top-down documentary photograph of a long strip of fanfold continuous-feed printer paper unfolded across a pale birch-plywood workbench, running diagonally from the lower left toward the centre, with the rest of the folded stack sitting at the lower left corner. Tractor-feed holes along the paper edges, faint perforations at each fold. The paper is covered in small grey monospace printout lines, blurred and unreadable. Along the strip: three lines marked with yellow highlighter, two lines blacked out with heavy black felt-tip marker bars, and four small paper sticky flags in muted orange and teal stuck to the edge like bookmarks, each with a tiny handwritten pencil tick. A round brass loupe sits on the paper over one yellow line. A ceramic mug of black coffee partly out of frame at the bottom edge. Overcast daylight from a big window, soft and even, subtle shadows under the paper folds, real paper texture and slight creases. Shot on a full-frame camera, 35mm, f/4, natural colour grade, a little film grain. The upper right half of the frame is plain empty workbench in soft light. No text legible, no logos, no computer screens, no hands.
```

## Rejected candidates

- **A** (green-bar stack by a window, loupe, pencil, highlighter): good light, but the
  "dot-matrix" text is crisp enough to read as gibberish, and the stack is portrait-shaped,
  so the 2.5:1 crop cuts it awkwardly.
- **C** (low-angle tabbed ledger, walnut desk, sunset): the most "AI" of the four: HDR glow,
  dust motes, warped page block, painterly finish.
- **D** (strip laid flat in a horizontal band, flags on top): fits the banner perfectly but
  looks like a staged graphic; the repeated dash-text pattern is obviously synthetic.

### Prompt A

```text
Overhead editorial photograph, shot straight down from above on a 50mm lens at f/2.8, of a worn oak desk by a window. On the left third of the frame: a loose stack of old continuous-feed computer printout paper (pale green-and-white bar stripes, tractor-feed sprocket holes along both edges, perforated fold lines), several sheets fanned out. The printed lines are tiny dot-matrix monospace text, too small and soft to read. A few lines are highlighted with a translucent yellow highlighter. Two or three lines are crossed out with thick, slightly uneven black marker bars, like a redacted document. Small coloured paper index flags (orange, blue, white) stick out from the edges of the stack, marking places. A brass and glass jeweller's loupe rests on the top sheet, magnifying one highlighted line. A pencil and a capped highlighter lie nearby. Soft natural morning window light from the upper left, gentle long shadows, fine wood grain, a little dust, slight paper curl. Shallow depth of field so the far edges fall out of focus. The right half of the frame is calm, mostly empty oak desk surface with soft light: generous negative space. Muted, warm, realistic colours, like a magazine still-life photo. No logos, no brand names, no readable words, no screens, no people.
```

### Prompt C

```text
Close, low-angle editorial still life, camera about 30 degrees above a dark walnut desk, side-lit by late-afternoon window light from the left. A thick block of folded continuous-feed computer printout, green bar paper with sprocket holes on both edges, sits on the left side of the frame; its top page lies open. Narrow paper index tabs in orange, white and blue protrude from between the folds at different depths, like a well-used reference ledger. On the open page, one line is highlighted in yellow and two lines are blacked out with thick marker. A small brass jeweller's loupe rests on the page beside the highlighted line. The printed characters are tiny and fall quickly out of focus, nothing readable. Shallow depth of field, f/2, focus on the loupe and the highlighted line, creamy falloff. The right side of the frame is soft, dim, empty walnut desk and a blurred window glow: quiet negative space. Realistic, muted, warm tones, tactile paper fibres, faint dust in the light. No logos, no brand marks, no readable text, no screens, no people.
```

### Prompt D

```text
Top-down documentary photograph of a pale birch-plywood workbench. A long strip of white fanfold continuous-feed printer paper, tractor-feed holes along both edges and faint perforations at each fold, lies flat and runs horizontally across the middle band of the frame from the left edge to about the centre, where the rest of the folded paper stack sits squarely. Everything important sits in a wide horizontal band through the middle of the picture; the top and bottom of the frame are plain workbench. The paper is covered in small grey monospace printout lines, soft and unreadable. Along the strip: three lines marked with translucent yellow highlighter, two lines blacked out with heavy black felt-tip marker bars, and four small paper sticky flags in muted orange and teal stuck along the top edge of the paper like bookmarks. A round brass jeweller's loupe rests on the paper over one yellow-highlighted line, magnifying it. Overcast daylight from a big window on the left, soft and even, gentle shadows under the paper folds, real paper texture and creases, wood grain. Full-frame camera, 35mm, f/4, natural colour grade, slight film grain. The right third of the frame is empty workbench in soft light. No legible text, no logos, no computer screens, no hands, no mug.
```
