from __future__ import annotations

import re


SIZE_RE = re.compile(r"(?P<value>[+-]?\d+(?:[.,]\d+)?)\s*(?P<unit>[KMGT]?i?B|bytes?)", re.IGNORECASE)
UNIT_FACTORS = {
    "B": 1,
    "BYTE": 1,
    "BYTES": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


def parse_size_to_bytes(value: str | None) -> int | None:
    if not value:
        return None
    match = SIZE_RE.search(value.strip())
    if match is None:
        return None
    try:
        number = float(match.group("value").replace(",", "."))
    except ValueError:
        return None
    factor = UNIT_FACTORS.get(match.group("unit").upper())
    if factor is None:
        return None
    return int(number * factor)


def format_size(value: int) -> str:
    sign = "-" if value < 0 else ""
    size = float(abs(value))
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{sign}{int(size)} {units[unit_index]}"
    return f"{sign}{size:.2f} {units[unit_index]}"


def format_size_diff(new_size: str | None, old_size: str | None) -> str | None:
    new_bytes = parse_size_to_bytes(new_size)
    old_bytes = parse_size_to_bytes(old_size)
    if new_bytes is None or old_bytes is None:
        return None
    return format_byte_delta(new_bytes - old_bytes)


def format_byte_delta(delta: int) -> str:
    if delta == 0:
        return "0 B"
    prefix = "+" if delta > 0 else ""
    return f"{prefix}{format_size(delta)}"
