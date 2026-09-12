from __future__ import annotations

import hashlib
import os
import platform
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import HelperEventType
from archupdater.domain.aur import (
    AurInstallTarget,
    AurPkgbuildReview,
    AurReviewFile,
    AurVcsSource,
)
from archupdater.helper.actions.pacman_prompts import PacmanPromptHandler
from archupdater.helper.actions.common import (
    EmitEvent,
    EmitLog,
    PACMAN_PATH,
    stream_command,
    stream_subprocess,
)


FLATPAK_PATH = Path("/usr/bin/flatpak")
FWUPDMGR_PATH = Path("/usr/bin/fwupdmgr")
SYSTEMD_INHIBIT_PATH = Path("/usr/bin/systemd-inhibit")
VERCMP_PATH = Path("/usr/bin/vercmp")
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9@._+-]+$")
FLATPAK_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
FIRMWARE_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9@._:+/{}/-]+$")
PACMAN_PACKAGE_FILE_SUFFIX_RE = re.compile(
    r"\.pkg\.tar(?:\.(?:zst|xz|gz|lrz|lzo|lz4|Z))?$"
)
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
VCS_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")
VCS_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
MAX_AUR_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024
MAX_AUR_BUILD_OUTPUT_FILES = 64
MAX_AUR_REVIEW_FILES = 512
MAX_AUR_REVIEW_BYTES = 16 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024


class PrivilegedUpdateValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AurBuildUser:
    name: str
    uid: int
    gid: int
    home: Path


def validate_flatpak_refs(raw_refs: object) -> list[str]:
    return _validate_string_list(
        raw_refs,
        field_name="refs",
        pattern=FLATPAK_REF_RE,
        allow_empty=False,
    )


def validate_firmware_device_id(raw_device_id: object) -> str:
    if not isinstance(raw_device_id, str):
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate("PrivilegedHelper", "`device_id` must be a string.")
        )
    device_id = raw_device_id.strip()
    if (
        not device_id
        or len(device_id) > 256
        or device_id.startswith("-")
        or "\x00" in device_id
        or not FIRMWARE_DEVICE_ID_RE.fullmatch(device_id)
    ):
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Invalid firmware device id: {device_id}",
            ).format(device_id=repr(raw_device_id))
        )
    return device_id


