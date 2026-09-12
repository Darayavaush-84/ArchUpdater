from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


MessageKey = tuple[str, str, str, str, str]


def message_keys(path: Path) -> set[MessageKey]:
    root = ET.parse(path).getroot()
    keys: set[MessageKey] = set()
    for context in root.findall("context"):
        context_name = context.findtext("name") or ""
        for message in context.findall("message"):
            keys.add(_message_key(context_name, message))
    return keys


def unfinished_message_keys(path: Path) -> set[MessageKey]:
    root = ET.parse(path).getroot()
    keys: set[MessageKey] = set()
    for context in root.findall("context"):
        context_name = context.findtext("name") or ""
        for message in context.findall("message"):
            translation = message.find("translation")
            translated_text = "" if translation is None else "".join(translation.itertext())
            if (
                translation is None
                or translation.attrib.get("type") == "unfinished"
                or not translated_text.strip()
            ):
                keys.add(_message_key(context_name, message))
    return keys


def catalog_debt(catalog: Path, fresh_catalog: Path) -> dict[str, set[MessageKey]]:
    catalog_messages = message_keys(catalog)
    source_messages = message_keys(fresh_catalog)
    return {
        "missing": source_messages - catalog_messages,
        "stale": catalog_messages - source_messages,
        "unfinished": unfinished_message_keys(catalog),
    }


def report_catalog_debt(catalogs: list[Path], fresh_catalog: Path) -> bool:
    has_debt = False
    for catalog in catalogs:
        debt = catalog_debt(catalog, fresh_catalog)
        counts = {kind: len(keys) for kind, keys in debt.items()}
        catalog_has_debt = any(counts.values())
        has_debt = has_debt or catalog_has_debt
        status = "STALE" if catalog_has_debt else "synchronized"
        print(
            f"{catalog.name}: {status}; missing={counts['missing']}, "
            f"stale={counts['stale']}, unfinished={counts['unfinished']}."
        )
    return has_debt


def _message_key(context_name: str, message: ET.Element) -> MessageKey:
    return (
        context_name,
        message.findtext("source") or "",
        message.findtext("comment") or "",
        message.attrib.get("id", ""),
        message.attrib.get("numerus", ""),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Qt catalogs against extracted source messages without rewriting them."
    )
    parser.add_argument("--fresh", required=True, type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when source messages are missing/stale or translations are unfinished.",
    )
    parser.add_argument("catalogs", nargs="+", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        has_debt = report_catalog_debt(args.catalogs, args.fresh)
    except (OSError, ET.ParseError) as exc:
        print(f"Translation source validation failed: {exc}", file=sys.stderr)
        return 1
    if has_debt and args.strict:
        print("Translation catalogs are not synchronized with the current sources.", file=sys.stderr)
        return 1
    if has_debt:
        print(
            "WARNING: translation catalogs contain the source debt reported above; "
            "strict mode would fail.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
