#!/usr/bin/env bash
# Merge per-user Playwright videos side-by-side. Requires test-results/pairs/*-{A,B}.webm
# (produced by `PW_VIDEO=1 npx playwright test`).
set -euo pipefail

cd "$(dirname "$0")/.."
PAIRS="test-results/pairs"
OUT="../docs/media/playwright"

[ -d "$PAIRS" ] || { echo "no $PAIRS — run: PW_VIDEO=1 npx playwright test"; exit 1; }
mkdir -p "$OUT"
rm -f "$OUT"/*.mp4

for a in "$PAIRS"/*-A.webm; do
  slug="$(basename "$a" -A.webm)"
  b="$PAIRS/${slug}-B.webm"
  [ -f "$b" ] || { echo "missing B for $slug"; continue; }
  ffmpeg -y -loglevel error -i "$a" -i "$b" -filter_complex \
    "[0:v]scale=-2:480,setsar=1,pad=iw:ih+10:0:10:color=0x0F7A66,pad=iw+2:ih:0:0:color=0xE9E5DC[a];\
     [1:v]scale=-2:480,setsar=1,pad=iw:ih+10:0:10:color=0x3B5BA5[b];\
     [a][b]hstack=inputs=2[v]" \
    -map "[v]" -c:v libx264 -crf 30 -preset veryfast -pix_fmt yuv420p -movflags +faststart -an \
    "$OUT/${slug}.mp4"
  echo "ok: ${slug}.mp4"
done
echo "done -> $OUT"
