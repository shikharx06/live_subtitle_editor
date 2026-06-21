#!/usr/bin/env bash
# Build autoplaying GIFs from the merged side-by-side .mp4s (for inline README previews).
# Run merge-videos.sh first so docs/media/playwright/*.mp4 exist.
set -euo pipefail

cd "$(dirname "$0")/.."
DIR="../docs/media/playwright"

shopt -s nullglob
for mp4 in "$DIR"/*.mp4; do
  slug="$(basename "$mp4" .mp4)"
  ffmpeg -y -loglevel error -i "$mp4" \
    -vf "fps=12,scale=860:-1:flags=lanczos,palettegen=stats_mode=diff" /tmp/pal.png
  ffmpeg -y -loglevel error -i "$mp4" -i /tmp/pal.png \
    -filter_complex "fps=12,scale=860:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3" \
    "$DIR/${slug}.gif"
  echo "ok: ${slug}.gif"
done
echo "done -> $DIR"
