from __future__ import annotations

import os
import sys
import json
import re
import signal
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.helper.actions.privileged_updates import (
    PrivilegedUpdateValidationError,
    install_reviewed_aur,
    install_reviewed_aur_group,
    resolve_aur_build_user,
    run_firmware_update,
    run_flatpak_system_cleanup,
    run_flatpak_system_update,
    run_system_update,
    validate_aur_build_review,
    validate_firmware_device_id,
    validate_flatpak_refs,
)
from archupdater.helper.actions.support_packages import (
    SupportPackageValidationError,
    install_support_packages,
    remove_support_packages,
    validate_package_list,
)
from archupdater.i18n.manager import TranslationManager, resolve_language_code
from archupdater.application.helper_protocol import HelperAction, HelperEventType
from archupdater.domain.aur import AurInstallTarget, AurPkgbuildReview
from archupdater.process_lifecycle import set_parent_death_signal


class HelperValidationError(ValueError):
    pass


MAX_HELPER_REQUEST_CHARACTERS = 24 * 1024 * 1024


class HelperAuthorizationScope(str, Enum):
    SUPPORT_PACKAGES = "support-packages"
    UPDATE_SESSION = "update-session"


AUTH_SCOPE_ACTIONS = {
    HelperAuthorizationScope.SUPPORT_PACKAGES: frozenset(
        {
            HelperAction.INSTALL_SUPPORT_PACKAGES,
            HelperAction.REMOVE_SUPPORT_PACKAGES,
        }
    ),
    HelperAuthorizationScope.UPDATE_SESSION: frozenset(
        {
            HelperAction.RUN_SYSTEM_UPDATE,
            HelperAction.RUN_FLATPAK_SYSTEM_UPDATE,
            HelperAction.RUN_FLATPAK_SYSTEM_CLEANUP,
            HelperAction.RUN_FIRMWARE_UPDATE,
            HelperAction.INITIALIZE_UPDATE_SESSION,
            HelperAction.INSTALL_REVIEWED_AUR,
            HelperAction.INSTALL_REVIEWED_AUR_GROUP,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class ValidatedHelperRequest:
    action: HelperAction
    package_names: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    device_id: str = ""
    aur_targets: list[AurInstallTarget] = field(default_factory=list)
    aur_review: AurPkgbuildReview | None = None
    expected_version: str = ""
    expected_versions: dict[str, str] = field(default_factory=dict)


def emit_event(event_type: HelperEventType, **payload: object) -> None:
    event = {"event": event_type.value, **payload}
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def emit_log(message: str) -> None:
    emit_event(HelperEventType.LOG, message=message)


def _raise_termination(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def _requested_language_code(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    raw_value = str(payload.get("language_code") or "").strip()
    if not raw_value:
        return None
    return resolve_language_code(raw_value)


def validate_request(
    payload: object,
    *,
    authorization_scope: HelperAuthorizationScope | None = None,
) -> ValidatedHelperRequest:
    if not isinstance(payload, dict):
        raise HelperValidationError(
            QCoreApplication.translate("PrivilegedHelper", "Request must be a JSON object.")
        )

    action = payload.get("action")
    if action not in {helper_action.value for helper_action in HelperAction}:
        raise HelperValidationError(
            QCoreApplication.translate("PrivilegedHelper", "Unsupported action.")
        )

    action_type = HelperAction(action)
    if (
        authorization_scope is not None
        and action_type not in AUTH_SCOPE_ACTIONS[authorization_scope]
    ):
        raise HelperValidationError(
            QCoreApplication.translate("PrivilegedHelper", "Unsupported action.")
        )

    _validate_request_fields(payload, action)

    if action == HelperAction.INSTALL_SUPPORT_PACKAGES.value:
        package_names = _validated_support_packages(payload.get("package_names"))
        return ValidatedHelperRequest(
            action=HelperAction.INSTALL_SUPPORT_PACKAGES,
            package_names=package_names,
        )

    if action == HelperAction.REMOVE_SUPPORT_PACKAGES.value:
        package_names = _validated_support_packages(payload.get("package_names"))
        return ValidatedHelperRequest(
            action=HelperAction.REMOVE_SUPPORT_PACKAGES,
            package_names=package_names,
        )

    if action == HelperAction.RUN_SYSTEM_UPDATE.value:
        return ValidatedHelperRequest(
            action=HelperAction.RUN_SYSTEM_UPDATE,
            expected_versions=_validated_expected_versions(
                payload.get("expected_versions"),
                key_pattern=re.compile(r"[A-Za-z0-9@._+-]+"),
            ),
        )

    if action == HelperAction.RUN_FLATPAK_SYSTEM_UPDATE.value:
        refs = _validated_flatpak_refs(payload.get("refs"))
        expected_versions = _validated_expected_versions(
            payload.get("expected_versions"),
            key_pattern=re.compile(r"[A-Za-z0-9._/-]+"),
        )
        if set(refs) != set(expected_versions):
            raise HelperValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Flatpak references and expected versions do not match.",
                )
            )
        return ValidatedHelperRequest(
            action=HelperAction.RUN_FLATPAK_SYSTEM_UPDATE,
            refs=refs,
            expected_versions=expected_versions,
        )

    if action == HelperAction.RUN_FLATPAK_SYSTEM_CLEANUP.value:
        return ValidatedHelperRequest(action=HelperAction.RUN_FLATPAK_SYSTEM_CLEANUP)

    if action == HelperAction.RUN_FIRMWARE_UPDATE.value:
        return ValidatedHelperRequest(
            action=HelperAction.RUN_FIRMWARE_UPDATE,
            device_id=_validated_firmware_device_id(payload.get("device_id")),
            expected_version=_validated_version(payload.get("expected_version")),
        )

    if action == HelperAction.INITIALIZE_UPDATE_SESSION.value:
        return ValidatedHelperRequest(
            action=HelperAction.INITIALIZE_UPDATE_SESSION,
            aur_targets=_validated_aur_targets(payload.get("aur_targets")),
        )

    if action == HelperAction.INSTALL_REVIEWED_AUR.value:
        return ValidatedHelperRequest(
            action=HelperAction.INSTALL_REVIEWED_AUR,
            aur_review=_validated_aur_build_review(payload.get("aur_review")),
            expected_version=_validated_aur_version(payload.get("expected_version")),
        )

    if action == HelperAction.INSTALL_REVIEWED_AUR_GROUP.value:
        targets = _validated_aur_targets(payload.get("aur_targets"))
        review = _validated_aur_build_review(payload.get("aur_review"))
        if (
            len(targets) < 2
            or len({target.package_base for target in targets}) != 1
            or review.package_base != targets[0].package_base
            or review.package_name not in {target.package_name for target in targets}
        ):
            raise HelperValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid reviewed AUR package group.",
                )
            )
        return ValidatedHelperRequest(
            action=HelperAction.INSTALL_REVIEWED_AUR_GROUP,
            aur_targets=targets,
            aur_review=review,
        )

    raise HelperValidationError(
        QCoreApplication.translate("PrivilegedHelper", "Unsupported action.")
    )


def _validate_request_fields(payload: dict[object, object], action: object) -> None:
    allowed_fields = {"action", "language_code"}
    if action in {
        HelperAction.INSTALL_SUPPORT_PACKAGES.value,
        HelperAction.REMOVE_SUPPORT_PACKAGES.value,
    }:
        allowed_fields.add("package_names")
    if action == HelperAction.RUN_SYSTEM_UPDATE.value:
        allowed_fields.add("expected_versions")
    if action == HelperAction.RUN_FLATPAK_SYSTEM_UPDATE.value:
        allowed_fields.update({"refs", "expected_versions"})
    if action == HelperAction.RUN_FIRMWARE_UPDATE.value:
        allowed_fields.update({"device_id", "expected_version"})
    if action == HelperAction.INITIALIZE_UPDATE_SESSION.value:
        allowed_fields.add("aur_targets")
    if action == HelperAction.INSTALL_REVIEWED_AUR.value:
        allowed_fields.update({"aur_review", "expected_version"})
    if action == HelperAction.INSTALL_REVIEWED_AUR_GROUP.value:
        allowed_fields.update({"aur_review", "aur_targets"})

    unexpected_fields = sorted(str(key) for key in payload if str(key) not in allowed_fields)
    if unexpected_fields:
        raise HelperValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Unsupported request field: {field}",
            ).format(field=unexpected_fields[0])
        )


