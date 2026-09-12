from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.application.update_session.protocol import (
    BatchEventType,
    BatchOutcome,
    MAX_UPDATE_PLAN_BYTES,
    deserialize_update_plan_json,
)
from archupdater.batch.events import EventWriter
from archupdater.batch.runner import BatchRunner
from archupdater.batch.translations import TRANSLATION_MARKERS
from archupdater.domain.update_plan import UpdatePlan
from archupdater.i18n.manager import TranslationManager
from archupdater.infrastructure.settings import SettingsService
from archupdater.process_lifecycle import set_parent_death_signal


_TRANSLATION_MARKERS = TRANSLATION_MARKERS


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="archupdater.batch_update_runner")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--events", required=True)
    return parser.parse_args(argv)


def _load_plan(path: Path) -> UpdatePlan:
    with path.open("rb") as handle:
        raw_bytes = handle.read(MAX_UPDATE_PLAN_BYTES + 1)
    if len(raw_bytes) > MAX_UPDATE_PLAN_BYTES:
        raise ValueError("Update plan exceeds the safety limit.")
    return deserialize_update_plan_json(raw_bytes.decode("utf-8", errors="strict"))


def _raise_termination(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    return _run(argv)


def _process_main(argv: list[str] | None = None) -> int:
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    previous_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, _raise_termination)
    signal.signal(signal.SIGINT, _raise_termination)
    try:
        set_parent_death_signal(signal.SIGTERM)
        if os.getppid() == 1:
            return 1
        return _run(argv)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)


def _run(argv: list[str] | None = None) -> int:
    app = QCoreApplication([sys.argv[0]])
    app.setApplicationName("ArchUpdater")
    app.setOrganizationName("ArchUpdater")
    translation_manager = TranslationManager(app)
    translation_manager.install(SettingsService().language_preference())
    parsed = _parse_args(argv or sys.argv[1:])
    events = EventWriter(Path(parsed.events))
    runner: BatchRunner | None = None
    try:
        plan = _load_plan(Path(parsed.plan))
        runner = BatchRunner(plan, events)
        return runner.run()
    except Exception as exc:  # last-resort structured session failure
        message = str(exc).strip() or exc.__class__.__name__
        if runner is not None:
            runner._print_footer(success=False, message=message)
        else:
            print(message, file=sys.stderr, flush=True)
        events.emit(
            BatchEventType.BATCH_COMPLETED.value,
            success=False,
            message=message,
            outcome=BatchOutcome.FAILED.value,
            completed=[],
            incomplete=[],
            failed=[],
            not_executed=[],
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(_process_main())