def validate_aur_build_review(raw_review: object) -> AurPkgbuildReview:
    if not isinstance(raw_review, dict) or set(raw_review) != {
        "package_name",
        "package_base",
        "digest",
        "files",
        "vcs_sources",
    }:
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Invalid reviewed AUR build manifest.",
            )
        )
    package_name = raw_review["package_name"]
    package_base = raw_review["package_base"]
    digest = raw_review["digest"]
    raw_files = raw_review["files"]
    raw_vcs_sources = raw_review["vcs_sources"]
    if (
        not isinstance(package_name, str)
        or not PACKAGE_NAME_RE.fullmatch(package_name)
        or not isinstance(package_base, str)
        or not PACKAGE_NAME_RE.fullmatch(package_base)
        or not isinstance(digest, str)
        or not SHA256_RE.fullmatch(digest)
        or not isinstance(raw_files, list)
        or not raw_files
        or len(raw_files) > MAX_AUR_REVIEW_FILES
        or not isinstance(raw_vcs_sources, list)
        or len(raw_vcs_sources) > 64
    ):
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Invalid reviewed AUR build manifest.",
            )
        )

    files: list[AurReviewFile] = []
    paths: list[str] = []
    total_size = 0
    tree_digest = hashlib.sha256()
    for raw_file in raw_files:
        if not isinstance(raw_file, dict) or set(raw_file) != {
            "path",
            "sha256",
            "size",
            "content",
        }:
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid reviewed AUR build manifest.",
                )
            )
        path = raw_file["path"]
        sha256 = raw_file["sha256"]
        size = raw_file["size"]
        content = raw_file["content"]
        if (
            not isinstance(path, str)
            or not path
            or len(path) > 4096
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or any(
                unicodedata.category(character) in {"Cc", "Cf", "Cs"}
                for character in path
            )
            or path in paths
            or not isinstance(sha256, str)
            or not SHA256_RE.fullmatch(sha256)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(content, str)
            or any(
                (
                    unicodedata.category(character) == "Cc"
                    and character not in {"\n", "\r", "\t"}
                )
                or unicodedata.category(character) in {"Cf", "Cs"}
                for character in content
            )
        ):
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid reviewed AUR build manifest.",
                )
            )
        raw_content = content.encode("utf-8")
        total_size += len(raw_content)
        if (
            len(raw_content) != size
            or hashlib.sha256(raw_content).hexdigest() != sha256.lower()
            or total_size > MAX_AUR_REVIEW_BYTES
        ):
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Reviewed AUR file content does not match its manifest.",
                )
            )
        paths.append(path)
        files.append(AurReviewFile(path=path, sha256=sha256.lower(), size=size, content=content))
        tree_digest.update(path.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(str(size).encode("ascii"))
        tree_digest.update(b"\0")
        tree_digest.update(sha256.lower().encode("ascii"))
        tree_digest.update(b"\0")

    if paths != sorted(paths) or tree_digest.hexdigest() != digest.lower():
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Reviewed AUR tree digest does not match its manifest.",
            )
        )
    if not {"PKGBUILD", ".SRCINFO"}.issubset(set(paths)):
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The reviewed AUR build manifest is incomplete.",
            )
        )
    vcs_sources: list[AurVcsSource] = []
    seen_source_names: set[str] = set()
    for raw_source in raw_vcs_sources:
        if not isinstance(raw_source, dict) or set(raw_source) != {
            "name",
            "url",
            "branch",
            "commit",
        }:
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper", "Invalid reviewed AUR VCS source lock."
                )
            )
        name = raw_source["name"]
        url = raw_source["url"]
        branch = raw_source["branch"]
        commit = raw_source["commit"]
        if (
            not isinstance(name, str)
            or not PACKAGE_NAME_RE.fullmatch(name)
            or name in seen_source_names
            or not isinstance(url, str)
            or len(url) > 2048
            or not re.fullmatch(r"(?:https|git|ssh)://[^\s]+", url)
            or (branch is not None and not isinstance(branch, str))
            or (
                isinstance(branch, str)
                and (
                    not branch
                    or len(branch) > 512
                    or not VCS_BRANCH_RE.fullmatch(branch)
                    or branch.startswith(("-", "/"))
                    or ".." in branch.split("/")
                )
            )
            or not isinstance(commit, str)
            or not VCS_COMMIT_RE.fullmatch(commit)
        ):
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper", "Invalid reviewed AUR VCS source lock."
                )
            )
        seen_source_names.add(name)
        vcs_sources.append(
            AurVcsSource(
                name=name,
                url=url,
                branch=branch,
                commit=commit.lower(),
            )
        )

    return AurPkgbuildReview(
        package_name=package_name,
        package_base=package_base,
        pkgbuild=next(file.content for file in files if file.path == "PKGBUILD"),
        digest=digest.lower(),
        files=tuple(files),
        vcs_sources=tuple(vcs_sources),
    )


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
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Could not identify the unprivileged user for the AUR build.",
            )
        ) from exc
    if uid <= 0:
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "AUR packages must not be built as root.",
            )
        )
    try:
        account = pwd.getpwuid(uid)
    except KeyError as exc:
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Could not identify the unprivileged user for the AUR build.",
            )
        ) from exc
    home = Path(account.pw_dir)
    if not home.is_absolute() or not home.is_dir():
        raise PrivilegedUpdateValidationError(
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


def run_system_update(
    _expected_versions: dict[str, str],
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not _require_executable(PACMAN_PATH, "pacman", emit_event=emit_event, emit_log=emit_log):
        return 2

    emit_event(HelperEventType.STATUS, value="running")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Running system package update with pacman.",
        )
    )
    command = [str(PACMAN_PATH), "-Syu", "--confirm", "--color", "never"]
    return _run_helper_command(
        _critical_command(command),
        success_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "System update completed successfully.",
        ),
        failure_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "pacman exited with code {code}.",
        ),
        emit_event=emit_event,
        emit_log=emit_log,
        survive_parent_exit=True,
    )


