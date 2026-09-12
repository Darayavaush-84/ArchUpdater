from __future__ import annotations

from dataclasses import dataclass, field

from archupdater.domain.enums import PreflightSeverity


@dataclass(slots=True)
class PreflightIssue:
    severity: PreflightSeverity
    title: str
    message: str
    details: list[str] = field(default_factory=list)
