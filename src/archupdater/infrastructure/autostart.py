from __future__ import annotations

import configparser
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path


class AutostartService:
    DESKTOP_FILE_NAME = "io.github.archupdater.desktop"

    def __init__(self) -> None:
        self._project_root = Path(__file__).resolve().parents[3]
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        if not config_home.is_absolute():
            config_home = Path.home() / ".config"
        self._desktop_entry_path = config_home / "autostart" / self.DESKTOP_FILE_NAME

    def is_enabled(self) -> bool:
        entry = self._read_enabled_entry()
        return entry is not None and self._launch_command_available(entry.get("Exec", ""))

    def repair_stale_entry(self) -> None:
        """Migrate an existing entry after a launcher move; respect desktop disabling."""
        entry = self._read_enabled_entry()
        if entry is None:
            return
        command = entry.get("Exec", "")
        expected_command = f"{self._resolve_launch_command()} --start-hidden"
        if command == expected_command:
            return
        if self._launch_command_available(command):
            arguments = shlex.split(command)
            if len(arguments) != 2 or Path(arguments[0]).name != "archupdater" or arguments[1] != "--start-hidden":
                return
        self.set_enabled(True)

    def _read_enabled_entry(self) -> configparser.SectionProxy | None:
        if not self._desktop_entry_path.is_file() or self._desktop_entry_path.is_symlink():
            return None
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(self._desktop_entry_path.read_text(encoding="utf-8"))
            entry = parser["Desktop Entry"]
            if (
                entry.get("Type") != "Application"
                or entry.getboolean("Hidden", fallback=False)
                or not entry.getboolean("X-GNOME-Autostart-enabled", fallback=True)
            ):
                return None
            return entry
        except (OSError, UnicodeError, configparser.Error, KeyError, ValueError):
            return None

    def _launch_command_available(self, command: str) -> bool:
        try:
            arguments = shlex.split(command)
        except ValueError:
            return False
        if not arguments:
            return False
        executable = arguments[0].replace("%%", "%")
        return shutil.which(executable) is not None

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
        # The wrapper survives replacement/removal of versioned virtualenvs.
        installed = shutil.which("/usr/local/bin/archupdater") or shutil.which("archupdater")
        if installed:
            return self._desktop_quote(installed)

        argv0 = Path(sys.argv[0]).expanduser().absolute()
        if argv0.name == "archupdater" and os.access(argv0, os.X_OK):
            return self._desktop_quote(str(argv0))

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