def _validated_support_packages(raw_packages: object) -> list[str]:
    try:
        return validate_package_list(raw_packages, "package_names")
    except SupportPackageValidationError as exc:
        raise HelperValidationError(str(exc)) from exc


def _validated_flatpak_refs(raw_refs: object) -> list[str]:
    try:
        return validate_flatpak_refs(raw_refs)
    except PrivilegedUpdateValidationError as exc:
        raise HelperValidationError(str(exc)) from exc


def _validated_firmware_device_id(raw_device_id: object) -> str:
    try:
        return validate_firmware_device_id(raw_device_id)
    except PrivilegedUpdateValidationError as exc:
        raise HelperValidationError(str(exc)) from exc


def _validated_aur_targets(raw_targets: object) -> list[AurInstallTarget]:
    if not isinstance(raw_targets, list):
        raise HelperValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "`aur_targets` must be an array.",
            )
        )
    targets: list[AurInstallTarget] = []
    seen_names: set[str] = set()
    for raw_target in raw_targets:
        if not isinstance(raw_target, dict) or set(raw_target) != {
            "package_name",
            "package_base",
            "version",
            "current_version",
            "dynamic_version",
        }:
            raise HelperValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid AUR install target.",
                )
            )
        package_name = raw_target["package_name"]
        package_base = raw_target["package_base"]
        version = raw_target["version"]
        current_version = raw_target["current_version"]
        dynamic_version = raw_target["dynamic_version"]
        if (
            not isinstance(package_name, str)
            or not isinstance(package_base, str)
            or not isinstance(version, str)
            or not isinstance(current_version, str)
            or not isinstance(dynamic_version, bool)
            or not package_name
            or len(package_name) > 255
            or not re.fullmatch(r"[A-Za-z0-9@._+-]+", package_name)
            or package_name in seen_names
            or not package_base
            or len(package_base) > 255
            or not re.fullmatch(r"[A-Za-z0-9@._+-]+", package_base)
            or not version
            or len(version) > 512
            or any(character in version for character in ("\x00", "\n", "\r", "\t"))
            or len(current_version) > 512
            or any(
                character in current_version for character in ("\x00", "\n", "\r", "\t")
            )
            or (dynamic_version and version != "latest-commit")
            or (dynamic_version and not current_version)
        ):
            raise HelperValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid AUR install target.",
                )
            )
        seen_names.add(package_name)
        targets.append(
            AurInstallTarget(
                package_name=package_name,
                package_base=package_base,
                version=version,
                current_version=current_version,
                dynamic_version=dynamic_version,
            )
        )
    return targets


