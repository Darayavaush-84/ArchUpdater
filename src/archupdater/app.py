from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QStyle

from .i18n.manager import TranslationManager
from .infrastructure.autostart import AutostartService
from .infrastructure.single_instance import SingleInstanceGuard
from .infrastructure.settings import SettingsService
from .presentation.main_window import MainWindow
from .presentation.tray_controller import TrayController
from .presentation.theme import build_application_stylesheet


def main() -> int:
    argv = list(sys.argv)
    start_hidden = "--start-hidden" in argv
    filtered_argv = [arg for arg in argv if arg != "--start-hidden"]

    app = QApplication(filtered_argv)
    app.setApplicationName("ArchUpdater")
    app.setOrganizationName("ArchUpdater")
    app.setDesktopFileName("io.github.archupdater")
    app.setFont(QFont("Noto Sans", 10))
    app.setStyleSheet(build_application_stylesheet(app.palette()))
    app_icon = QIcon.fromTheme("system-software-update")
    if app_icon.isNull():
        app_icon = app.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
    app.setWindowIcon(app_icon)

    should_activate_existing = not start_hidden
    if SingleInstanceGuard.notify_existing(activate=should_activate_existing):
        return 0

    single_instance_guard = SingleInstanceGuard(parent=app)
    if not single_instance_guard.acquire():
        SingleInstanceGuard.notify_existing(activate=should_activate_existing)
        return 0

    try:
        AutostartService().repair_stale_entry()
    except OSError:
        logging.getLogger(__name__).warning("Could not repair the autostart entry", exc_info=True)

    settings = SettingsService()
    app_settings = settings.load_app_settings()
    translation_manager = TranslationManager(app)
    translation_manager.install(app_settings.language_preference)

    window = MainWindow(settings=settings, translation_manager=translation_manager)

    def restart_application() -> bool:
        single_instance_guard.close()
        started, _pid = QProcess.startDetached("/usr/local/bin/archupdater", [])
        if not started:
            single_instance_guard.acquire()
            return False
        app.quit()
        return True

    window.restart_application = restart_application
    window.setWindowIcon(app_icon)
    app.aboutToQuit.connect(window.update_controller.shutdown)
    tray_controller = TrayController(
        app=app,
        window=window,
        update_controller=window.update_controller,
        enabled=app_settings.systray_enabled,
        notifications_enabled=app_settings.systray_notifications_enabled,
        parent=app,
    )
    window.set_tray_controller(tray_controller)
    single_instance_guard.activated.connect(window.show_from_tray)
    tray_controller.show_if_enabled()

    if start_hidden and app_settings.systray_enabled:
        # Allow Plasma's tray to arrive during login, then provide a visible
        # fallback on desktops without a tray. Never hide a manually opened window.
        QTimer.singleShot(3000, lambda: window.show() if not tray_controller.is_active() else None)
    else:
        window.show()

    return app.exec()
