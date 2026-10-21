# Changelog

## [1.1.1] - 2026-10-21

**Fixed**
- Update checks no longer stall for minutes when the firmware metadata server (LVFS) does not respond: metadata is downloaded at most once a day, and a stuck download is abandoned after 60 seconds instead of 180.

## [1.1.0] - 2026-10-20

**Added**
- **Pacman download timeouts**: if they are disabled, ArchUpdater offers once per session to enable them, so an unresponsive mirror cannot stall the update check. With administrator authentication it comments out `DisableDownloadTimeout` in `/etc/pacman.conf`, only if the effective configuration (including included files) confirms the change.

**Security**
- AUR packages are built in an isolated temporary system account, not as your user: other programs you run cannot alter the reviewed files or replace the package before installation, and builds cannot access your home directory.
- Development (`-git`) packages: the approved Git commit is verified after download and before any upstream code runs, and exactly that commit is built.
- The update authentication prompt now states that it installs system packages, reviewed AUR packages, system Flatpaks and firmware.
- The single-instance socket lives in your private runtime directory, so other local users cannot block ArchUpdater from starting.

**Changed**
- AUR builds use the system `makepkg.conf`; from yours only `MAKEFLAGS` (`-j`, `-l`) and `PACKAGER` apply. Build caches such as ccache and files in your home are not available.
- AUR updates require systemd (`systemd-run`).
- Self-updates keep only the current and previous release.

**Fixed**
- Periodic checks run on time after resuming from suspend.
- Reviewed AUR build files up to the documented size limit are accepted; oversized requests are reported clearly.
- Uninstalling also removes leftover AUR build state.

## [1.0.5] - 2026-10-08

**Added**
- **Last Update**: reopen the latest update result (completion date, summary, exportable log), even after a restart. Manually reopened results stay open until closed.

**Changed**
- A new foreground instance checks for updates automatically; reopening from the tray does not, and hidden startup at login follows the periodic check settings.
- **Close automatically if all updates succeed** is remembered across restarts.

**Fixed**
- Action buttons stay readable: the window's minimum width adapts to translated labels and update counts.
- Partial results are reported consistently in the progress window and exported logs; cancelled sessions are no longer shown as failures.
- Update results are validated before replacing the saved session; invalid data keeps the previous result.
- Translated progress summaries and follow-up instructions are restored.

## [1.0.3] - 2026-09-27

**Fixed**
- Reviewed AUR build scripts keep their executable permissions, so valid packages build correctly.
- AUR updates that make no changes, partially fail or cannot be verified are reported correctly.
- `--purge-user-data` also removes saved AUR development state, including custom XDG directories.

## [1.0.2] - 2026-09-18

**Fixed**
- A disconnected update interface can no longer interrupt critical package and firmware operations.
- Incomplete or unreadable update events report a failure instead of leaving the window waiting.
- System updates that make no changes, and failures after packages have changed, are reported correctly.
- Installed Flatpak commits are verified before updates are reported as completed.
- Confirmation dialogs no longer reject accepted choices; the final Pacman transaction is shown when it changes after review.
- Start on login and the system tray work correctly, including after an ArchUpdater update.
- The interface stays responsive while checking firmware support.
- One failing KDE Store entry no longer stops other Plasma add-on checks; malformed local metadata is ignored.
- Incomplete update results stay open, with warnings for failed or incomplete checks.

**Changed**
- Automatic checks resume from the last successful check across restarts and respect the disabled setting.
- Clearer warning before running community-maintained AUR build scripts.

## [1.0.1] - 2026-09-12

**Added**
- Update ArchUpdater from the green **Update** button: review the release notes and choose **Update and Restart**.
- A GitHub release workflow that runs CI and publishes packages and checksums.

**Fixed**
- Untranslated Plasma restart choices and Save/Cancel buttons in Preferences.

**Changed**
- More regression tests for release handling, installation and the update dialog.

## [1.0.0]

Initial public stable release: one desktop interface for system packages, optional AUR and Flatpak updates, firmware and Plasma add-ons, with Arch News, system tray integration and five interface languages.

[1.1.1]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.1.1
[1.1.0]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.1.0
[1.0.5]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.5
[1.0.3]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.3
[1.0.2]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.2
[1.0.1]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.1
[1.0.0]: https://github.com/Darayavaush-84/ArchUpdater/releases/tag/v1.0.0
