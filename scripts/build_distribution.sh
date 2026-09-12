#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$ROOT_DIR/dist"

rm -rf -- "$BUILD_DIR" "$DIST_DIR"
find "$ROOT_DIR/src" -maxdepth 1 -type d -name '*.egg-info' -exec rm -rf -- {} +

python -m build --sdist --wheel --outdir "$DIST_DIR"

shopt -s nullglob
wheels=("$DIST_DIR"/*.whl)
sdists=("$DIST_DIR"/*.tar.gz)
if ((${#wheels[@]} != 1 || ${#sdists[@]} != 1)); then
  echo "Expected exactly one wheel and one source distribution in $DIST_DIR." >&2
  exit 1
fi

python "$ROOT_DIR/scripts/check_distribution_contents.py" \
  --wheel "${wheels[0]}" \
  --sdist "${sdists[0]}"
