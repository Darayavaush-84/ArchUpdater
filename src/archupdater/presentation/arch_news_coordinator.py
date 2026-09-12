from __future__ import annotations

from collections.abc import Callable, Sequence

from archupdater.domain.arch_news import ArchNewsItem
from archupdater.domain.check_results import ArchNewsCheckState
from archupdater.presentation.arch_news_dialog import ArchNewsDialogResult


class ArchNewsCoordinator:
    def __init__(
        self,
        *,
        load_read_ids: Callable[[], set[str]],
        mark_read_in_cache: Callable[[list[ArchNewsItem]], None],
        delete_items_from_cache: Callable[[set[str]], None],
        show_dialog: Callable[..., ArchNewsDialogResult],
        set_unread_count: Callable[[int], None],
        set_notice_text: Callable[[str], None],
        clear_notice_text: Callable[[], None],
        translate: Callable[[str], str],
    ) -> None:
        self._load_read_ids = load_read_ids
        self._mark_read_in_cache = mark_read_in_cache
        self._delete_items_from_cache = delete_items_from_cache
        self._show_dialog = show_dialog
        self._set_unread_count = set_unread_count
        self._set_notice_text = set_notice_text
        self._clear_notice_text = clear_notice_text
        self._t = translate

    def apply_read_state(self, items: Sequence[ArchNewsItem]) -> None:
        read_ids = self._load_read_ids()
        for item in items:
            item.read = item.item_id in read_ids
        self._set_unread_count(len(self.unread_items(items)))

    def unread_items(self, items: Sequence[ArchNewsItem]) -> list[ArchNewsItem]:
        return [item for item in items if not item.read]

    def mark_read(
        self,
        items: Sequence[ArchNewsItem],
        *,
        all_items: Sequence[ArchNewsItem] | None = None,
    ) -> None:
        unread = list(items)
        if not unread:
            self._set_unread_count(len(self.unread_items(all_items or unread)))
            return
        self._mark_read_in_cache(unread)
        for item in unread:
            item.read = True
        self._clear_notice_text()
        self._set_unread_count(len(self.unread_items(all_items or unread)))

    def open_news(self, items: Sequence[ArchNewsItem]) -> None:
        unread = self.unread_items(items)
        result = self._show_dialog(
            items,
            intro=self._t("Arch Linux news items from the latest check."),
            ok_text=self._t("Mark as Read"),
            cancel_text=self._t("Close"),
            include_cancel=False,
            enable_ok=bool(unread),
        )
        self._delete_read_items(result.deleted_read_ids, items)
        if result.accepted:
            self.mark_read(unread, all_items=items)

    def confirm_before_update(
        self,
        items: Sequence[ArchNewsItem],
        *,
        check_state: ArchNewsCheckState = ArchNewsCheckState.LOADED,
    ) -> bool:
        if check_state is ArchNewsCheckState.FAILED:
            result = self._show_dialog(
                items,
                intro=self._t(
                    "Arch Linux news could not be checked. Continuing may miss required manual intervention."
                ),
                ok_text=self._t("Continue Anyway"),
                cancel_text=self._t("Cancel"),
                include_cancel=True,
                enable_ok=True,
            )
            self._delete_read_items(result.deleted_read_ids, items)
            if not result.accepted:
                return False
        unread = self.unread_items(items)
        if not unread:
            return True
        result = self._show_dialog(
            items,
            intro=self._t(
                "There are unread Arch Linux news items. Review them before installing updates."
            ),
            ok_text=self._t("Continue"),
            cancel_text=self._t("Cancel"),
            include_cancel=True,
            enable_ok=True,
        )
        self._delete_read_items(result.deleted_read_ids, items)
        if not result.accepted:
            return False
        self.mark_read(unread, all_items=items)
        return True

    def show_notice(self, items: Sequence[ArchNewsItem]) -> None:
        unread_count = len(self.unread_items(items))
        self._set_unread_count(unread_count)
        if unread_count <= 0:
            return
        self._set_notice_text(
            self._t("{count} unread Arch Linux news item(s) may affect updates.").format(
                count=unread_count
            )
        )

    def _delete_read_items(
        self,
        item_ids: set[str],
        items: Sequence[ArchNewsItem],
    ) -> None:
        if not item_ids:
            return
        self._delete_items_from_cache(item_ids)
        if isinstance(items, list):
            items[:] = [item for item in items if item.item_id not in item_ids]
        self._set_unread_count(len(self.unread_items(items)))
