from __future__ import annotations

import json
import platform
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from archupdater import __version__
from archupdater.domain.progress import UpdateProgressSnapshot


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
DECORATIVE_SEPARATOR_RE = re.compile(r"^-{12,}$")


@dataclass(frozen=True, slots=True)
class RuntimeExportInfo:
    python_version: str
    qt_version: str
    platform_name: str

    @classmethod
    def current(cls, *, qt_version: str) -> RuntimeExportInfo:
        return cls(
            python_version=platform.python_version(),
            qt_version=qt_version,
            platform_name=platform.platform(),
        )


def clean_console_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    previous_blank = False
    for raw_line in lines:
        line = ANSI_ESCAPE_RE.sub("", raw_line).strip()
        if DECORATIVE_SEPARATOR_RE.fullmatch(line):
            if cleaned and not previous_blank:
                cleaned.append("")
                previous_blank = True
            continue
        if line == "ArchUpdater update session":
            continue
        if not line:
            if cleaned and not previous_blank:
                cleaned.append("")
                previous_blank = True
            continue
        cleaned.append(line)
        previous_blank = False
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return cleaned


def write_update_log_export(
    *,
    folder: Path,
    snapshot: UpdateProgressSnapshot,
    runtime: RuntimeExportInfo,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    archive_path = folder / f"archupdater-update-logs-{timestamp}.zip"

    created = False
    try:
        destination = archive_path.open("xb")
        created = True
        with destination, zipfile.ZipFile(
            destination, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(export_manifest(snapshot, runtime=runtime), indent=2, ensure_ascii=False),
            )
            archive.writestr("update-session.log", export_log_text(snapshot))
    except Exception:
        if created:
            archive_path.unlink(missing_ok=True)
        raise
    return archive_path


def export_manifest(
    snapshot: UpdateProgressSnapshot,
    *,
    runtime: RuntimeExportInfo,
) -> dict[str, object]:
    return {
        "application": "ArchUpdater",
        "archupdater_version": __version__,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python_version": runtime.python_version,
        "qt_version": runtime.qt_version,
        "platform": runtime.platform_name,
        "session": {
            "title": snapshot.title,
            "subtitle": snapshot.subtitle,
            "percent": snapshot.percent,
            "success": snapshot.success,
            "final_state": snapshot.final_state,
            "current_phase": (
                snapshot.current_phase.value if snapshot.current_phase is not None else None
            ),
            "notice_title": snapshot.notice_title,
            "notice_text": snapshot.notice_text,
        },
        "summary": {
            "title": snapshot.summary_title,
            "completed": snapshot.summary_completed,
            "incomplete": snapshot.summary_incomplete,
            "failed": snapshot.summary_failed,
            "not_executed": snapshot.summary_not_executed,
            "next_step": snapshot.summary_next_step,
        },
        "steps": [
            {
                "phase": step.phase.value,
                "label": step.label,
                "state": step.state.value,
                "log_line_count": len(step.log_lines),
            }
            for step in snapshot.steps
        ],
    }


def export_log_text(snapshot: UpdateProgressSnapshot) -> str:
    cleaned_console = "\n".join(clean_console_lines(snapshot.console_lines)).strip()
    return "\n".join(
        (
            export_summary_text(snapshot).rstrip(),
            "",
            "Update log",
            "----------",
            cleaned_console or "No update log was captured.",
            "",
        )
    )


def export_summary_text(snapshot: UpdateProgressSnapshot) -> str:
    lines = [
        "ArchUpdater Update Log Export",
        f"ArchUpdater version: {__version__}",
        f"Exported at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        f"Title: {snapshot.title}",
        f"Subtitle: {snapshot.subtitle}",
        f"Result: {'success' if snapshot.success else 'failed'}",
        "",
        "Summary",
    ]
    if snapshot.summary_completed:
        lines.append(f"Completed: {', '.join(snapshot.summary_completed)}")
    if snapshot.summary_incomplete:
        lines.append(f"Incomplete: {', '.join(snapshot.summary_incomplete)}")
    if snapshot.summary_failed:
        lines.append(f"Failed: {', '.join(snapshot.summary_failed)}")
    if snapshot.summary_not_executed:
        lines.append(f"Not executed: {', '.join(snapshot.summary_not_executed)}")
    if snapshot.summary_next_step:
        lines.append(f"Next step: {snapshot.summary_next_step}")

    lines.extend(["", "Steps"])
    for index, step in enumerate(snapshot.steps, start=1):
        lines.append(f"{index}. {step.label} [{step.phase.value}] - {step.state.value}")
    return "\n".join(lines) + "\n"
