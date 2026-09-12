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

## Development Gates

Before considering an architectural change complete, run:

```bash
ruff check src tests
env QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
```

For dead-code checks, use:

```bash
python -m vulture src tests --min-confidence 80
```
