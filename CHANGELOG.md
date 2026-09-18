# Changelog

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

[1.0.2]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.2
[1.0.1]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.1
[1.0.0]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.0
