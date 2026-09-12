from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from PySide6.QtCore import QCoreApplication

from archupdater.domain.enums import UpdateSource
from archupdater.domain.optional_sources import OptionalSourceStatus, OptionalSourcesSnapshot
from archupdater.services.firmware import FirmwareDeviceSupportProbe, FirmwareProbeFn


WhichFn = Callable[[str], str | None]
AurEnabledProvider = Callable[[], bool]
AurEnabledSetter = Callable[[bool], None]


@dataclass(slots=True)
class OptionalSourcesService:
    which: WhichFn = shutil.which
    home_dir: Path = field(default_factory=Path.home)
    env: Mapping[str, str] | None = None
    firmware_probe: FirmwareProbeFn | None = None
    firmware_support_probe: FirmwareDeviceSupportProbe | None = None
    aur_enabled_provider: AurEnabledProvider = lambda: False
    aur_enabled_setter: AurEnabledSetter | None = None

    _AUR_HELPERS = ("paru", "yay", "pikaur")
    _MANAGED_PACKAGE_MAP = {
        UpdateSource.FLATPAK: ["flatpak"],
        UpdateSource.FIRMWARE: ["fwupd"],
    }

    def snapshot(self) -> OptionalSourcesSnapshot:
        statuses = {
            UpdateSource.AUR: self._aur_status(),
            UpdateSource.FLATPAK: self._binary_source_status(
                source=UpdateSource.FLATPAK,
                binary_name="flatpak",
                installed_text=self._translate("Installed"),
                missing_text=self._translate("Missing"),
            ),
            UpdateSource.PLASMA_WIDGET: self._plasma_widgets_status(),
            UpdateSource.FIRMWARE: self._firmware_status(),
        }
        return OptionalSourcesSnapshot(statuses=statuses)

    def _aur_status(self) -> OptionalSourceStatus:
        installed_helpers = [helper for helper in self._AUR_HELPERS if self.which(helper)]
        installed = bool(installed_helpers)
        active = installed and self.aur_enabled_provider()
        if active:
            status_text = self._translate("Enabled ({helpers})").format(
                helpers=", ".join(installed_helpers)
            )
        elif installed:
            status_text = self._translate("Installed, disabled in ArchUpdater ({helpers})").format(
                helpers=", ".join(installed_helpers)
            )
        else:
            status_text = self._translate(
                "Missing; install an AUR helper manually, then reopen this page"
            )
        return OptionalSourceStatus(
            source=UpdateSource.AUR,
            installed=installed,
            active=active,
            status_text=status_text,
            installable_packages=[],
            removable_packages=[],
        )

    def set_aur_enabled(self, enabled: bool) -> None:
        if self.aur_enabled_setter is None:
            raise RuntimeError(
                self._translate("AUR preference persistence is unavailable.")
            )
        self.aur_enabled_setter(enabled)

    def _firmware_status(self) -> OptionalSourceStatus:
        installed = self.which("fwupdmgr") is not None
        if not installed:
            return OptionalSourceStatus(
                source=UpdateSource.FIRMWARE,
                installed=False,
                active=False,
                status_text=self._translate("Missing"),
                installable_packages=list(self._MANAGED_PACKAGE_MAP[UpdateSource.FIRMWARE]),
                removable_packages=[],
            )

        support_available = self._probe_firmware_device_support()
        if support_available is True:
            status_text = self._translate("Installed, ready to check device firmware")
        elif support_available is False:
            status_text = self._translate("Installed, no compatible firmware devices detected")
        else:
            status_text = self._translate("Installed, device support unavailable")

        return OptionalSourceStatus(
            source=UpdateSource.FIRMWARE,
            installed=True,
            active=True,
            status_text=status_text,
            installable_packages=[],
            removable_packages=list(self._MANAGED_PACKAGE_MAP[UpdateSource.FIRMWARE]),
        )

    def _probe_firmware_device_support(self) -> bool | None:
        return self._firmware_support_probe().detect_supported_devices()

    def _firmware_support_probe(self) -> FirmwareDeviceSupportProbe:
        return self.firmware_support_probe or FirmwareDeviceSupportProbe(run=self.firmware_probe)

    def _binary_source_status(
        self,
        *,
        source: UpdateSource,
        binary_name: str,
        installed_text: str,
        missing_text: str,
        manageable: bool = True,
    ) -> OptionalSourceStatus:
        installed = self.which(binary_name) is not None
        installable_packages = []
        removable_packages = []
        if manageable:
            packages = list(self._MANAGED_PACKAGE_MAP[source])
            installable_packages = [] if installed else packages
            removable_packages = packages if installed else []
        return OptionalSourceStatus(
            source=source,
            installed=installed,
            active=installed,
            status_text=installed_text if installed else missing_text,
            installable_packages=installable_packages,
            removable_packages=removable_packages,
        )

    def _plasma_widgets_status(self) -> OptionalSourceStatus:
        installed = self.which("kpackagetool6") is not None
        active = installed and (self._has_plasma_session() or self._has_local_plasma_widgets())
        if not installed:
            status_text = self._translate("Missing")
        elif active:
            status_text = self._translate("Installed")
        else:
            status_text = self._translate("Installed but inactive")
        return OptionalSourceStatus(
            source=UpdateSource.PLASMA_WIDGET,
            installed=installed,
            active=active,
            status_text=status_text,
        )

    def _has_plasma_session(self) -> bool:
        environment = self.env or os.environ
        desktop = environment.get("XDG_CURRENT_DESKTOP", "").upper()
        session = environment.get("DESKTOP_SESSION", "").upper()
        return "KDE" in desktop or "PLASMA" in desktop or "PLASMA" in session

    def _has_local_plasma_widgets(self) -> bool:
        base = self.home_dir / ".local" / "share"
        roots = (
            base / "plasma" / "plasmoids",
            base / "plasma" / "wallpapers",
            base / "kwin" / "effects",
            base / "kwin" / "scripts",
        )
        for root in roots:
            try:
                if root.is_dir() and next(root.iterdir(), None) is not None:
                    return True
            except OSError:
                continue
        return False

    def _translate(self, text: str) -> str:
        return QCoreApplication.translate("OptionalSourcesService", text)
