from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.application.update_sources.source_backends import default_preflight_source_registry
from archupdater.domain.enums import UpdateSource


class SourceBackendRegistryTests(unittest.TestCase):
    def test_install_backends_follow_update_step_order(self) -> None:
        registry = default_preflight_source_registry()

        step_keys = [backend.step_key for backend in registry.install_backends()]

        self.assertEqual(
            step_keys,
            ["system", "aur", "flatpak", "firmware", "plasma_widget"],
        )

    def test_check_backends_follow_source_order(self) -> None:
        registry = default_preflight_source_registry()

        sources = [
            backend.source
            for backend in registry.enabled_for_check(
                {
                    UpdateSource.AUR,
                    UpdateSource.FLATPAK,
                    UpdateSource.FIRMWARE,
                    UpdateSource.PLASMA_WIDGET,
                }
            )
        ]

        self.assertEqual(
            sources,
            [
                UpdateSource.SYSTEM,
                UpdateSource.AUR,
                UpdateSource.FLATPAK,
                UpdateSource.PLASMA_WIDGET,
                UpdateSource.FIRMWARE,
            ],
        )


if __name__ == "__main__":
    unittest.main()
