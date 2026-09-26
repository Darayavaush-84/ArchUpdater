from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import HelperEventType
from archupdater.domain.aur import (
    AurInstallTarget,
    AurPkgbuildReview,
)
from archupdater.helper.actions import (
    aur_artifacts,
    aur_review,
    aur_workspace,
    update_commands,
    validation,
)
from archupdater.helper.actions.common import (
    EmitEvent,
    EmitLog,
)


def install_reviewed_aur(
    review: AurPkgbuildReview,
    expected_version: str,
    *,
    expected_package_base: str,
    current_version: str = "",
    dynamic_version: bool = False,
    build_user: aur_workspace.AurBuildUser,
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
    build_user: aur_workspace.AurBuildUser,
    build_root: Path,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    makepkg_path = Path("/usr/bin/makepkg")
    if not update_commands._require_executable(
        update_commands.PACMAN_PATH, "pacman", emit_event=emit_event, emit_log=emit_log
    ):
        return 2
    if not update_commands._require_executable(
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
        aur_review._validate_review_targets(
            review,
            package_names={target.package_name for target in targets},
            expected_package_base=expected_package_base,
        )
        aur_artifacts._validate_current_aur_versions(targets, emit_log=emit_log)
        action_root = Path(
            tempfile.mkdtemp(
                prefix=f"{review.package_name}-",
                dir=build_root,
            )
        )
        action_root.chmod(0o711)
        sealed_checkout = aur_workspace._seal_aur_build_checkout(review, build_root=action_root)
        workspace = action_root / "workspace"
        workspace.mkdir(mode=0o700)
        os.chown(workspace, build_user.uid, build_user.gid)
        checkout_path = aur_workspace._create_user_aur_build_checkout(
            sealed_checkout,
            review,
            build_root=workspace,
            build_user=build_user,
        )
        work_directories = {
            name: aur_workspace._create_user_build_directory(workspace / name, build_user)
            for name in ("build", "logs", "packages", "sources", "source-packages", "tmp")
        }
        environment = aur_workspace._aur_build_environment(build_user, work_directories)

        def demote_build_process() -> None:
            os.initgroups(build_user.name, build_user.gid)
            os.setgid(build_user.gid)
            os.setuid(build_user.uid)
            os.umask(0o022)

        return_code, _output = update_commands.stream_subprocess(
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
            emit_event(HelperEventType.COMPLETED, success=False, message=message, changed=False)
            return 3

        if any(target.dynamic_version for target in targets):
            if not review.vcs_sources:
                raise validation.PrivilegedUpdateValidationError(
                    QCoreApplication.translate(
                        "PrivilegedHelper",
                        "The development AUR update has no approved VCS source commit.",
                    )
                )
            aur_artifacts._verify_vcs_source_commits(
                review,
                build_directory=work_directories["build"],
            )

        verified_root = action_root / "verified"
        verified_root.mkdir(mode=0o700)
        verified_artifacts = [
            aur_artifacts._verified_built_artifact(
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
        expected_versions = {
            target.package_name: version
            for target, (_artifact, version) in zip(targets, verified_artifacts, strict=True)
        }
        return _install_verified_artifacts(
            artifacts, expected_versions, emit_event=emit_event, emit_log=emit_log,
        )
    except (OSError, subprocess.SubprocessError, validation.PrivilegedUpdateValidationError) as exc:
        message = str(exc) or QCoreApplication.translate(
            "PrivilegedHelper",
            "Could not build or verify the reviewed AUR package.",
        )
        emit_log(message)
        emit_event(HelperEventType.COMPLETED, success=False, message=message, changed=False)
        return 4
    finally:
        if action_root is not None:
            shutil.rmtree(action_root, ignore_errors=True)


def _install_verified_artifacts(
    artifacts: list[Path],
    expected_versions: dict[str, str],
    *,
    emit_event: EmitEvent,
    emit_log: EmitLog,
) -> int:
    # Query after the potentially long build, immediately around pacman -U.
    before = update_commands.installed_package_versions()
    failure_message = QCoreApplication.translate(
        "PrivilegedHelper", "Could not build or verify the reviewed AUR package.",
    )
    if before is None:
        emit_log("Could not read installed package versions before the AUR transaction.")
        emit_event(
            HelperEventType.COMPLETED, success=False, message=failure_message,
            reason="preparation_failed", changed=False,
        )
        return 3

    verification_failed = False

    def report_result(event: HelperEventType, **payload: object) -> None:
        nonlocal verification_failed
        if event is HelperEventType.COMPLETED:
            after = update_commands.installed_package_versions()
            payload["changed"] = None if after is None else before != after
            payload["actual_versions"] = (
                {name: after[name] for name in expected_versions if name in after}
                if after is not None else {}
            )
            if after is None or (
                payload.get("success") is True
                and payload["actual_versions"] != expected_versions
            ):
                verification_failed = True
                emit_log("Could not verify all installed AUR package versions after the transaction.")
                payload.update(
                    success=False, message=failure_message, reason="postcondition_failed",
                )
            elif payload.get("success") is True and payload["changed"] is False:
                payload["message"] = QCoreApplication.translate(
                    "BatchUpdateRunner", "No selected updates were installed.",
                )
        emit_event(event, **payload)

    code = update_commands._run_helper_command(
        update_commands._critical_command([
            str(update_commands.PACMAN_PATH), "-U", "--confirm", "--needed",
            "--color", "never", "--", *map(str, artifacts),
        ]),
        success_message=QCoreApplication.translate(
            "PrivilegedHelper", "Reviewed AUR package installed successfully.",
        ),
        failure_message=QCoreApplication.translate(
            "PrivilegedHelper", "pacman exited with code {code}.",
        ),
        emit_event=report_result, emit_log=emit_log, survive_parent_exit=True,
    )
    return 3 if verification_failed else code