def install_reviewed_aur(
    review: AurPkgbuildReview,
    expected_version: str,
    *,
    expected_package_base: str,
    current_version: str = "",
    dynamic_version: bool = False,
    build_user: AurBuildUser,
    build_root: Path,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    return install_reviewed_aur_group(
        review,
        [
            AurInstallTarget(
                review.package_name,
                expected_package_base,
                expected_version,
                current_version=current_version,
                dynamic_version=dynamic_version,
            )
        ],
        expected_package_base=expected_package_base,
        build_user=build_user,
        build_root=build_root,
        emit_event=emit_event,
        emit_log=emit_log,
    )


def install_reviewed_aur_group(
    review: AurPkgbuildReview,
    targets: list[AurInstallTarget],
    *,
    expected_package_base: str,
    build_user: AurBuildUser,
    build_root: Path,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    makepkg_path = Path("/usr/bin/makepkg")
    if not _require_executable(PACMAN_PATH, "pacman", emit_event=emit_event, emit_log=emit_log):
        return 2
    if not _require_executable(
        makepkg_path,
        "makepkg",
        emit_event=emit_event,
        emit_log=emit_log,
    ):
        return 2

    emit_event(HelperEventType.STATUS, value="running")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Building the reviewed AUR package as an unprivileged user.",
        )
    )
    action_root: Path | None = None
    try:
        _validate_review_targets(
            review,
            package_names={target.package_name for target in targets},
            expected_package_base=expected_package_base,
        )
        _validate_current_aur_versions(targets, emit_log=emit_log)
        action_root = Path(
            tempfile.mkdtemp(
                prefix=f"{review.package_name}-",
                dir=build_root,
            )
        )
        action_root.chmod(0o711)
        sealed_checkout = _seal_aur_build_checkout(review, build_root=action_root)
        workspace = action_root / "workspace"
        workspace.mkdir(mode=0o700)
        os.chown(workspace, build_user.uid, build_user.gid)
        checkout_path = _create_user_aur_build_checkout(
            sealed_checkout,
            review,
            build_root=workspace,
            build_user=build_user,
        )
        work_directories = {
            name: _create_user_build_directory(workspace / name, build_user)
            for name in ("build", "logs", "packages", "sources", "source-packages", "tmp")
        }
        environment = _aur_build_environment(build_user, work_directories)

        def demote_build_process() -> None:
            os.initgroups(build_user.name, build_user.gid)
            os.setgid(build_user.gid)
            os.setuid(build_user.uid)
            os.umask(0o022)

        return_code, _output = stream_subprocess(
            [
                str(makepkg_path),
                "--dir",
                str(checkout_path),
                "--force",
                "--noconfirm",
                "--noprogressbar",
            ],
            emit_log=emit_log,
            env=environment,
            preexec_fn=demote_build_process,
            start_new_session=True,
            timeout_seconds=6 * 60 * 60,
        )
        if return_code != 0:
            message = QCoreApplication.translate(
                "PrivilegedHelper",
                "makepkg exited with code {code}.",
            ).format(code=return_code)
            emit_event(HelperEventType.COMPLETED, success=False, message=message)
            return 3

        if any(target.dynamic_version for target in targets):
            if not review.vcs_sources:
                raise PrivilegedUpdateValidationError(
                    QCoreApplication.translate(
                        "PrivilegedHelper",
                        "The development AUR update has no approved VCS source commit.",
                    )
                )
            _verify_vcs_source_commits(
                review,
                build_directory=work_directories["build"],
            )

        verified_root = action_root / "verified"
        verified_root.mkdir(mode=0o700)
        verified_artifacts = [
            _verified_built_artifact(
                work_directories["packages"],
                package_name=target.package_name,
                expected_version=target.version,
                current_version=target.current_version,
                dynamic_version=target.dynamic_version,
                private_directory=verified_root / target.package_name,
                emit_log=emit_log,
            )
            for target in targets
        ]
        artifacts = [artifact for artifact, _version in verified_artifacts]
        actual_versions = {
            target.package_name: actual_version
            for target, (_artifact, actual_version) in zip(targets, verified_artifacts, strict=True)
        }
        return _run_helper_command(
            _critical_command([
                str(PACMAN_PATH),
                "-U",
                "--confirm",
                "--needed",
                "--color",
                "never",
                "--",
                *[str(artifact) for artifact in artifacts],
            ]),
            success_message=QCoreApplication.translate(
                "PrivilegedHelper",
                "Reviewed AUR package installed successfully.",
            ),
            failure_message=QCoreApplication.translate(
                "PrivilegedHelper",
                "pacman exited with code {code}.",
            ),
            emit_event=emit_event,
            emit_log=emit_log,
            survive_parent_exit=True,
            success_payload={"actual_versions": actual_versions},
        )
    except (OSError, subprocess.SubprocessError, PrivilegedUpdateValidationError) as exc:
        message = str(exc) or QCoreApplication.translate(
            "PrivilegedHelper",
            "Could not build or verify the reviewed AUR package.",
        )
        emit_log(message)
        emit_event(HelperEventType.COMPLETED, success=False, message=message)
        return 4
    finally:
        if action_root is not None:
            shutil.rmtree(action_root, ignore_errors=True)


