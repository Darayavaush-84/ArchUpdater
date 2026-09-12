from __future__ import annotations


class UpdateError(RuntimeError):
    pass


class UpdateCancelled(UpdateError):
    pass


class AuthenticationCancelled(UpdateCancelled):
    pass


class BackendError(UpdateError):
    pass


class BackendUnavailableError(BackendError):
    pass
