from __future__ import annotations

from collections.abc import Callable

from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import UpdatePlan
from archupdater.application.update_sources.descriptors import UPDATE_STEP_ORDER, plan_has_source, source_descriptors


Translate = Callable[[str], str]


class BatchPlanInspector:
    def __init__(
        self,
        plan: UpdatePlan,
        *,
        translate: Translate,
    ) -> None:
        self._plan = plan
        self._t = translate

    def selected_steps(self) -> list[tuple[str, str]]:
        descriptors = source_descriptors(self._t)
        return [
            (descriptors[source].batch_step.value, descriptors[source].update_list_title)
            for source in UPDATE_STEP_ORDER
            if plan_has_source(self._plan, source)
        ]

    def step_position(self, step: str) -> tuple[int, int]:
        steps = self.selected_steps()
        total = max(1, len(steps))
        for index, (step_name, _label) in enumerate(steps, start=1):
            if step_name == step:
                return index, total
        return total, total

    def banner_lines(self) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        system_targets = self._plan.target_ids(UpdateSource.SYSTEM)
        if system_targets:
            lines.append(
                (
                    self._t("Pacman"),
                    self.count_summary(
                        len(system_targets),
                        singular=self._t("1 package"),
                        plural=self._t("{count} packages"),
                    ),
                )
            )
        aur_targets = self._plan.target_ids(UpdateSource.AUR)
        if aur_targets:
            lines.append(
                (
                    self._t("AUR"),
                    self.count_summary(
                        len(aur_targets),
                        singular=self._t("1 package"),
                        plural=self._t("{count} packages"),
                    ),
                )
            )
        system_refs = self._plan.flatpak_refs("system")
        if system_refs:
            lines.append(
                (
                    self._t("Flatpak (system)"),
                    self.count_summary(
                        len(system_refs),
                        singular=self._t("1 update"),
                        plural=self._t("{count} updates"),
                    ),
                )
            )
        user_refs = self._plan.flatpak_refs("user")
        if user_refs:
            lines.append(
                (
                    self._t("Flatpak (user)"),
                    self.count_summary(
                        len(user_refs),
                        singular=self._t("1 update"),
                        plural=self._t("{count} updates"),
                    ),
                )
            )
        firmware_targets = self._plan.target_ids(UpdateSource.FIRMWARE)
        if firmware_targets:
            lines.append(
                (
                    self._t("Firmware"),
                    self.count_summary(
                        len(firmware_targets),
                        singular=self._t("1 device"),
                        plural=self._t("{count} devices"),
                    ),
                )
            )

        widget_count = len(self._plan.update_items(UpdateSource.PLASMA_WIDGET))
        if widget_count:
            lines.append(
                (
                    self._t("KDE Store Add-ons"),
                    self.count_summary(
                        widget_count,
                        singular=self._t("1 add-on"),
                        plural=self._t("{count} add-ons"),
                    ),
                )
            )
        return lines

    def requires_privileged_auth(self) -> bool:
        return bool(
            self._plan.target_ids(UpdateSource.SYSTEM)
            or self._plan.target_ids(UpdateSource.AUR)
            or self._plan.target_ids(UpdateSource.FIRMWARE)
        )

    def count_summary(self, count: int, *, singular: str, plural: str) -> str:
        if count == 1:
            return singular
        return plural.format(count=count)

    def summarize_items(self, items: list[str], *, limit: int = 4) -> str:
        if len(items) <= limit:
            return ", ".join(items)
        visible = ", ".join(items[:limit])
        return self._t("{visible} (+{remaining} more)").format(
            visible=visible,
            remaining=len(items) - limit,
        )
