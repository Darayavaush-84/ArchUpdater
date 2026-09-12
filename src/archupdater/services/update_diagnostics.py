from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class UpdateFailureKind(str, Enum):
    GENERIC = "generic"
    PACMAN_DATABASE_INVALID = "pacman_database_invalid"


@dataclass(frozen=True, slots=True)
class UpdateFailureDiagnostic:
    kind: UpdateFailureKind
    summary: str
    return_code: int
    details: list[str] = field(default_factory=list)

    @property
    def signal_number(self) -> int | None:
        return abs(self.return_code) if self.return_code < 0 else None

    def render(self, translate: Callable[[str], str]) -> str:
        if self.signal_number is not None:
            message = translate("{message} (signal {signal})").format(
                message=translate(self.summary),
                signal=self.signal_number,
            )
        else:
            message = translate("{message} (exit code {code})").format(
                message=translate(self.summary),
                code=self.return_code,
            )
        if self.details:
            message = f"{message}\n" + "\n".join(self.details)
        return message


def command_failure_diagnostic(
    *,
    failure_message: str,
    return_code: int,
    output: str,
) -> UpdateFailureDiagnostic:
    diagnostic = output.strip()
    if looks_like_pacman_database_error(diagnostic.lower()):
        return UpdateFailureDiagnostic(
            kind=UpdateFailureKind.PACMAN_DATABASE_INVALID,
            summary="Pacman package databases are not valid. Refresh package databases, then try again.",
            return_code=return_code,
            details=important_system_failure_lines(diagnostic),
        )
    return UpdateFailureDiagnostic(
        kind=UpdateFailureKind.GENERIC,
        summary=failure_message,
        return_code=return_code,
        details=important_system_failure_lines(diagnostic),
    )


def looks_like_pacman_database_error(lowered_output: str) -> bool:
    return (
        "invalid or corrupted database" in lowered_output
        or "database" in lowered_output and "not valid" in lowered_output
        or "signature from" in lowered_output
    )


def important_system_failure_lines(output: str) -> list[str]:
    if not output:
        return []
    markers = (
        "error:",
        "warning:",
        "package architecture is not valid",
        "invalid or corrupted database",
        "database",
        "signature from",
        "unable to lock database",
        "could not lock database",
        "returning error",
    )
    lines: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not line or not any(marker in lowered for marker in markers):
            continue
        if line not in lines:
            lines.append(line)
        if len(lines) >= 8:
            break
    return lines
