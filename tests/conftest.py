from __future__ import annotations

import atexit
import os
import shutil
import tempfile

from PySide6.QtCore import QCoreApplication


_runtime_root = tempfile.mkdtemp(prefix="archupdater-tests-")
_config_home = os.path.join(_runtime_root, "config")
_cache_home = os.path.join(_runtime_root, "cache")

os.makedirs(_config_home, exist_ok=True)
os.makedirs(_cache_home, exist_ok=True)
os.environ.setdefault("XDG_CONFIG_HOME", _config_home)
os.environ.setdefault("XDG_CACHE_HOME", _cache_home)


def _cleanup_runtime_root() -> None:
    shutil.rmtree(_runtime_root, ignore_errors=True)


atexit.register(_cleanup_runtime_root)


def _apply_test_application_metadata() -> None:
    QCoreApplication.setOrganizationName("ArchUpdaterTests")
    QCoreApplication.setApplicationName("ArchUpdaterTests")


def pytest_configure() -> None:
    _apply_test_application_metadata()


def pytest_runtest_setup() -> None:
    _apply_test_application_metadata()