def run_flatpak_system_update(
    refs: list[str],
    expected_versions: dict[str, str],
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not _require_executable(FLATPAK_PATH, "flatpak", emit_event=emit_event, emit_log=emit_log):
        return 2

    emit_event(HelperEventType.STATUS, value="preparing")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Running system Flatpak update.",
        )
    )
    preview_code, preview_output = stream_command(
        [
            str(FLATPAK_PATH),
            "remote-ls",
            "--system",
            "--updates",
            "--columns=ref,version,branch",
        ],
        emit_log=emit_log,
    )
    if preview_code != 0:
        message = QCoreApplication.translate(
            "PrivilegedHelper",
            "Could not prepare the Flatpak transaction (exit code {code}).",
        ).format(code=preview_code)
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=message,
            reason="preparation_failed",
        )
        return 3
    available_versions = _parse_tab_versions(preview_output)
    actual_versions = {
        ref: available_versions[ref]
        for ref in refs
        if available_versions.get(ref)
    }
    if actual_versions != expected_versions:
        message = QCoreApplication.translate(
            "PrivilegedHelper",
            "The Flatpak transaction changed after it was reviewed.",
        )
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=message,
            reason="plan_changed",
            actual_versions=actual_versions,
        )
        return 3

    emit_event(HelperEventType.STATUS, value="running")
    update_code, _update_output = stream_command(
        _critical_command([
            str(FLATPAK_PATH),
            "update",
            "--system",
            "--assumeyes",
            "--noninteractive",
            "--",
            *refs,
        ]),
        emit_log=emit_log,
        survive_parent_exit=True,
    )
    if update_code != 0:
        message = QCoreApplication.translate(
            "PrivilegedHelper",
            "flatpak exited with code {code}.",
        ).format(code=update_code)
        emit_event(HelperEventType.COMPLETED, success=False, message=message)
        return 3

    verify_code, verify_output = stream_command(
        [
            str(FLATPAK_PATH),
            "remote-ls",
            "--system",
            "--updates",
            "--columns=ref,version,branch",
        ],
        emit_log=emit_log,
    )
    remaining_refs = set(refs).intersection(_parse_tab_versions(verify_output))
    if verify_code != 0 or remaining_refs:
        message = QCoreApplication.translate(
            "PrivilegedHelper",
            "Flatpak finished without installing all selected updates.",
        )
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=message,
            reason="postcondition_failed",
        )
        return 3

    emit_event(
        HelperEventType.COMPLETED,
        success=True,
        message=QCoreApplication.translate(
            "PrivilegedHelper",
            "System Flatpak update completed successfully.",
        ),
    )
    return 0


def run_flatpak_system_cleanup(
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not _require_executable(FLATPAK_PATH, "flatpak", emit_event=emit_event, emit_log=emit_log):
        return 2

    emit_event(HelperEventType.STATUS, value="running")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Removing unused system Flatpak runtimes.",
        )
    )
    return _run_helper_command(
        [
            str(FLATPAK_PATH),
            "uninstall",
            "--system",
            "--unused",
            "--noninteractive",
        ],
        success_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "System Flatpak cleanup completed successfully.",
        ),
        failure_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "flatpak exited with code {code}.",
        ),
        emit_event=emit_event,
        emit_log=emit_log,
    )


