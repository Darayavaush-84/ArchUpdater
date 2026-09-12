# Architecture

ArchUpdater is organized around explicit dependency boundaries. New code should fit one
of these roles before introducing a new module.

## Layers

- `archupdater.domain`: pure data structures, enums, and small domain helpers. It must not
  import Qt, subprocess, services, infrastructure, presentation, or helper code.
- `archupdater.application`: use cases and orchestration. It may depend on domain objects
  and service-facing protocols, but not on Qt, presentation, infrastructure, or helper code.
- `archupdater.services`: concrete backend integrations such as pacman, Flatpak, fwupd,
  KDE Store, process runners, and parser logic. Services may depend on domain objects but
  not on application, infrastructure, presentation, or helper code.
- `archupdater.infrastructure`: persistence and desktop adapters such as `QSettings`,
  autostart, and cache storage. Infrastructure must stay independent from application and
  presentation workflows.
- `archupdater.presentation`: Qt UI, view models, dialogs, presenters, and window
  coordination. Presentation talks to the application facade and infrastructure adapters,
  but must not import backend services directly.
- `archupdater.batch`: command-line update-session bootstrap and orchestration. This is an
  entrypoint layer, so it wires application use cases, services, process execution, events,
  and auth policy for the external batch updater.
- `archupdater.helper`: privileged helper process and helper actions. It communicates through
  application-level helper protocol objects and must not import presentation code.
- `archupdater.container`: composition root for the desktop app. It is allowed to instantiate
  concrete services and adapters because it connects the layers.

## Dependency Direction

The stable direction is:

`presentation -> application -> domain`

`services -> domain`

`infrastructure -> domain`

Entrypoints (`app.py`, `batch_update_runner.py`, `batch`, and `container`) are the places
where concrete objects are assembled.

## Guardrails

The architecture boundary tests in `tests/test_architecture_boundaries.py` enforce the most
important rules:

- domain stays pure;
- presentation does not import services or helper code;
- services do not import application, infrastructure, presentation, or helper code;
- application does not import infrastructure, presentation, helper, Qt, or concrete
  process/filesystem adapters such as `subprocess`, `shutil`, and `os`;
- infrastructure does not import application, presentation, or helper code;
- services do not own Qt process/object adapters.

When adding a feature, prefer extending these tests if a new boundary becomes important.

## Component Ownership

`services/aur.py` coordinates update discovery and keeps the application's existing
`AurUpdateService` API. Its collaborators have separate lifetimes and responsibilities:

- `aur_metadata.py` and `aur_sources.py` parse metadata and source descriptions without I/O.
- `AurRpcClient` owns bounded HTTP requests; tests can inject its opener.
- `AurVcsTracker` resolves remote commits and filters already installed revisions;
  `AurVcsStateStore` persists installation receipts with atomic replacement.
- `AurReviewManager` owns temporary checkouts from preparation through discard, including
  manifest validation and dependency checks. It shares the service's RPC and VCS collaborators.

`helper/actions/privileged_updates.py` preserves the public entry points through explicit
re-exports. Backend actions live in `system_updates.py`, `flatpak_updates.py`,
`firmware_updates.py`, and `aur_updates.py`. AUR review validation, workspace ownership,
and artifact verification are separate modules. `update_commands.py` owns shared command
execution and shutdown inhibition. The build still runs as the unprivileged build user;
artifact validation and installation remain in the privileged process.

`CheckScheduleController` owns the startup network subscription and check timers. The main
window supplies callbacks for starting checks and showing status; `BackgroundBehaviorController`
still applies user preferences and calculates the next scheduled check. Closing the window
for real stops timers and disconnects the network subscription; hiding to the tray retains them.

`presentation/theme.py` assembles the stylesheet from `presentation/styles/`. `palette.py`
derives colors once, and the section builders retain the original cascade order. Keep this
order when editing overlapping selectors. Splitting the stylesheet does not change its output.

## Test Collaborators

Reusable collaborators live in `tests/support/`: `FakeCommandRunner` consumes explicit
responses and rejects unexpected commands, `FakePreflightEnvironment` supplies command
availability and disk capacity without probing the host, and the network fakes supply Qt
signals and responses without network access. Prefer these injected collaborators to
patching global process, filesystem, or network functions in service tests.

Filesystem behavior itself is tested in temporary directories. The fixtures in
`tests/support/aur.py` deliberately use real local Git repositories to verify review integrity
and checkout cleanup; these integration tests require Git and never clone from the Internet.
The real `vercmp` test requires Arch's executable. Both kinds declare their prerequisites and
skip when absent; CI's Arch job supplies them. Tests for privileged actions substitute process
execution and do not perform real package updates.

## Translation Maintenance

Run `scripts/build_translations.sh` after source-message changes, complete the five TS
catalogs in `i18n/ts`, then run the script again to compile the QM resources. Validate with
`ARCHUPDATER_TRANSLATION_STRICT=1 scripts/check_translations.sh`; CI uses this strict mode
so missing, obsolete, or unfinished messages fail validation.

Qt contexts must match at extraction and runtime. Dialog helpers use an explicit
`QCoreApplication.translate` context instead of calling `tr` on a variable whose class
lupdate cannot infer. The composition root injects translations into preflight and update
checking services, keeping Qt out of the application layer.

Strings translated through callbacks are registered with `QT_TRANSLATE_NOOP` in
`batch/translations.py` and `i18n/markers.py`. Keep those markers aligned with their call
sites. `test_translation_catalogs.py` checks callback coverage, Python/Qt placeholders,
compiled catalog contents, and translated GUI/service behavior in all four target languages.

## Development Gates

Before considering an architectural change complete, run:

```bash
ruff check src tests scripts
env QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
```

For dead-code checks, use:

```bash
python -m vulture src tests --min-confidence 80
```
