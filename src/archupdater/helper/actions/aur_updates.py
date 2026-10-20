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
    for executable, name in (
        (update_commands.PACMAN_PATH, "pacman"),
        (makepkg_path, "makepkg"),
        (aur_workspace.SYSTEMD_RUN_PATH, "systemd-run"),
    ):
        if not update_commands._require_executable(
            executable, name, emit_event=emit_event, emit_log=emit_log,
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
    sandbox: aur_workspace.AurBuildSandbox | None = None
    try:
        aur_review._validate_review_targets(
            review,
            package_names={target.package_name for target in targets},
            expected_package_base=expected_package_base,
        )
        verify_vcs = any(target.dynamic_version for target in targets)
        if verify_vcs and not review.vcs_sources:
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "The development AUR update has no approved VCS source commit.",
                )
            )
        aur_artifacts._validate_current_aur_versions(targets, emit_log=emit_log)
        aur_workspace.remove_stale_build_states()
        action_root = Path(
            tempfile.mkdtemp(
                prefix=f"{review.package_name}-",
                dir=build_root,
            )
        )
        action_root.chmod(0o711)
        input_directory = action_root / "input"
        aur_workspace.prepare_build_input(
            review, input_directory, build_user=build_user, emit_log=emit_log,
        )
        # The build runs as a transient DynamicUser= account in a unit whose state
        # is reachable only by root: other processes of the desktop user can no
        # longer alter the reviewed sources or replace the built package.
        sandbox = aur_workspace.AurBuildSandbox.create()
        if verify_vcs:
            # Verify approved commits before upstream code can run: code built from
            # a changed remote could otherwise rewrite its own Git metadata.
            return_code = _run_build_phase(
                sandbox, input_directory, aur_workspace.BUILD_PHASE_FETCH, emit_log=emit_log,
            )
            if return_code == 0:
                state_directory = aur_workspace.verified_state_directory(
                    sandbox.state_directory
                )
                aur_artifacts._verify_vcs_mirror_commits(
                    review,
                    sources_directory=aur_workspace.verified_state_directory(
                        state_directory / "sources"
                    ),
                )
                return_code = _run_build_phase(
                    sandbox, input_directory, aur_workspace.BUILD_PHASE_BUILD,
                    emit_log=emit_log,
                )
        else:
            return_code = _run_build_phase(
                sandbox, input_directory, aur_workspace.BUILD_PHASE_FULL, emit_log=emit_log,
            )
        if return_code != 0:
            message = QCoreApplication.translate(
                "PrivilegedHelper",
                "makepkg exited with code {code}.",
            ).format(code=return_code)
            emit_event(HelperEventType.COMPLETED, success=False, message=message, changed=False)
            return 3

        state_directory = aur_workspace.verified_state_directory(sandbox.state_directory)
        packages_directory = aur_workspace.verified_state_directory(
            state_directory / "packages"
        )

        verified_root = action_root / "verified"
        verified_root.mkdir(mode=0o700)
        verified_artifacts = [
            aur_artifacts._verified_built_artifact(
                packages_directory,
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
        if sandbox is not None:
            aur_workspace.stop_build_unit(sandbox)
            aur_workspace.remove_build_state(sandbox.token)
        if action_root is not None:
            _remove_action_root(action_root)


def _run_build_phase(
    sandbox: aur_workspace.AurBuildSandbox,
    input_directory: Path,
    phase: str,
    *,
    emit_log: EmitLog,
) -> int:
    return_code, _output = update_commands.stream_subprocess(
        aur_workspace.build_unit_command(sandbox, input_directory, phase),
        emit_log=emit_log,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        start_new_session=True,
        timeout_seconds=aur_workspace.BUILD_UNIT_TIMEOUT_SECONDS,
    )
    # Nothing may still write to the state once root starts reading it.
    aur_workspace.stop_build_unit(sandbox)
    return return_code


def _remove_action_root(action_root: Path) -> None:
    # The sealed input is read-only; only root may delete inside it without this.
    for directory, _subdirectories, _files in os.walk(action_root):
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
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
