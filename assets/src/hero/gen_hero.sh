#!/usr/bin/env bash
# gen_hero.sh OUT.png PROMPTFILE -> OUT.png (landscape 1536x1024 from gpt-6-luna via `codex exec`)
# One lean codex call: no tools beyond image generation, read-only sandbox, low reasoning effort.
# Crop/compress to the README hero afterwards with finish_hero.py.
set -uo pipefail
out=$(realpath -m "$1"); prompt=$(cat "$2")
msg="Call your image generation tool directly, exactly once, landscape 1536x1024. Pass the image prompt below to the tool word for word: do not rewrite, shorten or add to it. Do not read any files or skills, do not run shell commands, do not copy or save anything, do not judge the result. Image prompt: $prompt"
work=${HERO_WORK:-${TMPDIR:-/tmp}/priorlog-hero}
wd=$work/$(basename "$out" .png)_$(date +%s%N); mkdir -p "$wd" "$(dirname "$out")"
log=$work/$(basename "$out" .png).log; t0=$(date +%s)
bash -ic "$(printf '%q ' codex exec --ignore-user-config --skip-git-repo-check -s read-only -m gpt-6-luna -c model_reasoning_effort=low -C "$wd" -- "$msg")" </dev/null > "$log" 2>&1
sid=$(grep -m1 -o 'session id: [0-9a-f-]*' "$log" | cut -d' ' -f3)
png=$(ls -t ~/.codex/generated_images/"$sid"/*.png 2>/dev/null | head -1)
[[ -n $png ]] && cp "$png" "$out"
echo "$(basename "$out") done in $(( $(date +%s)-t0 ))s exists=$([[ -s $out ]] && echo yes || echo no)"
