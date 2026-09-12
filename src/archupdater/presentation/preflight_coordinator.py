from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from archupdater.domain.packages import PackageUpdate
from archupdater.domain.update_plan import UpdatePlan
from archupdater.presentation.preflight_dialogs import confirm_preflight_issues
from archupdater.application.updates import UpdateApplication


class UpdatePreflightCoordinator:
    def __init__(
        self,
        *,
        parent: QWidget,
        service: UpdateApplication,
        packages: Callable[[], list[PackageUpdate]],
    ) -> None:
        self._parent = parent
        self._service = service
        self._packages = packages

    def confirm(self, plan: UpdatePlan) -> bool:
        issues = self._service.check_update_preflight(plan, self._packages())
        return confirm_preflight_issues(self._parent, issues)
