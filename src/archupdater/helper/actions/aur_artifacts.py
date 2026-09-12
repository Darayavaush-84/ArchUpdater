from __future__ import annotations

import platform
import re
import stat
import subprocess
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.domain.aur import (
    AurInstallTarget,
    AurPkgbuildReview,
)
from archupdater.helper.actions import aur_workspace, update_commands, validation
from archupdater.helper.actions.common import (
    EmitLog,
)

VERCMP_PATH = Path("/usr/bin/vercmp")


PACMAN_PACKAGE_FILE_SUFFIX_RE = re.compile(r"\.pkg\.tar(?:\.(?:zst|xz|gz|lrz|lzo|lz4|Z))?$")


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


MAX_AUR_BUILD_OUTPUT_FILES = 64


def _verified_built_artifact(
    output_directory: Path,
    *,
    package_name: str,
    expected_version: str,
    current_version: str,
    dynamic_version: bool,
    private_directory: Path,
    emit_log: EmitLog,
) -> tuple[Path, str]:
    entries = sorted(output_directory.iterdir(), key=lambda path: path.name)
    if len(entries) > MAX_AUR_BUILD_OUTPUT_FILES:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The AUR build produced too many output files.",
            )
        )
    matches: list[tuple[Path, tuple[str, str, str]]] = []
    for candidate in entries:
        if not PACMAN_PACKAGE_FILE_SUFFIX_RE.search(candidate.name):
            continue
        candidate_stat = candidate.lstat()
        if (
            stat.S_ISLNK(candidate_stat.st_mode)
            or not stat.S_ISREG(candidate_stat.st_mode)
            or candidate_stat.st_size <= 0
            or candidate_stat.st_size > aur_workspace.MAX_AUR_ARTIFACT_BYTES
        ):
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "AUR build output is not a valid regular package file.",
                )
            )
        identity = _package_file_identity(candidate, emit_log=emit_log)
        if identity[0] != package_name:
            continue
        if dynamic_version:
            if (
                expected_version != "latest-commit"
                or not current_version
                or identity[1] == "latest-commit"
                or _compare_pacman_versions(identity[1], current_version) <= 0
            ):
                raise validation.PrivilegedUpdateValidationError(
                    QCoreApplication.translate(
                        "PrivilegedHelper",
                        "Built development AUR package did not produce a newer concrete version.",
                    )
                )
        elif identity[1] != expected_version:
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Built AUR package version mismatch: expected {expected}, found {actual}.",
                ).format(expected=expected_version, actual=identity[1])
            )
        if identity[2] not in {platform.machine(), "any"}:
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Built AUR package architecture is not valid for this system.",
                )
            )
        matches.append((candidate, identity))
    if len(matches) != 1:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Expected exactly one verified artifact for {package}; found {count}.",
            ).format(package=package_name, count=len(matches))
        )
    source, expected_identity = matches[0]
    private_directory.mkdir(mode=0o700)
    copied = aur_workspace._copy_untrusted_artifact(
        source,
        private_directory / "artifact.pkg.tar",
    )
    if _package_file_identity(copied, emit_log=emit_log) != expected_identity:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "AUR artifact identity changed while it was being secured.",
            )
        )
    return copied, expected_identity[1]


def _compare_pacman_versions(version_a: str, version_b: str) -> int:
    try:
        result = subprocess.run(
            [str(VERCMP_PATH), version_a, version_b],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
            },
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper", "Could not compare AUR package versions."
            )
        ) from exc
    try:
        comparison = int(result.stdout.strip())
    except ValueError as exc:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper", "Could not compare AUR package versions."
            )
        ) from exc
    if result.returncode != 0 or comparison not in {-1, 0, 1}:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper", "Could not compare AUR package versions."
            )
        )
    return comparison


def _verify_vcs_source_commits(
    review: AurPkgbuildReview,
    *,
    build_directory: Path,
) -> None:
    source_root = build_directory / review.package_base / "src"
    resolved_root = source_root.resolve(strict=True)
    for source in review.vcs_sources:
        source_path = source_root / source.name
        try:
            if source_path.is_symlink() or not source_path.is_dir():
                raise OSError("not a directory")
            resolved_source = source_path.resolve(strict=True)
            resolved_source.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Could not locate an approved AUR VCS source checkout.",
                )
            ) from exc
        try:
            result = subprocess.run(
                [
                    "/usr/bin/git",
                    "-c",
                    f"safe.directory={resolved_source}",
                    "-C",
                    str(resolved_source),
                    "rev-parse",
                    "--verify",
                    "HEAD",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": "/nonexistent",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_OPTIONAL_LOCKS": "0",
                    "LC_ALL": "C.UTF-8",
                },
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper", "Could not verify an AUR VCS source commit."
                )
            ) from exc
        actual_commit = result.stdout.strip().lower()
        if result.returncode != 0 or actual_commit != source.commit:
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "An AUR VCS source changed after the update was approved.",
                )
            )


def _validate_current_aur_versions(
    targets: list[AurInstallTarget],
    *,
    emit_log: EmitLog,
) -> None:
    dynamic_targets = [target for target in targets if target.dynamic_version]
    if not dynamic_targets:
        return
    return_code, output = update_commands.stream_command(
        [
            str(update_commands.PACMAN_PATH),
            "-Q",
            "--color",
            "never",
            "--",
            *[target.package_name for target in dynamic_targets],
        ],
        emit_log=emit_log,
    )
    actual_versions: dict[str, str] = {}
    for raw_line in output:
        line = ANSI_ESCAPE_RE.sub("", raw_line).strip()
        name, separator, version = line.partition(" ")
        if separator and name and version:
            actual_versions[name] = version.strip()
    expected_versions = {target.package_name: target.current_version for target in dynamic_targets}
    if return_code != 0 or actual_versions != expected_versions:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The installed AUR development package changed after the update was approved.",
            )
        )


def _package_file_identity(path: Path, *, emit_log: EmitLog) -> tuple[str, str, str]:
    return_code, output = update_commands.stream_command(
        [
            "/usr/bin/env",
            "LC_ALL=C",
            str(update_commands.PACMAN_PATH),
            "-Qip",
            "--color",
            "never",
            "--",
            str(path),
        ],
        emit_log=emit_log,
    )
    if return_code != 0:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Could not inspect an AUR package artifact.",
            )
        )
    fields: dict[str, str] = {}
    for line in output:
        clean_line = ANSI_ESCAPE_RE.sub("", line)
        key, separator, value = clean_line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    identity = (
        fields.get("Name", ""),
        fields.get("Version", ""),
        fields.get("Architecture", ""),
    )
    if not all(identity):
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Invalid AUR package artifact identity.",
            )
        )
    return identity