def _validated_aur_build_review(raw_review: object) -> AurPkgbuildReview:
    try:
        return validate_aur_build_review(raw_review)
    except PrivilegedUpdateValidationError as exc:
        raise HelperValidationError(str(exc)) from exc


def _validated_aur_version(raw_version: object) -> str:
    return _validated_version(raw_version)


def _validated_version(raw_version: object) -> str:
    if (
        not isinstance(raw_version, str)
        or not raw_version
        or len(raw_version) > 512
        or raw_version.startswith("-")
        or any(character in raw_version for character in ("\x00", "\n", "\r", "\t"))
    ):
        raise HelperValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Invalid expected version.",
            )
        )
    return raw_version


def _validated_expected_versions(
    raw_versions: object,
    *,
    key_pattern: re.Pattern[str],
) -> dict[str, str]:
    if not isinstance(raw_versions, dict) or not raw_versions:
        raise HelperValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Expected versions must be a non-empty object.",
            )
        )
    versions: dict[str, str] = {}
    for raw_name, raw_version in raw_versions.items():
        if (
            not isinstance(raw_name, str)
            or not raw_name
            or len(raw_name) > 512
            or raw_name.startswith("-")
            or not key_pattern.fullmatch(raw_name)
            or ".." in Path(raw_name).parts
        ):
            raise HelperValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Invalid expected-version target.",
                )
            )
        versions[raw_name] = _validated_version(raw_version)
    return versions


