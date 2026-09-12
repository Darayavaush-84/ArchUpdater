"""Local Git integration fixtures: real repositories, no AUR network calls."""

from __future__ import annotations

import subprocess
from pathlib import Path

from archupdater.services.aur_review import AurReviewManager
from archupdater.services.aur_rpc import AurRpcClient
from archupdater.services.aur_vcs import AurVcsTracker
from archupdater.services.aur_vcs_state import AurVcsStateStore
from archupdater.services.command_runner import CommandRunner


def create_git_checkout(path: Path, files: dict[str, str | bytes]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode() if isinstance(content, str) else content)
    git = ["git", "-C", str(path), "-c", "core.hooksPath=/dev/null"]
    for arguments in (
        ["init", "-q"],
        ["add", "--all"],
        [
            "-c",
            "user.name=ArchUpdater Tests",
            "-c",
            "user.email=tests@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture",
        ],
    ):
        subprocess.run([*git, *arguments], check=True, capture_output=True)


class LocalGitAurReviewManager(AurReviewManager):
    def __init__(self, files: dict[str, str | bytes]) -> None:
        runner = CommandRunner()
        super().__init__(runner, AurRpcClient(), AurVcsTracker(runner, AurVcsStateStore()))
        self.files = files
        self.fetched: list[str] = []
        self.checkout_path: Path | None = None

    def _clone_checkout(self, package_base: str, checkout_path: Path) -> None:
        self.fetched.append(package_base)
        self.checkout_path = checkout_path
        create_git_checkout(checkout_path, self.files)
