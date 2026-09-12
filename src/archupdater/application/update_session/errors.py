from __future__ import annotations

from archupdater.domain.errors import AuthenticationCancelled, UpdateCancelled


class BatchCancelled(UpdateCancelled):
    def __init__(self, message: str = "", *, changed: bool = False) -> None:
        super().__init__(message)
        self.changed = changed


class BatchAuthenticationCancelled(AuthenticationCancelled):
    pass
