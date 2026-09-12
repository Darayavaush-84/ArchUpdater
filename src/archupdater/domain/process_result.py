from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandProcessResult:
    success: bool
    return_code: int
    output: str
