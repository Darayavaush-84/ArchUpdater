from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.batch.translations import TRANSLATION_MARKERS


class BatchTranslationMarkersTests(unittest.TestCase):
    def test_current_batch_completion_markers_are_present(self) -> None:
        expected_markers = {
            "Selected updates completed with skipped items.",
            "No selected updates were installed.",
            "Incomplete",
        }

        self.assertLessEqual(expected_markers, set(TRANSLATION_MARKERS))

    def test_legacy_generic_aur_prompt_markers_are_absent(self) -> None:
        legacy_markers = {
            "Choose AUR provider",
            "Confirm AUR action",
            "AUR input required",
            "AUR update cancelled.",
            "The AUR helper found multiple packages that can satisfy a dependency. "
            "Choose one provider to continue.",
            "The AUR helper needs confirmation before it can continue.",
            "The AUR helper needs additional input before it can continue.",
            "No supported AUR helper is available.",
            "Requesting administrator authorization for privileged update step.",
        }

        self.assertTrue(legacy_markers.isdisjoint(TRANSLATION_MARKERS))


if __name__ == "__main__":
    unittest.main()