def _validated_request_from_payload(
    payload: object,
    translation_manager: TranslationManager,
    *,
    authorization_scope: HelperAuthorizationScope,
) -> ValidatedHelperRequest:
    translation_manager.install(_requested_language_code(payload))
    return validate_request(payload, authorization_scope=authorization_scope)


def _execute_request(
    request: ValidatedHelperRequest,
    *,
    allowed_aur_targets: dict[str, AurInstallTarget] | None = None,
    aur_build_root: Path | None = None,
) -> int:
    if request.action is HelperAction.INITIALIZE_UPDATE_SESSION:
        emit_event(
            HelperEventType.COMPLETED,
            success=True,
            message=QCoreApplication.translate(
                "PrivilegedHelper",
                "Privileged update session initialized.",
            ),
        )
        return 0

    if request.action is HelperAction.INSTALL_REVIEWED_AUR:
        if request.aur_review is None or aur_build_root is None:
            return 8
        target = (allowed_aur_targets or {}).get(request.aur_review.package_name)
        if target is None:
            return 8
        try:
            build_user = resolve_aur_build_user()
            return install_reviewed_aur(
                request.aur_review,
                request.expected_version,
                expected_package_base=target.package_base,
                current_version=target.current_version,
                dynamic_version=target.dynamic_version,
                build_user=build_user,
                build_root=aur_build_root,
                emit_event=emit_event,
                emit_log=emit_log,
            )
        except (OSError, PrivilegedUpdateValidationError) as exc:
            message = str(exc) or QCoreApplication.translate(
                "PrivilegedHelper",
                "Could not build or install the reviewed AUR package.",
            )
            emit_event(HelperEventType.COMPLETED, success=False, message=message)
            return 4

    if request.action is HelperAction.INSTALL_REVIEWED_AUR_GROUP:
        if request.aur_review is None or aur_build_root is None or not request.aur_targets:
            return 8
        try:
            build_user = resolve_aur_build_user()
            return install_reviewed_aur_group(
                request.aur_review,
                request.aur_targets,
                expected_package_base=request.aur_targets[0].package_base,
                build_user=build_user,
                build_root=aur_build_root,
                emit_event=emit_event,
                emit_log=emit_log,
            )
        except (OSError, PrivilegedUpdateValidationError) as exc:
            message = str(exc) or QCoreApplication.translate(
                "PrivilegedHelper",
                "Could not build or install the reviewed AUR package group.",
            )
            emit_event(HelperEventType.COMPLETED, success=False, message=message)
            return 4

    if request.action is HelperAction.INSTALL_SUPPORT_PACKAGES:
        return install_support_packages(
            request.package_names,
            emit_event=emit_event,
            emit_log=emit_log,
        )

    if request.action is HelperAction.REMOVE_SUPPORT_PACKAGES:
        return remove_support_packages(
            request.package_names,
            emit_event=emit_event,
            emit_log=emit_log,
        )

    if request.action is HelperAction.RUN_SYSTEM_UPDATE:
        return run_system_update(
            request.expected_versions,
            emit_event=emit_event,
            emit_log=emit_log,
        )

    if request.action is HelperAction.RUN_FLATPAK_SYSTEM_UPDATE:
        return run_flatpak_system_update(
            request.refs,
            request.expected_versions,
            emit_event=emit_event,
            emit_log=emit_log,
        )

    if request.action is HelperAction.RUN_FLATPAK_SYSTEM_CLEANUP:
        return run_flatpak_system_cleanup(
            emit_event=emit_event,
            emit_log=emit_log,
        )

    if request.action is HelperAction.RUN_FIRMWARE_UPDATE:
        return run_firmware_update(
            request.device_id,
            request.expected_version,
            emit_event=emit_event,
            emit_log=emit_log,
        )

    emit_event(
        HelperEventType.COMPLETED,
        success=False,
        message=QCoreApplication.translate(
            "PrivilegedHelper",
            "No handler available for requested action.",
        ),
    )
    return 8


