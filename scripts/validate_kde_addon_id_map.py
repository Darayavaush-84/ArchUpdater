#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEFAULT_MAP = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "archupdater"
    / "resources"
    / "data"
    / "plasma_widgets_id_map.txt"
)


def validate_id_map(path: Path) -> list[str]:
    errors: list[str] = []
    seen_ids: dict[str, int] = {}
    seen_plugins: dict[str, int] = {}
    previous_id = -1

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        data_part, _separator, comment = raw_line.partition("#")
        if "ignored" in comment.casefold():
            continue
        line = data_part.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) != 2:
            errors.append(f"{line_number}: expected '<content-id> <plugin-id>'")
            continue

        content_id, plugin_id = parts
        if not content_id.isdigit():
            errors.append(f"{line_number}: content id is not numeric: {content_id}")
            continue
        numeric_id = int(content_id)
        if numeric_id < previous_id:
            errors.append(f"{line_number}: content id is not sorted: {content_id}")
        previous_id = numeric_id

        if plugin_id in seen_plugins:
            errors.append(
                f"{line_number}: duplicate plugin id {plugin_id} "
                f"(first seen on line {seen_plugins[plugin_id]})"
            )
        if content_id in seen_ids:
            errors.append(
                f"{line_number}: duplicate content id {content_id} "
                f"(first seen on line {seen_ids[content_id]})"
            )
        seen_plugins[plugin_id] = line_number
        seen_ids[content_id] = line_number

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the KDE Store add-on id map.")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_MAP)
    args = parser.parse_args(argv)

    errors = validate_id_map(args.path)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"{args.path}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
