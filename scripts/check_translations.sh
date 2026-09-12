#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TS_DIR="$ROOT_DIR/i18n/ts"
QM_DIR="$ROOT_DIR/src/archupdater/i18n/resources"
SOURCE_DIR="$ROOT_DIR/src"
SOURCE_CHECKER="$ROOT_DIR/scripts/check_translation_sources.py"
STRICT_SOURCE_CHECK="${ARCHUPDATER_TRANSLATION_STRICT:-0}"
LUPDATE="${PYSIDE6_LUPDATE:-}"
LRELEASE="${PYSIDE6_LRELEASE:-}"
LCONVERT="${PYSIDE6_LCONVERT:-}"

resolve_tool() {
  local configured="$1"
  shift
  if [[ -n "$configured" ]]; then
    command -v "$configured" >/dev/null 2>&1 || {
      echo "Configured translation tool is missing: $configured" >&2
      return 1
    }
    printf '%s\n' "$configured"
    return 0
  fi
  local candidate
  for candidate in "$@"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  echo "No compatible Qt translation tool found (tried: $*)." >&2
  return 1
}

LUPDATE="$(resolve_tool "$LUPDATE" pyside6-lupdate lupdate6)"
LRELEASE="$(resolve_tool "$LRELEASE" pyside6-lrelease lrelease6)"
LCONVERT="$(resolve_tool "$LCONVERT" pyside6-lconvert lconvert6)"

tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "$tmp_dir"' EXIT

mapfile -t source_files < <(find "$SOURCE_DIR" -type f -name '*.py' -print | sort)
if ((${#source_files[@]} == 0)); then
  echo "No Python source files found below $SOURCE_DIR." >&2
  exit 1
fi

catalogs=()
ts_catalogs=()
for lang in en it de fr es; do
  ts_catalogs+=("$TS_DIR/archupdater_${lang}.ts")
  catalogs+=(
    "$TS_DIR/archupdater_${lang}.ts"
    "$QM_DIR/archupdater_${lang}.qm"
  )
done
for catalog in "${catalogs[@]}"; do
  if [[ ! -s "$catalog" ]]; then
    echo "Missing or empty translation artifact: $catalog" >&2
    exit 1
  fi
done
catalog_state_before="$(sha256sum "${catalogs[@]}")"

fresh_catalog="$tmp_dir/archupdater_en.ts"
"$LUPDATE" \
  "${source_files[@]}" \
  -no-obsolete \
  -warnings-are-errors \
  -source-language en_US \
  -target-language en_US \
  -ts "$fresh_catalog"

source_check_arguments=()
if [[ "$STRICT_SOURCE_CHECK" == "1" ]]; then
  source_check_arguments+=(--strict)
fi
python "$SOURCE_CHECKER" \
  --fresh "$fresh_catalog" \
  "${source_check_arguments[@]}" \
  "${ts_catalogs[@]}"

declare -A target_languages=(
  [en]="en_US"
  [it]="it_IT"
  [de]="de_DE"
  [fr]="fr_FR"
  [es]="es_ES"
)

for lang in en it de fr es; do
  ts_file="$TS_DIR/archupdater_${lang}.ts"
  normalized_ts="$tmp_dir/archupdater_${lang}.ts"
  compiled_qm="$tmp_dir/archupdater_${lang}.qm"

  "$LCONVERT" \
    -source-language en_US \
    -target-language "${target_languages[$lang]}" \
    -i "$ts_file" \
    -o "$normalized_ts"
  "$LRELEASE" -silent -fail-on-invalid "$normalized_ts" -qm "$compiled_qm"
  if [[ ! -s "$compiled_qm" ]]; then
    echo "Translation catalog did not produce a QM file: $ts_file" >&2
    exit 1
  fi
done

catalog_state_after="$(sha256sum "${catalogs[@]}")"
if [[ "$catalog_state_before" != "$catalog_state_after" ]]; then
  echo "Translation validation must not modify tracked TS or QM catalogs." >&2
  exit 1
fi
