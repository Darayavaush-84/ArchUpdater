from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from archupdater.domain.enums import UpdateProgressPhase, UpdateSource
from archupdater.domain.update_plan import UpdatePlan
from archupdater.application.update_session.protocol import BatchStep
from archupdater.domain.kde_addons import kde_addon_source_label


Translate = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    source: UpdateSource
    counter_key: str
    batch_step: BatchStep
    progress_phase: UpdateProgressPhase
    counter_title: str
    update_list_title: str
    progress_title: str
    filter_title: str
    default_icon_name: str
    preferred_card_width: int = 120


SOURCE_ORDER = (
    UpdateSource.SYSTEM,
    UpdateSource.AUR,
    UpdateSource.FLATPAK,
    UpdateSource.PLASMA_WIDGET,
    UpdateSource.FIRMWARE,
)

UPDATE_STEP_ORDER = (
    UpdateSource.SYSTEM,
    UpdateSource.AUR,
    UpdateSource.FLATPAK,
    UpdateSource.FIRMWARE,
    UpdateSource.PLASMA_WIDGET,
)


def source_descriptors(translate: Translate) -> dict[UpdateSource, SourceDescriptor]:
    kde_label = kde_addon_source_label(translate)
    return {
        UpdateSource.SYSTEM: SourceDescriptor(
            source=UpdateSource.SYSTEM,
            counter_key=UpdateSource.SYSTEM.counter_field,
            batch_step=BatchStep.SYSTEM,
            progress_phase=UpdateProgressPhase.SYSTEM,
            counter_title=translate("System"),
            update_list_title=translate("Pacman"),
            progress_title=translate("Pacman"),
            filter_title=translate("System Updates"),
            default_icon_name="package-x-generic",
        ),
        UpdateSource.AUR: SourceDescriptor(
            source=UpdateSource.AUR,
            counter_key=UpdateSource.AUR.counter_field,
            batch_step=BatchStep.AUR,
            progress_phase=UpdateProgressPhase.AUR,
            counter_title=translate("AUR"),
            update_list_title=translate("AUR"),
            progress_title=translate("AUR"),
            filter_title=translate("AUR Updates"),
            default_icon_name="package-x-generic",
        ),
        UpdateSource.FLATPAK: SourceDescriptor(
            source=UpdateSource.FLATPAK,
            counter_key=UpdateSource.FLATPAK.counter_field,
            batch_step=BatchStep.FLATPAK,
            progress_phase=UpdateProgressPhase.FLATPAK,
            counter_title=translate("Flatpak"),
            update_list_title=translate("Flatpak"),
            progress_title=translate("Flatpak"),
            filter_title=translate("Flatpak Updates"),
            default_icon_name="application-x-flatpak",
        ),
        UpdateSource.PLASMA_WIDGET: SourceDescriptor(
            source=UpdateSource.PLASMA_WIDGET,
            counter_key=UpdateSource.PLASMA_WIDGET.counter_field,
            batch_step=BatchStep.PLASMA_WIDGET,
            progress_phase=UpdateProgressPhase.PLASMA_WIDGET,
            counter_title=translate("KDE Store"),
            update_list_title=kde_label,
            progress_title=translate("Add-ons"),
            filter_title=translate("KDE Store Add-on Updates"),
            default_icon_name="plasma",
            preferred_card_width=160,
        ),
        UpdateSource.FIRMWARE: SourceDescriptor(
            source=UpdateSource.FIRMWARE,
            counter_key=UpdateSource.FIRMWARE.counter_field,
            batch_step=BatchStep.FIRMWARE,
            progress_phase=UpdateProgressPhase.FIRMWARE,
            counter_title=translate("Firmware"),
            update_list_title=translate("Device Firmware"),
            progress_title=translate("Device Firmware"),
            filter_title=translate("Device Firmware Updates"),
            default_icon_name="drive-removable-media",
        ),
    }


def source_texts(translate: Translate) -> dict[UpdateSource, str]:
    return {
        source: descriptor.update_list_title
        for source, descriptor in source_descriptors(translate).items()
    }


def source_filter_title(source: UpdateSource | None, *, translate: Translate) -> str:
    if source is None:
        return translate("All Updates")
    return source_descriptors(translate)[source].filter_title


def plan_has_source(plan: UpdatePlan, source: UpdateSource) -> bool:
    return plan.has_source(source)
