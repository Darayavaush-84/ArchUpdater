from __future__ import annotations

import os
import pwd
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.domain.aur import (
    AurPkgbuildReview,
)
from archupdater.helper.actions import validation

MAX_AUR_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024


COPY_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class AurBuildUser:
    name: str
    uid: int
    gid: int
    home: Path


def _seal_aur_build_checkout(
    review: AurPkgbuildReview,
    *,
    build_root: Path,
) -> Path:
    checkout_path = build_root / f"{review.package_name}-{review.digest[:16]}"
    checkout_path.mkdir(mode=0o700)
    directories: set[Path] = {checkout_path}
    for reviewed_file in review.files:
        destination = checkout_path.joinpath(*Path(reviewed_file.path).parts)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        current = destination.parent
        while current != checkout_path.parent:
            directories.add(current)
            if current == checkout_path:
                break
            current = current.parent
        with destination.open("xb") as handle:
            handle.write(reviewed_file.content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        destination.chmod(0o444)
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        directory.chmod(0o555)
    return checkout_path


def _create_user_aur_build_checkout(
    sealed_checkout: Path,
    review: AurPkgbuildReview,
    *,
    build_root: Path,
    build_user: AurBuildUser,
) -> Path:
    checkout_path = build_root / "checkout"
    checkout_path.mkdir(mode=0o700)
    os.chown(checkout_path, build_user.uid, build_user.gid)
    directories: set[Path] = {checkout_path}
    for reviewed_file in review.files:
        relative_path = Path(reviewed_file.path)
        source = sealed_checkout.joinpath(*relative_path.parts)
        destination = checkout_path.joinpath(*relative_path.parts)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        current = destination.parent
        while current != checkout_path.parent:
            directories.add(current)
            if current == checkout_path:
                break
            current = current.parent
        with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, length=COPY_CHUNK_BYTES)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        destination.chmod(0o600)
        os.chown(destination, build_user.uid, build_user.gid)
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        directory.chmod(0o700)
        os.chown(directory, build_user.uid, build_user.gid)
    return checkout_path


def resolve_aur_build_user(raw_uid: str | None = None) -> AurBuildUser:
    uid_text = raw_uid if raw_uid is not None else os.environ.get("PKEXEC_UID", "")
    try:
        uid = int(uid_text, 10)
    except (TypeError, ValueError) as exc:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Could not identify the unprivileged user for the AUR build.",
            )
        ) from exc
    if uid <= 0:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "AUR packages must not be built as root.",
            )
        )
    try:
        account = pwd.getpwuid(uid)
    except KeyError as exc:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Could not identify the unprivileged user for the AUR build.",
            )
        ) from exc
    home = Path(account.pw_dir)
    if not home.is_absolute() or not home.is_dir():
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The AUR build user has no usable home directory.",
            )
        )
    return AurBuildUser(
        name=account.pw_name,
        uid=account.pw_uid,
        gid=account.pw_gid,
        home=home,
    )


def _create_user_build_directory(path: Path, build_user: AurBuildUser) -> Path:
    path.mkdir(mode=0o700)
    os.chown(path, build_user.uid, build_user.gid)
    return path


def _aur_build_environment(
    build_user: AurBuildUser,
    directories: dict[str, Path],
) -> dict[str, str]:
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(build_user.home),
        "LOGNAME": build_user.name,
        "USER": build_user.name,
        "SHELL": "/bin/bash",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "BUILDDIR": str(directories["build"]),
        "LOGDEST": str(directories["logs"]),
        "PKGDEST": str(directories["packages"]),
        "SRCDEST": str(directories["sources"]),
        "SRCPKGDEST": str(directories["source-packages"]),
        "TMPDIR": str(directories["tmp"]),
    }
    for variable in (
        "http_proxy",
        "https_proxy",
        "ftp_proxy",
        "no_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "FTP_PROXY",
        "NO_PROXY",
    ):
        value = os.environ.get(variable)
        if value:
            environment[variable] = value
    return environment


def _copy_untrusted_artifact(
    source: Path,
    destination: Path,
) -> Path:
    source_stat = source.lstat()
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "AUR artifact is not a regular non-symlink file: {path}",
            ).format(path=source)
        )

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(source, flags)
    copied_size = 0
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_dev != source_stat.st_dev
            or opened_stat.st_ino != source_stat.st_ino
        ):
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "AUR artifact changed while it was being opened.",
                )
            )
        with os.fdopen(file_descriptor, "rb", closefd=False) as source_handle:
            with destination.open("xb") as destination_handle:
                while chunk := source_handle.read(COPY_CHUNK_BYTES):
                    copied_size += len(chunk)
                    if copied_size > MAX_AUR_ARTIFACT_BYTES:
                        raise validation.PrivilegedUpdateValidationError(
                            QCoreApplication.translate(
                                "PrivilegedHelper",
                                "AUR artifact exceeds the allowed size.",
                            )
                        )
                    destination_handle.write(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
    finally:
        os.close(file_descriptor)

    final_stat = source.lstat()
    if (
        final_stat.st_dev != source_stat.st_dev
        or final_stat.st_ino != source_stat.st_ino
        or final_stat.st_size != source_stat.st_size
        or final_stat.st_mtime_ns != source_stat.st_mtime_ns
        or final_stat.st_ctime_ns != source_stat.st_ctime_ns
        or copied_size != source_stat.st_size
    ):
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "AUR artifact changed while it was being copied.",
            )
        )
    return destination
