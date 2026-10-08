# Changelog

## [1.0.5] - 2026-10-08

### Added

- **Last Update**: reopen the latest update result with its completion date, summary and exportable log, even after restarting the application or the computer. Manually reopened results stay open until closed.

### Changed

- Automatically check for updates when opening a new foreground instance. Reopening the window from the system tray does not trigger another scan, and hidden startup at login continues to respect the periodic check settings.
- Remember the **Close automatically if all updates succeed** preference across application and system restarts.

### Fixed

- Keep action buttons fully readable by adapting the main window's minimum width to their labels, including translated text and update counts.
- Report partial update results consistently in the progress window and exported logs, and distinguish cancelled sessions from failures.
- Validate update results before replacing the saved session, preserving the previous result if new data is invalid.
- Restore translated progress summaries and follow-up instructions.

## [1.0.3] - 2026-09-27

### Fixed

- Preserve executable permissions for reviewed AUR build scripts so valid packages build correctly.
- Correctly report AUR updates that make no changes, partially fail, or cannot be verified.
- Remove saved AUR development state when uninstalling with `--purge-user-data`, including custom XDG directories.

## [1.0.2] - 2026-09-18

### Fixed

- Prevent a disconnected update interface from interrupting critical package and firmware operations.
- Report a failure instead of leaving the update window waiting when update events are incomplete or unreadable.
- Correctly report system updates that make no changes and failures that occur after packages have changed.
- Verify installed Flatpak commits before reporting updates as completed.
- Fix confirmation dialogs that could reject an accepted choice, and show the final Pacman transaction when it changes after review.
- Fix start-on-login and system tray behavior, including after an ArchUpdater update.
- Keep the interface responsive while checking firmware support.
- Continue checking other Plasma add-ons when one KDE Store entry fails, and ignore malformed local metadata.
- Keep incomplete update results open and show warnings for failed or incomplete checks.

### Changed

- Automatic checks now resume from the last successful check across restarts and respect the disabled setting.
- Clarify the warning shown before running community-maintained AUR build scripts.

## [1.0.1] - 2026-09-12

### Added

- Manually update ArchUpdater from the green **Update** button: review release notes and choose **Update and Restart**.
- A GitHub release workflow that runs CI and publishes downloadable packages and checksums.

### Fixed

- Untranslated Plasma restart choices and Save/Cancel buttons in Preferences.

### Changed

- Expanded regression tests for release handling, installation and the update dialog.

## [1.0.0]

Initial public stable release, with a unified desktop interface for system packages, optional AUR and Flatpak updates, firmware and Plasma add-ons; Arch News; system tray integration; and five interface languages.

[1.0.5]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.5
[1.0.3]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.3
[1.0.2]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.2
[1.0.1]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.1
[1.0.0]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.0
