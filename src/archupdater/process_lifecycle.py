from __future__ import annotations

import ctypes
import os
import signal


PR_SET_PDEATHSIG = 1


def set_parent_death_signal(signum: int = signal.SIGTERM) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signum, 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def arm_parent_death_signal(signum: int = signal.SIGTERM) -> None:
    set_parent_death_signal(signum)
    if os.getppid() == 1:
        os._exit(127)