def _authorization_scope(argv: list[str]) -> HelperAuthorizationScope:
    if len(argv) != 2:
        raise HelperValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Invalid privileged helper authorization scope.",
            )
        )

    marker = argv[1]
    for scope in HelperAuthorizationScope:
        if marker == f"--archupdater-auth={scope.value}":
            return scope

    raise HelperValidationError(
        QCoreApplication.translate(
            "PrivilegedHelper",
            "Invalid privileged helper authorization scope.",
        )
    )


def _run_session(translation_manager: TranslationManager) -> int:
    emit_event(HelperEventType.STATUS, value="ready")
    initialized = False
    allowed_aur_targets: dict[str, AurInstallTarget] = {}
    attempted_aur_targets: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="archupdater-aur-build-") as raw_build_root:
        aur_build_root = Path(raw_build_root)
        aur_build_root.chmod(0o755)
        return _run_initialized_session(
            translation_manager,
            initialized=initialized,
            allowed_aur_targets=allowed_aur_targets,
            attempted_aur_targets=attempted_aur_targets,
            aur_build_root=aur_build_root,
        )


def _run_initialized_session(
    translation_manager: TranslationManager,
    *,
    initialized: bool,
    allowed_aur_targets: dict[str, AurInstallTarget],
    attempted_aur_targets: set[str],
    aur_build_root: Path,
) -> int:
    while True:
        raw_line = sys.stdin.readline(MAX_HELPER_REQUEST_CHARACTERS + 1)
        if not raw_line:
            break
        if len(raw_line) > MAX_HELPER_REQUEST_CHARACTERS:
            while raw_line and not raw_line.endswith("\n"):
                raw_line = sys.stdin.readline(MAX_HELPER_REQUEST_CHARACTERS + 1)
            emit_event(
                HelperEventType.COMPLETED,
                success=False,
                message=QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Privileged helper request exceeds the safety limit.",
                ),
            )
            continue
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            request = _validated_request_from_payload(
                payload,
                translation_manager,
                authorization_scope=HelperAuthorizationScope.UPDATE_SESSION,
            )
        except json.JSONDecodeError:
            emit_event(
                HelperEventType.COMPLETED,
                success=False,
                message=QCoreApplication.translate("PrivilegedHelper", "Invalid JSON request."),
            )
            continue
        except HelperValidationError as exc:
            emit_event(HelperEventType.COMPLETED, success=False, message=str(exc))
            continue
        except Exception as exc:  # pragma: no cover - last resort
            emit_event(
                HelperEventType.COMPLETED,
                success=False,
                message=QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Unexpected helper error: {error}",
                ).format(error=exc),
            )
            continue
        if not initialized:
            if request.action is not HelperAction.INITIALIZE_UPDATE_SESSION:
                emit_event(
                    HelperEventType.COMPLETED,
                    success=False,
                    message=QCoreApplication.translate(
                        "PrivilegedHelper",
                        "The privileged update session was not initialized.",
                    ),
                )
                continue
            allowed_aur_targets = {
                target.package_name: target for target in request.aur_targets
            }
            initialized = True
            _execute_request(
                request,
                allowed_aur_targets=allowed_aur_targets,
                aur_build_root=aur_build_root,
            )
            continue

        if request.action is HelperAction.INITIALIZE_UPDATE_SESSION:
            emit_event(
                HelperEventType.COMPLETED,
                success=False,
                message=QCoreApplication.translate(
                    "PrivilegedHelper",
                    "The privileged update session is already initialized.",
                ),
            )
            continue
        if request.action is HelperAction.INSTALL_REVIEWED_AUR:
            assert request.aur_review is not None
            package_name = request.aur_review.package_name
            target = allowed_aur_targets.get(package_name)
            if (
                target is None
                or target.version != request.expected_version
                or target.package_base != request.aur_review.package_base
                or package_name in attempted_aur_targets
            ):
                emit_event(
                    HelperEventType.COMPLETED,
                    success=False,
                    message=QCoreApplication.translate(
                        "PrivilegedHelper",
                        "The reviewed AUR package is not part of the authorized update plan.",
                    ),
                )
                continue
            attempted_aur_targets.add(package_name)
            return_code = _execute_request(
                request,
                allowed_aur_targets=allowed_aur_targets,
                aur_build_root=aur_build_root,
            )
            if return_code == 0:
                allowed_aur_targets.pop(package_name, None)
            continue
        if request.action is HelperAction.INSTALL_REVIEWED_AUR_GROUP:
            assert request.aur_review is not None
            package_names = {target.package_name for target in request.aur_targets}
            authorized = all(
                allowed_aur_targets.get(target.package_name) == target
                for target in request.aur_targets
            )
            if (
                not authorized
                or package_names & attempted_aur_targets
                or request.aur_review.package_name not in package_names
            ):
                emit_event(
                    HelperEventType.COMPLETED,
                    success=False,
                    message=QCoreApplication.translate(
                        "PrivilegedHelper",
                        "The reviewed AUR package group is not part of the authorized update plan.",
                    ),
                )
                continue
            attempted_aur_targets.update(package_names)
            return_code = _execute_request(
                request,
                allowed_aur_targets=allowed_aur_targets,
                aur_build_root=aur_build_root,
            )
            if return_code == 0:
                for package_name in package_names:
                    allowed_aur_targets.pop(package_name, None)
            continue
        _execute_request(
            request,
            allowed_aur_targets=allowed_aur_targets,
            aur_build_root=aur_build_root,
        )
    return 0


