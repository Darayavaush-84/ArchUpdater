from __future__ import annotations

from PySide6.QtCore import QT_TRANSLATE_NOOP


TRANSLATION_MARKERS = (
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "ArchUpdater batch started."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Session log: {path}"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "The update batch was interrupted."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Selected updates completed successfully."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Selected updates completed with skipped items."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "No selected updates were installed."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Pacman"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Now running a full system upgrade with pacman."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Packages: {packages}"),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "Detected system updates: {packages}. Pacman will perform a full system upgrade.",
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "System update failed."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "AUR"),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "Now installing the selected AUR updates with {helper}."
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "AUR update failed."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Flatpak"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Now installing the selected Flatpak updates."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "System refs: {refs}"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "User refs: {refs}"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Flatpak update failed."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Flatpak update completed successfully."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Firmware"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Now installing the selected firmware updates."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Devices: {count}"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Firmware update failed."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Firmware device failed: {device}"),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "Updated {updated} firmware device(s). Failed: {failed}."
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Firmware update completed successfully."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "KDE Store Add-ons"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Now installing the selected KDE Store add-on updates."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Add-ons: {addons}"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{command} is not available on this system."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{step} completed successfully."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{step} failed."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "No further update steps will be executed."),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "Authentication was cancelled. The administrator password is required to continue, so the update has been interrupted.",
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "pkexec is required for privileged update steps."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "ArchUpdater privileged helper is not installed."),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "Requesting administrator authorization for privileged update session.",
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Privileged helper action: {action}"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Privileged helper status: {status}"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Failed to start privileged helper: {error}"),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "Authorization failed or no authentication agent was available.",
    ),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "Privileged helper exited unexpectedly with code {code}."
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "ArchUpdater update session"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "The following updates will be installed:"),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "You may be asked to authorize privileged update steps.",
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Success"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Failed"),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "ArchUpdater will refresh package status automatically."
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "No package status refresh is required."),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "Review the update log above before closing this window."
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Update summary"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Completed"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Incomplete"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Not executed"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Next step"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "No further action is required."),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "Skipped AUR updates remain available and can be retried later.",
    ),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "Review the live activity log, then run the remaining updates again.",
    ),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "Review the live activity log, then try the update again."
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Command: {command}"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Continuing with system package updates."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Continuing with AUR package updates."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Continuing with Flatpak updates."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Continuing with firmware updates."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Continuing with KDE Store add-on updates."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Continuing with the next update step."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "1 package"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{count} packages"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Flatpak (system)"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "1 update"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{count} updates"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Flatpak (user)"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "1 device"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{count} devices"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "1 add-on"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{count} add-ons"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{visible} (+{remaining} more)"),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "Selected updates completed with incomplete or failed steps."
    ),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "No selected updates were installed because the selected steps failed."
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "AUR update completed successfully."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "unknown error"),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "The available transaction changed after the original review. Review the new versions before continuing.",
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "makepkg is not available."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "AUR updates were skipped after PKGBUILD review."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "AUR update completed with skipped packages."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Review AUR PKGBUILD"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "AUR preparation failed for {package}: {error}"),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "Selected Flatpak updates were installed, but Flatpak reported a follow-up error.",
    ),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "Could not safely refresh the pacman transaction preview."
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "No reviewed system updates remain available."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "The changed system transaction was not approved."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Could not prepare the Flatpak transaction."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Flatpak returned an invalid transaction preview."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Flatpak cleanup failed."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "System Update Changed"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Could not build and install the reviewed AUR package."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Skipped AUR updates: {packages}."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{scope} refs: {refs}"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Could not verify the Flatpak transaction."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Flatpak returned an invalid verification result."),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "All selected Flatpak refs were deployed, but Flatpak reported a follow-up error.",
    ),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "Flatpak finished without installing all selected updates."
    ),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "The AUR update plan has no expected version for {package}."
    ),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "The AUR helper did not report the installed development version."
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Flatpak Update Changed"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "The changed Flatpak transaction was not approved."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "PKGBUILD review was cancelled."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Skipped {package}: PKGBUILD review was cancelled."),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "Missing build dependencies for {package}: {dependencies}. Install them explicitly before retrying.",
    ),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "The AUR helper reported an invalid development version."
    ),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "Could not record AUR development state for {package}: {error}"
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Privileged helper output exceeded the safety limit."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Could not initialize the privileged update session."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Invalid Pacman question."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "The privileged helper returned an invalid result."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "The update step was interrupted before it completed."),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner", "Further command output was suppressed after the safety limit."
    ),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "Update command timed out."),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{message} (signal {signal})"),
    QT_TRANSLATE_NOOP("BatchUpdateRunner", "{message} (exit code {code})"),
    QT_TRANSLATE_NOOP(
        "BatchUpdateRunner",
        "Pacman package databases are not valid. Refresh package databases, then try again.",
    ),
)