def run_firmware_update(
    device_id: str,
    expected_version: str,
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    if not _require_executable(FWUPDMGR_PATH, "fwupdmgr", emit_event=emit_event, emit_log=emit_log):
        return 2

    emit_event(HelperEventType.STATUS, value="running")
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Running firmware update for device {device}.",
        ).format(device=device_id)
    )
    return _run_helper_command(
        _critical_command([
            str(FWUPDMGR_PATH),
            "install",
            "--assume-yes",
            "--no-reboot-check",
            "--no-device-prompt",
            "--",
            device_id,
            expected_version,
        ]),
        success_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "Firmware update completed successfully.",
        ),
        failure_message=QCoreApplication.translate(
            "PrivilegedHelper",
            "fwupdmgr exited with code {code}.",
        ),
        emit_event=emit_event,
        emit_log=emit_log,
        survive_parent_exit=True,
    )


def _parse_tab_versions(lines: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for raw_line in lines:
        columns = raw_line.split("\t")
        if len(columns) < 2:
            continue
        ref = columns[0].strip()
        version = columns[1].strip()
        branch = columns[2].strip() if len(columns) >= 3 else ""
        if ref:
            versions[ref] = version or branch
    return versions


def _critical_command(command: list[str]) -> list[str]:
    if not SYSTEMD_INHIBIT_PATH.exists():
        return command
    return [
        str(SYSTEMD_INHIBIT_PATH),
        "--what=shutdown:sleep",
        "--who=ArchUpdater",
        "--why=Installing critical system updates",
        "--mode=block",
        "--",
        *command,
    ]


def _validate_review_target(
    review: AurPkgbuildReview,
    *,
    expected_package_base: str,
) -> None:
    _validate_review_targets(
        review,
        package_names={review.package_name},
        expected_package_base=expected_package_base,
    )


def _validate_review_targets(
    review: AurPkgbuildReview,
    *,
    package_names: set[str],
    expected_package_base: str,
) -> None:
    if review.package_base != expected_package_base:
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The reviewed AUR package base does not match the authorized update plan.",
            )
        )
    srcinfo = next(
        (reviewed.content for reviewed in review.files if reviewed.path == ".SRCINFO"),
        "",
    )
    declared_base = ""
    declared_packages: set[str] = set()
    for raw_line in srcinfo.splitlines():
        key, separator, value = raw_line.strip().partition("=")
        if separator != "=":
            continue
        key = key.strip()
        value = value.strip()
        if key == "pkgbase":
            declared_base = value
        elif key == "pkgname":
            declared_packages.add(value)
    if (
        declared_base != expected_package_base
        or not package_names
        or not package_names.issubset(declared_packages)
        or review.package_name not in package_names
    ):
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The reviewed .SRCINFO does not declare the authorized AUR package.",
            )
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
        raise PrivilegedUpdateValidationError(
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
            or candidate_stat.st_size > MAX_AUR_ARTIFACT_BYTES
        ):
            raise PrivilegedUpdateValidationError(
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
                raise PrivilegedUpdateValidationError(
                    QCoreApplication.translate(
                        "PrivilegedHelper",
                        "Built development AUR package did not produce a newer concrete version.",
                    )
                )
        elif identity[1] != expected_version:
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Built AUR package version mismatch: expected {expected}, found {actual}.",
                ).format(expected=expected_version, actual=identity[1])
            )
        if identity[2] not in {platform.machine(), "any"}:
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Built AUR package architecture is not valid for this system.",
                )
            )
        matches.append((candidate, identity))
    if len(matches) != 1:
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Expected exactly one verified artifact for {package}; found {count}.",
            ).format(package=package_name, count=len(matches))
        )
    source, expected_identity = matches[0]
    private_directory.mkdir(mode=0o700)
    copied = _copy_untrusted_artifact(
        source,
        private_directory / "artifact.pkg.tar",
    )
    if _package_file_identity(copied, emit_log=emit_log) != expected_identity:
        raise PrivilegedUpdateValidationError(
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
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper", "Could not compare AUR package versions."
            )
        ) from exc
    try:
        comparison = int(result.stdout.strip())
    except ValueError as exc:
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper", "Could not compare AUR package versions."
            )
        ) from exc
    if result.returncode != 0 or comparison not in {-1, 0, 1}:
        raise PrivilegedUpdateValidationError(
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
            raise PrivilegedUpdateValidationError(
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
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper", "Could not verify an AUR VCS source commit."
                )
            ) from exc
        actual_commit = result.stdout.strip().lower()
        if result.returncode != 0 or actual_commit != source.commit:
            raise PrivilegedUpdateValidationError(
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
    return_code, output = stream_command(
        [
            str(PACMAN_PATH),
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
    expected_versions = {
        target.package_name: target.current_version for target in dynamic_targets
    }
    if return_code != 0 or actual_versions != expected_versions:
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The installed AUR development package changed after the update was approved.",
            )
        )


def _validate_string_list(
    raw_values: object,
    *,
    field_name: str,
    pattern: re.Pattern[str],
    allow_empty: bool,
) -> list[str]:
    if not isinstance(raw_values, list):
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "`{field_name}` must be an array.",
            ).format(field_name=field_name)
        )
    if not raw_values and not allow_empty:
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "`{field_name}` must contain at least one item.",
            ).format(field_name=field_name)
        )

    validated: list[str] = []
    for raw_value in raw_values:
        if not isinstance(raw_value, str):
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid `{field_name}` item: {value}",
                ).format(field_name=field_name, value=repr(raw_value))
            )
        value = raw_value.strip()
        if (
            not value
            or len(value) > 512
            or value.startswith("-")
            or "\x00" in value
            or not pattern.fullmatch(value)
            or ".." in Path(value).parts
        ):
            raise PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid `{field_name}` item: {value}",
                ).format(field_name=field_name, value=repr(raw_value))
            )
        if value not in validated:
            validated.append(value)
    return validated


