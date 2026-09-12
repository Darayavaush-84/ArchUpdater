#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TS_DIR="$ROOT_DIR/i18n/ts"
QM_DIR="$ROOT_DIR/src/archupdater/i18n/resources"
SOURCE_DIR="$ROOT_DIR/src"
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

mkdir -p "$TS_DIR" "$QM_DIR"

mapfile -t source_files < <(find "$SOURCE_DIR" -type f -name '*.py' -print | sort)
if ((${#source_files[@]} == 0)); then
  echo "No Python source files found below $SOURCE_DIR." >&2
  exit 1
fi

languages=(en it de fr es)
declare -A target_languages=(
  [en]="en_US"
  [it]="it_IT"
  [de]="de_DE"
  [fr]="fr_FR"
  [es]="es_ES"
)
temporary_files=()

cleanup_temporary_files() {
  if ((${#temporary_files[@]})); then
    rm -f -- "${temporary_files[@]}"
  fi
}

trap cleanup_temporary_files EXIT

for lang in "${languages[@]}"; do
  ts_file="$TS_DIR/archupdater_${lang}.ts"
  generated_ts="$(mktemp "$TS_DIR/.archupdater_${lang}.XXXXXXXX.ts")"
  generated_qm="$(mktemp "$QM_DIR/.archupdater_${lang}.XXXXXXXX.qm")"
  temporary_files+=("$generated_ts" "$generated_qm")

  # Existing catalogs predate the language metadata required by current lupdate.
  # Normalize a temporary copy first so lupdate can merge translations instead of
  # returning success while silently refusing to update the file.
  "$LCONVERT" \
    -source-language en_US \
    -target-language "${target_languages[$lang]}" \
    -i "$ts_file" \
    -o "$generated_ts"
  "$LUPDATE" \
    "${source_files[@]}" \
    -no-obsolete \
    -warnings-are-errors \
    -ts "$generated_ts"
  "$LRELEASE" \
    -fail-on-invalid \
    "$generated_ts" \
    -qm "$generated_qm"
done

# Publish the complete set only after every catalog has updated and compiled.
for index in "${!languages[@]}"; do
  lang="${languages[$index]}"
  generated_ts="${temporary_files[$((index * 2))]}"
  generated_qm="${temporary_files[$((index * 2 + 1))]}"
  mv -f -- "$generated_ts" "$TS_DIR/archupdater_${lang}.ts"
  mv -f -- "$generated_qm" "$QM_DIR/archupdater_${lang}.qm"
done

temporary_files=()
