"""Crop a 1536x1024 hero candidate to the 2.5:1 README banner and save it as JPEG.

python3 assets/src/hero/finish_hero.py CANDIDATE.png assets/hero.jpg [--top 170]
"""

import argparse

from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("out")
ap.add_argument("--top", type=int, default=170, help="first source row of the crop band")
a = ap.parse_args()
im = Image.open(a.src).convert("RGB")
w, _ = im.size
band = round(w / 2.5)
im = im.crop((0, a.top, w, a.top + band)).resize((1600, 640), Image.LANCZOS)
im.save(a.out, quality=88, optimize=True, progressive=True)
print(f"wrote {a.out} {im.size}")
