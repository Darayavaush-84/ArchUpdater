from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.infrastructure.autostart import AutostartService


class AutostartServiceTests(unittest.TestCase):
    def test_enabling_writes_private_regular_desktop_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AutostartService()
            service._desktop_entry_path = Path(tmp) / "autostart" / service.DESKTOP_FILE_NAME

            service.set_enabled(True)

            self.assertTrue(service.is_enabled())
            self.assertIn("--start-hidden", service._desktop_entry_path.read_text(encoding="utf-8"))
            self.assertEqual(service._desktop_entry_path.stat().st_mode & 0o777, 0o600)

    def test_symlinked_desktop_entry_is_never_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.write_text("keep", encoding="utf-8")
            service = AutostartService()
            service._desktop_entry_path = root / service.DESKTOP_FILE_NAME
            service._desktop_entry_path.symlink_to(target)

            with self.assertRaisesRegex(OSError, "symlinked"):
                service.set_enabled(True)

            self.assertEqual(target.read_text(encoding="utf-8"), "keep")
            self.assertFalse(service.is_enabled())

    def test_enabled_requires_a_runnable_command_and_respects_desktop_disabling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AutostartService()
            service._desktop_entry_path = Path(tmp) / service.DESKTOP_FILE_NAME
            for fields, expected in (
                (f'Exec="{sys.executable}" --start-hidden', True),
                ('Exec=/nonexistent/archupdater --start-hidden', False),
                (f'Exec="{sys.executable}"\nHidden=true', False),
                (f'Exec="{sys.executable}"\nX-GNOME-Autostart-enabled=false', False),
                ('Exec="unterminated', False),
                ('Name=ArchUpdater', False),
            ):
                with self.subTest(fields=fields):
                    service._desktop_entry_path.write_text(
                        '[Desktop Entry]\nType=Application\n' + fields + '\n'
                    )
                    self.assertEqual(service.is_enabled(), expected)

    def test_stale_autostart_is_repaired_once_using_stable_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            launcher = Path(tmp) / 'archupdater'
            launcher.write_text('#!/bin/sh\n')
            launcher.chmod(0o755)
            service = AutostartService()
            service._desktop_entry_path = Path(tmp) / service.DESKTOP_FILE_NAME
            service._desktop_entry_path.write_text(
                '[Desktop Entry]\nType=Application\n'
                'Exec=/missing/old-venv/bin/archupdater --start-hidden\n'
            )
            with patch.object(service, '_resolve_launch_command', return_value=str(launcher)):
                service.repair_stale_entry()
                self.assertTrue(service.is_enabled())
                self.assertIn(f'Exec={launcher} --start-hidden', service._desktop_entry_path.read_text())
                with patch.object(service, 'set_enabled') as write:
                    service.repair_stale_entry()
                    write.assert_not_called()

    def test_repair_migrates_a_still_existing_versioned_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / 'archupdater'
            old.write_text('#!/bin/sh\n')
            old.chmod(0o755)
            service = AutostartService()
            service._desktop_entry_path = Path(tmp) / service.DESKTOP_FILE_NAME
            service._desktop_entry_path.write_text(
                f'[Desktop Entry]\nType=Application\nExec={old} --start-hidden\n'
            )
            with patch.object(service, '_resolve_launch_command', return_value='/stable/archupdater'):
                service.repair_stale_entry()
            self.assertIn('Exec=/stable/archupdater --start-hidden', service._desktop_entry_path.read_text())

    def test_repair_does_not_enable_absent_or_explicitly_disabled_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AutostartService()
            service._desktop_entry_path = Path(tmp) / service.DESKTOP_FILE_NAME
            service.repair_stale_entry()
            self.assertFalse(service._desktop_entry_path.exists())
            for flag in ('Hidden=true', 'X-GNOME-Autostart-enabled=false'):
                contents = ('[Desktop Entry]\nType=Application\n'
                            f'Exec=/missing/archupdater --start-hidden\n{flag}\n')
                service._desktop_entry_path.write_text(contents)
                service.repair_stale_entry()
                self.assertEqual(service._desktop_entry_path.read_text(), contents)

    def test_stable_wrapper_is_preferred_over_running_versioned_entrypoint(self) -> None:
        service = AutostartService()
        with patch('archupdater.infrastructure.autostart.shutil.which',
                   side_effect=lambda name: '/usr/local/bin/archupdater' if name == '/usr/local/bin/archupdater' else None), \
             patch('sys.argv', ['/opt/archupdater/releases/old/venv/bin/archupdater']):
            self.assertEqual(service._resolve_launch_command(), '/usr/local/bin/archupdater')

    def test_config_home_is_respected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'XDG_CONFIG_HOME': tmp}):
            service = AutostartService()
            self.assertEqual(service._desktop_entry_path, Path(tmp) / 'autostart' / service.DESKTOP_FILE_NAME)


if __name__ == "__main__":
    unittest.main()
