from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.services.command_runner import CommandRunner
from archupdater.services.flatpak import FlatpakUpdateService


class _FlatpakServiceWithAppstream(FlatpakUpdateService):
    def __init__(self, appstream_path: Path) -> None:
        super().__init__(runner=CommandRunner())
        self._test_appstream_path = appstream_path

    def _appstream_path(self, _scope: str, _remote: str, _arch: str) -> Path | None:
        return self._test_appstream_path


class FlatpakReleaseNotesTests(unittest.TestCase):
    def test_release_notes_are_loaded_from_appstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appstream_path = Path(tmp) / "appstream.xml"
            appstream_path.write_text(
                """<components>
                <component>
                  <id>org.example.App</id>
                  <releases>
                    <release version="2.0" date="2026-05-01">
                      <description><p>Fixed startup crash.</p></description>
                    </release>
                  </releases>
                </component>
                </components>""",
                encoding="utf-8",
            )
            service = _FlatpakServiceWithAppstream(appstream_path)

            notes = service._release_notes(
                scope="user",
                remote="flathub",
                ref="app/org.example.App/x86_64/stable",
                application="org.example.App",
            )

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].version, "2.0")
        self.assertEqual(notes[0].date, "2026-05-01")
        self.assertEqual(notes[0].description, "Fixed startup crash.")

    def test_release_timestamp_is_converted_to_utc_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appstream_path = Path(tmp) / "appstream.xml"
            appstream_path.write_text(
                """<components>
                <component>
                  <id>org.example.App</id>
                  <releases>
                    <release version="2.0" timestamp="1767225600" />
                  </releases>
                </component>
                </components>""",
                encoding="utf-8",
            )
            service = _FlatpakServiceWithAppstream(appstream_path)

            notes = service._release_notes(
                scope="system",
                remote="flathub",
                ref="app/org.example.App/x86_64/stable",
                application="org.example.App",
            )

        self.assertEqual(notes[0].date, "2026-01-01")

    def test_appstream_root_never_falls_back_across_installation_scopes(self) -> None:
        service = FlatpakUpdateService(runner=CommandRunner())
        with patch(
            "archupdater.services.flatpak.Path.home",
            return_value=Path("/home/example"),
        ):
            self.assertEqual(
                service._appstream_root("user"),
                Path("/home/example/.local/share/flatpak/appstream"),
            )
        self.assertEqual(
            service._appstream_root("system"),
            Path("/var/lib/flatpak/appstream"),
        )
        self.assertIsNone(service._appstream_root("other"))


if __name__ == "__main__":
    unittest.main()
