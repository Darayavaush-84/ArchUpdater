"""Narrow Polkit entry point for installing attested ArchUpdater wheels offline."""

from __future__ import annotations

import argparse
import email
import fcntl
import importlib.metadata
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import venv
import zipfile

from packaging.version import Version

from archupdater.domain.self_update import MAX_BUNDLE_BYTES, MAX_WHEEL_BYTES, release_version
from archupdater.services.self_update import verify_artifact


def private_copy(source: Path, destination: Path, *, uid: int, limit: int) -> None:
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as input_file:
        info = os.fstat(input_file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or not 0 < info.st_size <= limit:
            raise ValueError("Invalid update input file.")
        with destination.open("xb") as output:
            os.chmod(destination, 0o600)
            total = 0
            while chunk := input_file.read(64 * 1024):
                total += len(chunk)
                if total > limit:
                    raise ValueError("Update input exceeds the size limit.")
                output.write(chunk)


def wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_files = [
            item for item in archive.infolist() if item.filename.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1 or metadata_files[0].file_size > 128 * 1024:
            raise ValueError("Invalid update wheel metadata.")
        metadata = email.message_from_bytes(archive.read(metadata_files[0]))
        if metadata.get("Name") != "archupdater":
            raise ValueError("The update wheel is not ArchUpdater.")
        return release_version(metadata.get("Version", ""))


def site_packages(release: Path) -> Path:
    return (
        release
        / "venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )


def installed_version(release: Path) -> str:
    for distribution in importlib.metadata.distributions(path=[str(site_packages(release))]):
        if distribution.metadata["Name"] == "archupdater":
            return release_version(distribution.version)
    raise ValueError("The managed installation has no version metadata.")


class ManagedInstall:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.releases = root / "releases"

    def validate(self) -> None:
        if self.root.name != "archupdater" or not self.root.is_absolute():
            raise ValueError("Not a managed ArchUpdater installation.")
        for path in (self.root, self.releases, self.link_target("current"), *self.root.parents):
            info = path.lstat()
            if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError("The managed installation is not protected.")
        self.link_target("current")

    def link_target(self, name: str) -> Path:
        link = self.root / name
        if not link.is_symlink():
            raise ValueError("Missing managed release link.")
        target = link.resolve(strict=True)
        if target.parent != self.releases or not target.is_dir():
            raise ValueError("Release link is outside the managed installation.")
        return target

    def switch(self, name: str, target: Path) -> None:
        if target.parent != self.releases:
            raise ValueError("Invalid release destination.")
        temporary = self.root / f".{name}-{os.getpid()}"
        try:
            temporary.symlink_to(f"releases/{target.name}")
            os.replace(temporary, self.root / name)
        finally:
            temporary.unlink(missing_ok=True)

    def rollback(self) -> None:
        previous = self.link_target("previous")
        self.smoke_test(previous, installed_version(previous))
        self.switch("current", previous)

    def install(self, wheel: Path, bundle: Path, version: str, *, uid: int) -> None:
        version = release_version(version)
        current = self.link_target("current")
        if Version(version) <= Version(installed_version(current)):
            raise ValueError("The update must be newer than the installed release.")
        with tempfile.TemporaryDirectory(prefix=".verified-", dir=self.root) as temporary:
            verified = Path(temporary)
            sealed_wheel = verified / f"archupdater-{version}-py3-none-any.whl"
            sealed_bundle = verified / "attestation.json"
            private_copy(wheel, sealed_wheel, uid=uid, limit=MAX_WHEEL_BYTES)
            private_copy(bundle, sealed_bundle, uid=uid, limit=MAX_BUNDLE_BYTES)
            # Verification uses the private copies; caller-owned files are never installed.
            verify_artifact(sealed_wheel, sealed_bundle, version, home=verified)
            if wheel_version(sealed_wheel) != version:
                raise ValueError("The signed wheel version does not match the approved version.")
            stage = Path(tempfile.mkdtemp(prefix=f"{version}-", dir=self.releases))
            committed = False
            try:
                venv.EnvBuilder(with_pip=True, system_site_packages=True).create(stage / "venv")
                destination = site_packages(stage)
                for path in site_packages(current).iterdir():
                    if (
                        path.name == "archupdater"
                        or path.name.startswith(("archupdater-", "pip-"))
                        or path.name == "pip"
                    ):
                        continue
                    target = destination / path.name
                    if target.exists() or target.is_symlink():
                        continue
                    if path.is_dir() and not path.is_symlink():
                        shutil.copytree(path, target, symlinks=True)
                    else:
                        shutil.copy2(path, target, follow_symlinks=False)
                self.run(
                    [
                        str(stage / "venv/bin/python"),
                        "-I",
                        "-m",
                        "pip",
                        "--isolated",
                        "install",
                        "--no-index",
                        "--no-deps",
                        "--only-binary=:all:",
                        str(sealed_wheel),
                    ]
                )
                self.smoke_test(stage, version)
                # New release must be readable by the normal desktop user.
                stage.chmod(0o755)
                for base, directories, files in os.walk(stage):
                    for name in directories + files:
                        path = Path(base) / name
                        if not path.is_symlink():
                            path.chmod(
                                (path.stat().st_mode & 0o755) | (0o755 if path.is_dir() else 0o644)
                            )
                self.switch("previous", current)
                self.switch("current", stage)
                committed = True
            finally:
                if not committed:
                    shutil.rmtree(stage)

    def run(self, command: list[str]) -> None:
        result = subprocess.run(
            command,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": "/root",
                "LANG": "C.UTF-8",
                "QT_QPA_PLATFORM": "offscreen",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=300,
            check=False,
        )
        if result.returncode:
            raise ValueError(
                "The new release could not be prepared. Check its dependencies and try install.sh if needed.\n"
                + (result.stdout or "")[-8192:]
            )

    def smoke_test(self, release: Path, version: str) -> None:
        self.run(
            [
                str(release / "venv/bin/python"),
                "-I",
                "-c",
                """
import importlib.metadata as metadata
import archupdater
from packaging.requirements import Requirement
from PySide6.QtWidgets import QApplication
from archupdater.presentation.main_window import MainWindow
from archupdater.helper import self_update
import sys
assert archupdater.__version__ == sys.argv[1]
for raw in metadata.requires("archupdater") or []:
    dependency = Requirement(raw)
    if dependency.marker is None or dependency.marker.evaluate({"extra": ""}):
        assert dependency.specifier.contains(metadata.version(dependency.name)), raw
app = QApplication([])
""",
                version,
            ]
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archupdater-auth", required=True, choices=["self-update"])
    operations = parser.add_mutually_exclusive_group(required=True)
    operations.add_argument("--install", nargs=3, metavar=("VERSION", "WHEEL", "BUNDLE"))
    operations.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ValueError("Administrator authorization is required.")
        prefix = Path(sys.prefix).resolve()
        if prefix.name != "venv" or prefix.parent.parent.name != "releases":
            raise ValueError("Self-update is available only for managed installations.")
        installation = ManagedInstall(prefix.parent.parent.parent)
        installation.validate()
        if Path("/var/lib/pacman/db.lck").exists():
            raise ValueError("A system package transaction is running.")
        with (installation.root / ".self-update.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.rollback:
                installation.rollback()
            else:
                version, wheel, bundle = args.install
                installation.install(
                    Path(wheel), Path(bundle), version, uid=int(os.environ.get("PKEXEC_UID", "0"))
                )
        print("OK", flush=True)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
