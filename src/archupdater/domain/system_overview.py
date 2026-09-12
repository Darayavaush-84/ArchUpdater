from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SystemOverviewSnapshot:
    kernel: str
    last_update_at: datetime | None
    mirror: str
    repository: str
