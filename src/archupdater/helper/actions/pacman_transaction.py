"""Read the transaction printed by the running pacman, without another DB refresh."""
from __future__ import annotations

import re


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_HEADER = re.compile(r"^Packages? \((\d+)\)")
_NAME = re.compile(r"[A-Za-z0-9@._+-]+")


class PacmanTransactionPreview:
    MAX_CHARACTERS = 128 * 1024

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._characters = 0
        self._collecting = False
        self.truncated = False

    def observe(self, line: str) -> None:
        line = _ANSI.sub("", line).rstrip()
        if _HEADER.match(line):
            self.lines.clear()
            self._characters = 0
            self.truncated = False
            self._collecting = True
        if line.startswith(("Total Download Size:", "Total Installed Size:",
                            "Total Removed Size:", "Net Upgrade Size:")):
            self._collecting = False
        if not self._collecting:
            return
        self._characters += len(line) + 1
        if self._characters > self.MAX_CHARACTERS:
            self.truncated = True
            return
        self.lines.append(line)

    def versions(self) -> dict[str, str] | None:
        if not self.lines or self.truncated:
            return None
        header = self.lines[0]
        match = _HEADER.match(header)
        assert match is not None
        expected_count = int(match[1])
        versions: dict[str, str] = {}
        if header.startswith("Packages ("):
            for token in " ".join([header[match.end():], *self.lines[1:]]).split():
                parts = token.rsplit("-", 2)
                if len(parts) != 3:
                    return None
                name, pkgver, pkgrel = parts
                if not _NAME.fullmatch(name) or not pkgver or not pkgrel or name in versions:
                    return None
                versions[name] = f"{pkgver}-{pkgrel}"
        else:
            # VerbosePkgLists aligns these columns, including empty old/new versions.
            try:
                old_column = header.index("Old Version")
                new_column = header.index("New Version")
                size_column = header.index("Net Change")
            except ValueError:
                return None
            for line in self.lines[1:]:
                if not line.strip():
                    continue
                name = line[:old_column].strip().rsplit("/", 1)[-1]
                version = line[new_column:size_column].strip()
                if (not _NAME.fullmatch(name) or not version
                        or any(c.isspace() for c in version) or name in versions):
                    return None
                versions[name] = version
        # Removals, missing/duplicate rows and unknown formats require review.
        return versions if versions and len(versions) == expected_count else None

    def details(self) -> str:
        return "\n".join(self.lines)
