from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.check_results import ArchNewsCheckState
from archupdater.presentation.arch_news_coordinator import ArchNewsCoordinator
from archupdater.presentation.arch_news_dialog import ArchNewsDialogResult


class ArchNewsPolicyTests(unittest.TestCase):
    def _coordinator(self, decisions: list[bool], intros: list[str]) -> ArchNewsCoordinator:
        def show_dialog(_items, **kwargs):  # noqa: ANN001, ANN202
            intros.append(str(kwargs["intro"]))
            return ArchNewsDialogResult(decisions.pop(0), set())

        return ArchNewsCoordinator(
            load_read_ids=set,
            mark_read_in_cache=lambda _items: None,
            delete_items_from_cache=lambda _ids: None,
            show_dialog=show_dialog,
            set_unread_count=lambda _count: None,
            set_notice_text=lambda _text: None,
            clear_notice_text=lambda: None,
            translate=lambda text: text,
        )

    def test_failed_news_check_requires_explicit_override(self) -> None:
        intros: list[str] = []
        coordinator = self._coordinator([False], intros)

        allowed = coordinator.confirm_before_update(
            [],
            check_state=ArchNewsCheckState.FAILED,
        )

        self.assertFalse(allowed)
        self.assertIn("could not be checked", intros[0])

    def test_failed_news_check_can_be_explicitly_overridden(self) -> None:
        coordinator = self._coordinator([True], [])

        self.assertTrue(
            coordinator.confirm_before_update(
                [],
                check_state=ArchNewsCheckState.FAILED,
            )
        )


if __name__ == "__main__":
    unittest.main()