def _copy_untrusted_artifact(
    source: Path,
    destination: Path,
) -> Path:
    source_stat = source.lstat()
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise PrivilegedUpdateValidationError(
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
            raise PrivilegedUpdateValidationError(
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
                        raise PrivilegedUpdateValidationError(
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
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "AUR artifact changed while it was being copied.",
            )
        )
    return destination


def _package_file_identity(path: Path, *, emit_log: EmitLog) -> tuple[str, str, str]:
    return_code, output = stream_command(
        [
            "/usr/bin/env",
            "LC_ALL=C",
            str(PACMAN_PATH),
            "-Qip",
            "--color",
            "never",
            "--",
            str(path),
        ],
        emit_log=emit_log,
    )
    if return_code != 0:
        raise PrivilegedUpdateValidationError(
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
        raise PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Invalid AUR package artifact identity.",
            )
        )
    return identity


def _require_executable(
    path: Path,
    command_name: str,
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> bool:
    if path.exists():
        return True
    emit_log(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "{command} executable not found at {path}.",
        ).format(command=command_name, path=path)
    )
    emit_event(
        HelperEventType.COMPLETED,
        success=False,
        message=QCoreApplication.translate(
            "PrivilegedHelper",
            "{command} is not available on this system.",
        ).format(command=command_name),
    )
    return False


def _run_helper_command(
    command: list[str],
    *,
    success_message: str,
    failure_message: str,
    emit_event: EmitEvent,
    emit_log: EmitLog,
    survive_parent_exit: bool = False,
    success_payload: dict[str, object] | None = None,
) -> int:
    if str(PACMAN_PATH) in command:
        return_code, _output = stream_command(
            command,
            emit_log=emit_log,
            survive_parent_exit=survive_parent_exit,
            input_handler=PacmanPromptHandler(emit_event=emit_event, emit_log=emit_log),
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    elif survive_parent_exit:
        return_code, _output = stream_command(
            command,
            emit_log=emit_log,
            survive_parent_exit=True,
        )
    else:
        return_code, _output = stream_command(command, emit_log=emit_log)
    if return_code != 0:
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=failure_message.format(code=return_code),
        )
        return 3

    emit_event(
        HelperEventType.COMPLETED,
        success=True,
        message=success_message,
        **(success_payload or {}),
    )
    return 0
