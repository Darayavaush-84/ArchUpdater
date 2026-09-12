"""Qt extraction markers for strings translated through injected callbacks.

Keep these in sync with the source locations noted below; no Qt imports are needed
in application or domain code to make those messages translatable.
"""

from PySide6.QtCore import QT_TRANSLATE_NOOP

TRANSLATION_MARKERS = (
    # application/preflight.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Missing command: pkexec"),
    # application/preflight.py, application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Required tool is missing"),
    # application/preflight.py
    QT_TRANSLATE_NOOP(
        "UpdatePreflightService", "Privileged update steps need the ArchUpdater helper."
    ),
    # application/preflight.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Free disk space is low on {path}."),
    # application/preflight.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Missing helper: {path}"),
    # application/preflight.py
    QT_TRANSLATE_NOOP(
        "UpdatePreflightService", "{message} Selected downloads report about {size}."
    ),
    # application/preflight.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Low disk space"),
    # application/preflight.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Available: {size}"),
    # application/update_sources/check_coordinator.py
    QT_TRANSLATE_NOOP("UpdateService", "Checking Arch Linux news..."),
    # application/update_sources/check_coordinator.py
    QT_TRANSLATE_NOOP("UpdateService", "Completed"),
    # application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "All Updates"),
    # application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "System"),
    # application/update_sources/descriptors.py, application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "Pacman"),
    # application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "System Updates"),
    # application/update_sources/descriptors.py, application/update_sources/descriptors.py, application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "AUR"),
    # application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "AUR Updates"),
    # application/update_sources/descriptors.py, application/update_sources/descriptors.py, application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "Flatpak"),
    # application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "Flatpak Updates"),
    # application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "KDE Store"),
    # application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "Add-ons"),
    # application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "KDE Store Add-on Updates"),
    # application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "Firmware"),
    # application/update_sources/descriptors.py, application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "Device Firmware"),
    # application/update_sources/descriptors.py
    QT_TRANSLATE_NOOP("UpdateService", "Device Firmware Updates"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "Updates"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "Checking pacman updates..."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "Pacman updates"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "Checking AUR updates..."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "AUR updates"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "Checking Flatpak updates..."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "Flatpak updates"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "Checking KDE Store add-on updates..."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "KDE Store add-on updates"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "Checking device firmware updates..."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "Device firmware updates"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "Unknown error."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Pacman is already running"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP(
        "UpdatePreflightService",
        "A pacman database lock is present. Close other package operations before updating.",
    ),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "KDE Store add-on updates need kpackagetool6."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Pacman configuration is not readable"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP(
        "UpdatePreflightService", "Pacman architecture configuration could not be read."
    ),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdateService", "{source} could not be checked: {details}"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Missing command: {command}"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "System package updates need pacman."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "System package updates need pacman-conf."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Command failed: pacman-conf Architecture"),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "AUR updates need pacman."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "AUR updates need git."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "AUR updates need makepkg."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Flatpak updates need flatpak."),
    # application/update_sources/source_backends.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Device firmware updates need fwupdmgr."),
    # domain/kde_addons.py, presentation/update_progress_model.py
    QT_TRANSLATE_NOOP("MainWindow", "KDE Store Add-ons"),
    # domain/kde_addons.py
    QT_TRANSLATE_NOOP("MainWindow", "Plasma Widget"),
    # domain/kde_addons.py
    QT_TRANSLATE_NOOP("MainWindow", "Wallpaper"),
    # domain/kde_addons.py
    QT_TRANSLATE_NOOP("MainWindow", "KWin Effect"),
    # domain/kde_addons.py
    QT_TRANSLATE_NOOP("MainWindow", "KWin Script"),
    # presentation/arch_news_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Arch Linux news items from the latest check."),
    # presentation/arch_news_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Mark as Read"),
    # presentation/arch_news_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Close"),
    # presentation/arch_news_coordinator.py
    QT_TRANSLATE_NOOP(
        "MainWindow",
        "There are unread Arch Linux news items. Review them before installing updates.",
    ),
    # presentation/arch_news_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Continue"),
    # presentation/arch_news_coordinator.py, presentation/arch_news_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Cancel"),
    # presentation/arch_news_coordinator.py
    QT_TRANSLATE_NOOP(
        "MainWindow",
        "Arch Linux news could not be checked. Continuing may miss required manual intervention.",
    ),
    # presentation/arch_news_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Continue Anyway"),
    # presentation/arch_news_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "{count} unread Arch Linux news item(s) may affect updates."),
    # presentation/background_behavior.py
    QT_TRANSLATE_NOOP("MainWindow", "Automatic update checks disabled."),
    # presentation/background_behavior.py
    QT_TRANSLATE_NOOP("MainWindow", "Automatic checks set to every {hours} hours."),
    # presentation/main_window/logic.py, presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Starting update session..."),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Installing updates"),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Running pacman update..."),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Updating pacman packages"),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Running AUR update..."),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Updating AUR packages"),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Running Flatpak update..."),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Updating Flatpak apps"),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Running firmware update..."),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Updating firmware"),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Running KDE Store add-on update..."),
    # presentation/main_window/logic.py
    QT_TRANSLATE_NOOP("MainWindow", "Updating KDE Store add-ons"),
    # presentation/package_details_presenter.py
    QT_TRANSLATE_NOOP("MainWindow", "Package Details"),
    # presentation/package_details_presenter.py
    QT_TRANSLATE_NOOP("MainWindow", "Not available"),
    # presentation/package_details_presenter.py
    QT_TRANSLATE_NOOP("MainWindow", "No description provided."),
    # presentation/plasma_restart_coordinator.py
    QT_TRANSLATE_NOOP(
        "MainWindow",
        "KDE Store add-ons were updated. Restart plasmashell manually to fully apply the changes.",
    ),
    # presentation/plasma_restart_coordinator.py, presentation/plasma_restart_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Plasma shell could not be restarted automatically."),
    # presentation/plasma_restart_coordinator.py, presentation/plasma_restart_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Plasma shell restart requested successfully."),
    # presentation/preferences_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Preferences Saved"),
    # presentation/preferences_coordinator.py
    QT_TRANSLATE_NOOP(
        "MainWindow",
        "Language preference saved as {language}. Restart ArchUpdater to apply the new language.",
    ),
    # presentation/preferences_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Startup Preference Failed"),
    # presentation/preferences_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "ArchUpdater will start automatically when you sign in."),
    # presentation/preferences_coordinator.py
    QT_TRANSLATE_NOOP(
        "MainWindow", "ArchUpdater will no longer start automatically when you sign in."
    ),
    # presentation/preferences_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Could not update the startup preference: {error}"),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Checking for updates..."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Update check failed. Open ArchUpdater."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Selected updates completed. Refreshing update status..."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Unknown error."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "1 update is ready to install."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "ArchUpdater: Refreshing update status..."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "ArchUpdater: Last check failed"),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "ArchUpdater: Up to date"),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "ArchUpdater"),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "ArchUpdater: 1 update available"),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Waiting for authentication..."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Installing system updates..."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Installing AUR updates..."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Installing Flatpak updates..."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Installing firmware updates..."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Installing KDE Store add-ons..."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "ArchUpdater: {count} updates available"),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "{count} updates are ready to install."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "ArchUpdater: {status}"),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "{count} ignored by pacman.conf."),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Ignored by pacman.conf: {count}"),
    # presentation/tray_status.py
    QT_TRANSLATE_NOOP("MainWindow", "Next check: {time}"),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Updates installed"),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Some selected updates were skipped."),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Updates installed with skipped items"),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "No selected updates were installed."),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "No updates installed"),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Authentication cancelled"),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Update failed"),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "The update was cancelled."),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "Update cancelled"),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "The system upgrade could not be completed"),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP(
        "MainWindow",
        "Pacman could not complete the full system transaction.\n\nThere may be a dependency, mirror, signature, or package conflict.\n\nReview the live activity log before trying again.",
    ),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "System update completed."),
    # presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "System update completed successfully."),
    # presentation/update_completion_coordinator.py, presentation/update_completion_coordinator.py
    QT_TRANSLATE_NOOP("MainWindow", "System update failed."),
    # presentation/update_progress_model.py
    QT_TRANSLATE_NOOP("MainWindow", "Session Summary"),
    # presentation/update_progress_model.py
    QT_TRANSLATE_NOOP(
        "MainWindow",
        "{count} selected. Some add-ons may need a plasmashell restart after installation.",
    ),
    # presentation/update_progress_model.py, presentation/update_progress_model.py, presentation/update_progress_model.py, presentation/update_progress_model.py, presentation/update_progress_model.py
    QT_TRANSLATE_NOOP("MainWindow", "Installing Updates"),
    # presentation/update_progress_model.py
    QT_TRANSLATE_NOOP("MainWindow", "Running the full Pacman system upgrade"),
    # presentation/update_progress_model.py
    QT_TRANSLATE_NOOP("MainWindow", "Installing selected AUR packages"),
    # presentation/update_progress_model.py
    QT_TRANSLATE_NOOP("MainWindow", "Applying selected Flatpak updates"),
    # presentation/update_progress_model.py
    QT_TRANSLATE_NOOP("MainWindow", "Installing selected firmware updates"),
    # presentation/update_progress_model.py
    QT_TRANSLATE_NOOP("MainWindow", "Updating selected KDE Store add-ons"),
    # presentation/update_progress_model.py
    QT_TRANSLATE_NOOP("MainWindow", "Downloading {package}"),
    # presentation/update_progress_model.py
    QT_TRANSLATE_NOOP("MainWindow", "{action} {package} — {current} of {total}"),
    # services/optional_sources.py
    QT_TRANSLATE_NOOP("OptionalSourcesService", "Installed, ready to check device firmware"),
    # services/optional_sources.py, services/optional_sources.py, services/optional_sources.py
    QT_TRANSLATE_NOOP("OptionalSourcesService", "Missing"),
    # services/optional_sources.py
    QT_TRANSLATE_NOOP(
        "OptionalSourcesService", "Missing; install an AUR helper manually, then reopen this page"
    ),
    # services/optional_sources.py
    QT_TRANSLATE_NOOP("OptionalSourcesService", "AUR preference persistence is unavailable."),
    # services/optional_sources.py
    QT_TRANSLATE_NOOP(
        "OptionalSourcesService", "Installed, no compatible firmware devices detected"
    ),
    # services/optional_sources.py
    QT_TRANSLATE_NOOP("OptionalSourcesService", "Installed, device support unavailable"),
    # services/optional_sources.py, services/optional_sources.py
    QT_TRANSLATE_NOOP("OptionalSourcesService", "Installed"),
    # services/optional_sources.py
    QT_TRANSLATE_NOOP("OptionalSourcesService", "Installed but inactive"),
    # services/optional_sources.py
    QT_TRANSLATE_NOOP("OptionalSourcesService", "Enabled ({helpers})"),
    # services/optional_sources.py
    QT_TRANSLATE_NOOP("OptionalSourcesService", "Installed, disabled in ArchUpdater ({helpers})"),
    # services/plasma_widget_archive.py, services/plasma_widget_archive.py, services/plasma_widget_archive.py, services/plasma_widget_archive.py, services/plasma_widget_archive.py, services/plasma_widget_archive.py, services/plasma_widget_archive.py, services/plasma_widget_archive.py, services/plasma_widget_archive.py, services/plasma_widget_archive.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService",
        "The downloaded KDE Store add-on package is incomplete or incompatible.",
    ),
    # services/plasma_widget_archive.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService",
        "The downloaded KDE Store add-on archive could not be extracted.",
    ),
    # services/plasma_widget_archive.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService",
        "The downloaded KDE Store add-on archive does not contain metadata.json.",
    ),
    # services/plasma_widget_archive.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService",
        "The downloaded KDE Store add-on metadata does not match the installed add-on.",
    ),
    # services/plasma_widget_archive.py, services/plasma_widget_archive.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService", "The downloaded KDE Store add-on metadata is invalid."
    ),
    # services/plasma_widget_archive.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService",
        "The downloaded KDE Store add-on type does not match the installed add-on.",
    ),
    # services/plasma_widget_archive.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService",
        "The downloaded KDE Store add-on version does not match the advertised update.",
    ),
    # services/plasma_widget_archive.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService", "Failed to read KDE Store add-on metadata from {path}."
    ),
    # services/plasma_widgets.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService",
        "Some KDE Store add-ons may require restarting plasmashell after updating.",
    ),
    # services/plasma_widgets.py
    QT_TRANSLATE_NOOP("PlasmaWidgetsUpdateService", "KDE Store"),
    # services/plasma_widgets.py, services/plasma_widgets_update.py, services/plasma_widgets_update.py, services/plasma_widgets_update.py, services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService", "KDE Store is temporarily unavailable. Try again later."
    ),
    # services/plasma_widgets.py, services/plasma_widgets_update.py, services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService",
        "KDE Store is temporarily limiting requests. Try again in a few minutes.",
    ),
    # services/plasma_widgets_store.py, services/plasma_widgets_store.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsStoreClient",
        "This widget publishes multiple package files, and ArchUpdater could not choose one safely.",
    ),
    # services/plasma_widgets_store.py, services/plasma_widgets_store.py, services/plasma_widgets_store.py, services/plasma_widgets_store.py, services/plasma_widgets_store.py, services/plasma_widgets_store.py, services/plasma_widgets_store.py, services/plasma_widgets_store.py, services/plasma_widgets_store.py, services/plasma_widgets_store.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsStoreClient", "KDE Store is temporarily unavailable. Try again later."
    ),
    # services/plasma_widgets_store.py, services/plasma_widgets_store.py, services/plasma_widgets_store.py, services/plasma_widgets_store.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsStoreClient",
        "The downloaded KDE Store add-on package is incomplete or incompatible.",
    ),
    # services/plasma_widgets_store.py, services/plasma_widgets_store.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsStoreClient",
        "KDE Store is temporarily limiting requests. Try again in a few minutes.",
    ),
    # services/plasma_widgets_store.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsStoreClient",
        "The KDE Store download version does not match the advertised update.",
    ),
    # services/plasma_widgets_update.py, services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP("PlasmaWidgetsUpdateService", "KDE Store add-on update failed."),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService",
        "KDE Store add-on updates completed successfully. Some add-ons may require restarting plasmashell.",
    ),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP("PlasmaWidgetsUpdateService", "Archive extracted successfully."),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP("PlasmaWidgetsUpdateService", "Fetching KDE Store metadata for {name}..."),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP("PlasmaWidgetsUpdateService", "KDE Store type: {kind}."),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP("PlasmaWidgetsUpdateService", "Selected download: {file}."),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP("PlasmaWidgetsUpdateService", "Downloading {name} {version}..."),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP("PlasmaWidgetsUpdateService", "Installing from extracted package: {path}"),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService", "Updated {updated} KDE Store add-ons. Failed: {failed}."
    ),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP("PlasmaWidgetsUpdateService", "kpackagetool6 exited with code {code}."),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP(
        "PlasmaWidgetsUpdateService", "KDE Store add-on update failed for {name}: {error}"
    ),
    # services/plasma_widgets_update.py
    QT_TRANSLATE_NOOP("PlasmaWidgetsUpdateService", "Details: {details}"),
    # services/preflight.py
    QT_TRANSLATE_NOOP("UpdatePreflightService", "Command not found: {command}"),
)
