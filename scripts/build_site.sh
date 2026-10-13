#!/usr/bin/env bash
# Assemble the GitHub Pages site: the static dashboard plus the repo's data.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-_site}"
rm -rf "$OUT"
mkdir -p "$OUT"
cp -r site/. "$OUT/"
cp -r data "$OUT/data"
mkdir -p "$OUT/config" && cp config/settings.json "$OUT/config/"
touch "$OUT/.nojekyll"
echo "Built $OUT"
