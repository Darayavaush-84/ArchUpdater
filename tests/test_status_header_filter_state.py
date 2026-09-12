from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import UpdateSource
from archupdater.presentation.status_header_filter_state import StatusHeaderFilterState


class StatusHeaderFilterStateTests(unittest.TestCase):
    def test_firmware_is_visible_only_when_selectable_and_non_empty(self) -> None:
        state = StatusHeaderFilterState()

        self.assertNotIn(UpdateSource.FIRMWARE, state.visible_sources)

        state.set_counter_values({UpdateSource.FIRMWARE: 1})

        self.assertIn(UpdateSource.FIRMWARE, state.visible_sources)

        state.set_selectable_sources({UpdateSource.SYSTEM})

        self.assertNotIn(UpdateSource.FIRMWARE, state.visible_sources)

    def test_toggle_ignores_hidden_source(self) -> None:
        state = StatusHeaderFilterState()

        toggle = state.toggle_source_filter(UpdateSource.FIRMWARE)

        self.assertFalse(toggle.changed)
        self.assertIsNone(toggle.active_source)

    def test_toggle_activates_and_clears_visible_source(self) -> None:
        state = StatusHeaderFilterState()

        first = state.toggle_source_filter(UpdateSource.AUR)
        second = state.toggle_source_filter(UpdateSource.AUR)

        self.assertTrue(first.changed)
        self.assertEqual(first.active_source, UpdateSource.AUR)
        self.assertTrue(second.changed)
        self.assertIsNone(second.active_source)

    def test_hidden_active_source_is_cleared_when_inputs_change(self) -> None:
        state = StatusHeaderFilterState()
        state.toggle_source_filter(UpdateSource.AUR)

        cleared = state.set_selectable_sources({UpdateSource.SYSTEM})

        self.assertTrue(cleared)
        self.assertIsNone(state.active_source_filter)


if __name__ == "__main__":
    unittest.main()