def main() -> int:
    app = QCoreApplication.instance() or QCoreApplication([sys.argv[0]])
    translation_manager = TranslationManager(app)
    translation_manager.install(None)

    try:
        if os.geteuid() != 0:
            emit_event(
                HelperEventType.COMPLETED,
                success=False,
                message=QCoreApplication.translate(
                    "PrivilegedHelper",
                    "The privileged helper must run as root.",
                ),
            )
            return 4

        signal.signal(signal.SIGTERM, _raise_termination)
        signal.signal(signal.SIGINT, _raise_termination)
        set_parent_death_signal(signal.SIGTERM)
        if os.getppid() == 1:
            emit_event(
                HelperEventType.COMPLETED,
                success=False,
                message=QCoreApplication.translate(
                    "PrivilegedHelper",
                    "The privileged helper lost its requesting process.",
                ),
            )
            return 4

        authorization_scope = _authorization_scope(sys.argv)
        if authorization_scope is HelperAuthorizationScope.UPDATE_SESSION:
            return _run_session(translation_manager)

        raw_payload = sys.stdin.read(MAX_HELPER_REQUEST_CHARACTERS + 1)
        if len(raw_payload) > MAX_HELPER_REQUEST_CHARACTERS:
            raise HelperValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "Privileged helper request exceeds the safety limit.",
                )
            )
        payload = json.loads(raw_payload)
        request = _validated_request_from_payload(
            payload,
            translation_manager,
            authorization_scope=authorization_scope,
        )
    except json.JSONDecodeError:
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=QCoreApplication.translate("PrivilegedHelper", "Invalid JSON request."),
        )
        return 5
    except HelperValidationError as exc:
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=str(exc),
        )
        return 6
    except Exception as exc:  # pragma: no cover - last resort
        emit_event(
            HelperEventType.COMPLETED,
            success=False,
            message=QCoreApplication.translate(
                "PrivilegedHelper",
                "Unexpected helper error: {error}",
            ).format(error=exc),
        )
        return 7

    return _execute_request(request)


if __name__ == "__main__":
    raise SystemExit(main())
