from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


class AutostartService:
    DESKTOP_FILE_NAME = "io.github.archupdater.desktop"

    def __init__(self) -> None:
        self._project_root = Path(__file__).resolve().parents[3]
        self._desktop_entry_path = Path.home() / ".config" / "autostart" / self.DESKTOP_FILE_NAME

    def is_enabled(self) -> bool:
        return self._desktop_entry_path.is_file() and not self._desktop_entry_path.is_symlink()

    def set_enabled(self, enabled: bool) -> None:
        if self._desktop_entry_path.is_symlink():
            raise OSError(
                f"Refusing to modify symlinked autostart entry: {self._desktop_entry_path}"
            )
        if enabled:
            self._desktop_entry_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self._desktop_entry_path.parent,
                    prefix=f".{self.DESKTOP_FILE_NAME}.",
                    delete=False,
                ) as handle:
                    temporary_path = Path(handle.name)
                    handle.write(self._desktop_entry_contents())
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary_path.chmod(0o600)
                os.replace(temporary_path, self._desktop_entry_path)
            finally:
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink()
            return

        if self._desktop_entry_path.exists():
            self._desktop_entry_path.unlink()

    def _desktop_entry_contents(self) -> str:
        exec_command = self._resolve_launch_command()
        return "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Version=1.0",
                "Name=ArchUpdater",
                "Comment=Check and install Arch-based system updates",
                f"Exec={exec_command} --start-hidden",
                "Icon=system-software-update",
                "Terminal=false",
                "Categories=System;Utility;",
                "X-GNOME-Autostart-enabled=true",
                "",
            ]
        )

    def _resolve_launch_command(self) -> str:
        argv0 = Path(sys.argv[0]).expanduser()
        if argv0.name == "archupdater" and argv0.exists():
            return self._desktop_quote(str(argv0))

        installed = shutil.which("archupdater")
        if installed:
            return self._desktop_quote(installed)

        python_path = self._desktop_quote(sys.executable)
        main_file = self._project_root / "main.py"
        if main_file.exists():
            main_path = self._desktop_quote(str(main_file))
            return f"{python_path} {main_path}"
        return f"{python_path} -m archupdater"

    def _desktop_quote(self, value: str) -> str:
        if any(character in value for character in ("\x00", "\n", "\r")):
            raise ValueError("Autostart command contains unsupported control characters.")
        escaped = value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
        if any(char.isspace() for char in value):
            return f'"{escaped}"'
        return escaped
