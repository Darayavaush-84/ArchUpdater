from __future__ import annotations

import json
import re
import tempfile

from archupdater.domain.enums import UpdateSource
from archupdater.domain.aur import AurInstallTarget, AurPkgbuildReview
from archupdater.domain.update_plan import UpdatePlan, UpdatePlanItem
from archupdater.application.helper_protocol import HelperAction, HelperRequest
from archupdater.application.update_session.protocol import BatchOutcome
from archupdater.application.update_session.errors import BatchCancelled
from archupdater.application.update_session.backend import (
    BackendRunContext,
    BackendRunResult,
    CommandRunResult,
)


class PacmanBackend:
    step_key = "system"
    exit_code = 2
    outcome = BatchOutcome.SYSTEM_TRANSACTION_FAILED.value

    def should_run(self, plan: UpdatePlan) -> bool:
        return bool(plan.target_ids(UpdateSource.SYSTEM))

    def label(self, context: BackendRunContext) -> str:
        return context.translate("Pacman")

    def start_message(self, context: BackendRunContext) -> str:
        return context.translate("Now running a full system upgrade with pacman.")

    def run(self, context: BackendRunContext) -> BackendRunResult:
        system_items = context.plan.update_items(UpdateSource.SYSTEM)
        system_targets = [item.target_id for item in system_items]
        if system_targets:
            reviewed = context.plan_inspector.summarize_items(system_targets)
            message = context.translate(
                "Detected system updates: {packages}. Pacman will perform a full system upgrade."
            )
            context.print_line(message.format(packages=reviewed))

        expected_versions = _expected_versions(system_items)
        with tempfile.TemporaryDirectory(prefix="archupdater-checkupdates-") as database_path:
            preview_result = context.run_command(
                ["checkupdates", "--nocolor"],
                failure_message=context.translate(
                    "Could not safely refresh the pacman transaction preview."
                ),
                extra_env={"CHECKUPDATES_DB": database_path},
                success_codes=frozenset({0, 2}),
            )
        if not preview_result.success:
            return BackendRunResult(False, preview_result.message)

        actual_versions = _parse_checkupdates_versions(
            str((preview_result.payload or {}).get("output") or "")
        )
        if actual_versions != expected_versions:
            if not actual_versions:
                return BackendRunResult(
                    True,
                    context.translate("No reviewed system updates remain available."),
                    changed=False,
                )
            if not _confirm_plan_change(
                context,
                title=context.translate("System Update Changed"),
                actual_versions=actual_versions,
            ):
                return BackendRunResult(
                    False,
                    context.translate("The changed system transaction was not approved."),
                )
            expected_versions = actual_versions

        command_result = context.run_privileged(
            HelperRequest(
                action=HelperAction.RUN_SYSTEM_UPDATE,
                expected_versions=expected_versions,
            ),
            failure_message=context.translate("System update failed."),
        )
        return BackendRunResult(
            command_result.success,
            command_result.message,
            changed=_privileged_transaction_changed(command_result),
        )


class AurBackend:
    step_key = "aur"
    exit_code = 3
    outcome = BatchOutcome.FAILED.value

    def should_run(self, plan: UpdatePlan) -> bool:
        return bool(plan.target_ids(UpdateSource.AUR))

    def label(self, context: BackendRunContext) -> str:
        return context.translate("AUR")

    def start_message(self, context: BackendRunContext) -> str:
        return context.translate("Now installing the selected AUR updates with {helper}.").format(
            helper="makepkg"
        )

    def run(self, context: BackendRunContext) -> BackendRunResult:
        if not context.command_available("makepkg"):
            return BackendRunResult(
                False,
                context.translate("makepkg is not available."),
            )
        aur_items = context.plan.update_items(UpdateSource.AUR)
        if aur_items:
            reviewed = context.plan_inspector.summarize_items(
                [item.target_id for item in aur_items]
            )
            context.print_line(
                context.translate("Packages: {packages}").format(packages=reviewed)
            )

        installed: list[str] = []
        skipped: list[str] = []
        for group in self._group_by_package_base(aur_items):
            item = group[0]
            package_name = self._package_name(item)
            targets = [
                AurInstallTarget(
                    package_name=self._package_name(candidate),
                    package_base=candidate.package_base or "",
                    version=(candidate.expected_version or "").strip(),
                    current_version=(candidate.current_version or "").strip(),
                    dynamic_version=candidate.dynamic_version,
                )
                for candidate in group
            ]
            if any(not target.version for target in targets):
                return BackendRunResult(
                    False,
                    context.translate(
                        "The AUR update plan has no expected version for {package}."
                    ).format(package=package_name),
                    changed=bool(installed),
                    incomplete=bool(installed),
                )
            try:
                if any(target.dynamic_version for target in targets):
                    review = context.service.aur_pkgbuild_review(
                        package_name,
                        item.package_base,
                        lock_vcs_sources=True,
                    )
                else:
                    review = context.service.aur_pkgbuild_review(
                        package_name,
                        item.package_base,
                    )
            except Exception as exc:
                return self._failure(context, package_name, exc, changed=bool(installed))

            try:
                try:
                    review_confirmed = self._confirm_pkgbuild_review(context, review)
                except BatchCancelled as exc:
                    raise BatchCancelled(
                        str(exc),
                        changed=bool(installed) or exc.changed,
                    ) from exc
                if not review_confirmed:
                    skipped.extend(target.package_name for target in targets)
                    for candidate in group:
                        self._emit_skipped(
                            context,
                            candidate,
                            reason=context.translate("PKGBUILD review was cancelled."),
                        )
                    context.print_line(
                        context.translate(
                            "Skipped {package}: PKGBUILD review was cancelled."
                        ).format(package=package_name)
                    )
                    continue

                try:
                    missing_dependencies = (
                        context.service.aur_missing_build_dependencies(review)
                    )
                except Exception as exc:
                    return self._failure(context, package_name, exc, changed=bool(installed))
                if missing_dependencies:
                    missing = context.summarize_items(missing_dependencies)
                    return BackendRunResult(
                        False,
                        context.translate(
                            "Missing build dependencies for {package}: {dependencies}. "
                            "Install them explicitly before retrying."
                        ).format(package=package_name, dependencies=missing),
                        changed=bool(installed),
                        incomplete=bool(installed),
                    )

                install_result = context.run_privileged(
                    HelperRequest(
                        action=(
                            HelperAction.INSTALL_REVIEWED_AUR_GROUP
                            if len(targets) > 1
                            else HelperAction.INSTALL_REVIEWED_AUR
                        ),
                        aur_review=review,
                        expected_version=targets[0].version if len(targets) == 1 else None,
                        aur_targets=targets if len(targets) > 1 else None,
                    ),
                    failure_message=context.translate(
                        "Could not build and install the reviewed AUR package."
                    ),
                )
                if not install_result.success:
                    return BackendRunResult(
                        False,
                        install_result.message,
                        changed=bool(installed),
                        incomplete=bool(installed),
                    )
                if any(target.dynamic_version for target in targets):
                    actual_versions = (install_result.payload or {}).get("actual_versions")
                    if not isinstance(actual_versions, dict):
                        return BackendRunResult(
                            False,
                            context.translate(
                                "The AUR helper did not report the installed development version."
                            ),
                            changed=bool(installed),
                            incomplete=bool(installed),
                        )
                    for target in targets:
                        if not target.dynamic_version:
                            continue
                        actual_version = actual_versions.get(target.package_name)
                        if not isinstance(actual_version, str) or not actual_version:
                            return BackendRunResult(
                                False,
                                context.translate(
                                    "The AUR helper reported an invalid development version."
                                ),
                                changed=bool(installed),
                                incomplete=bool(installed),
                            )
                        try:
                            context.service.record_aur_vcs_install(
                                target.package_name,
                                actual_version,
                                review.vcs_sources,
                            )
                        except Exception as exc:
                            context.emit_log(
                                context.translate(
                                    "Could not record AUR development state for {package}: {error}"
                                ).format(
                                    package=target.package_name,
                                    error=str(exc).strip() or context.translate("unknown error"),
                                )
                            )
                installed.extend(target.package_name for target in targets)
            finally:
                context.service.discard_aur_pkgbuild_review(review)

        if skipped:
            context.print_line(
                context.translate("Skipped AUR updates: {packages}.").format(
                    packages=context.summarize_items(skipped)
                )
            )
        if not installed and skipped:
            return BackendRunResult(
                True,
                context.translate("AUR updates were skipped after PKGBUILD review."),
                changed=False,
                incomplete=True,
            )
        if skipped:
            return BackendRunResult(
                True,
                context.translate("AUR update completed with skipped packages."),
                changed=True,
                incomplete=True,
            )
        return BackendRunResult(
            True,
            context.translate("AUR update completed successfully."),
            changed=bool(installed),
        )

    def _confirm_pkgbuild_review(
        self,
        context: BackendRunContext,
        review: AurPkgbuildReview,
    ) -> bool:
        response = context.request_question(
            {
                "question_type": "aur_pkgbuild_review",
                "title": context.translate("Review AUR PKGBUILD"),
                "package_name": review.package_name,
                "package_base": review.package_base,
                "pkgbuild": review.pkgbuild,
                "commit": review.commit,
                "digest": review.digest,
                "vcs_sources": [
                    {
                        "name": source.name,
                        "url": source.url,
                        "branch": source.branch,
                        "commit": source.commit,
                    }
                    for source in review.vcs_sources
                ],
                "files": [
                    {
                        "path": reviewed_file.path,
                        "sha256": reviewed_file.sha256,
                        "size": reviewed_file.size,
                        "content": reviewed_file.content,
                    }
                    for reviewed_file in review.files
                ],
            }
        )
        return response is True

    def _failure(
        self,
        context: BackendRunContext,
        package_name: str,
        error: Exception,
        *,
        changed: bool,
    ) -> BackendRunResult:
        details = str(error).strip() or context.translate("unknown error")
        message = context.translate(
            "AUR preparation failed for {package}: {error}"
        ).format(package=package_name, error=details)
        context.print_line(message)
        return BackendRunResult(False, message, changed=changed, incomplete=changed)

    def _emit_skipped(
        self,
        context: BackendRunContext,
        item: UpdatePlanItem,
        *,
        reason: str,
    ) -> None:
        context.emit_progress(
            {
                "kind": "aur_pkgbuild_review_skipped",
                "target_id": item.target_id,
                "package_name": self._package_name(item),
                "reason": reason,
            }
        )

    def _package_name(self, item: UpdatePlanItem) -> str:
        return item.package_name or item.target_id

    def _group_by_package_base(
        self,
        items: list[UpdatePlanItem],
    ) -> list[list[UpdatePlanItem]]:
        groups: dict[str, list[UpdatePlanItem]] = {}
        for item in items:
            groups.setdefault(item.package_base or self._package_name(item), []).append(item)
        return list(groups.values())


class FlatpakBackend:
    step_key = "flatpak"
    exit_code = 4
    outcome = BatchOutcome.FAILED.value

    def should_run(self, plan: UpdatePlan) -> bool:
        return bool(
            plan.update_items(UpdateSource.FLATPAK)
            or plan.cleanup_items(UpdateSource.FLATPAK)
        )

    def label(self, context: BackendRunContext) -> str:
        return context.translate("Flatpak")

    def start_message(self, context: BackendRunContext) -> str:
        return context.translate("Now installing the selected Flatpak updates.")

    def run(self, context: BackendRunContext) -> BackendRunResult:
        changed = False
        incomplete = False
        flatpak_items = context.plan.update_items(UpdateSource.FLATPAK)
        for scope in ("system", "user"):
            items = [
                item
                for item in flatpak_items
                if (item.installation_scope or "system") == scope
            ]
            refs = [item.target_id for item in items]
            if not refs:
                continue
            context.print_line(
                context.translate("{scope} refs: {refs}").format(
                    scope=scope.capitalize(),
                    refs=context.summarize_items(refs),
                )
            )
            expected_versions = _expected_versions(items)
            preview_result = context.run_command(
                [
                    "flatpak",
                    "remote-ls",
                    f"--{scope}",
                    "--updates",
                    "--json",
                    "--columns=ref,version,branch",
                ],
                failure_message=context.translate("Could not prepare the Flatpak transaction."),
            )
            if not preview_result.success:
                return BackendRunResult(
                    False,
                    preview_result.message,
                    changed=changed,
                    incomplete=changed,
                )
            available_versions = _parse_flatpak_version_output(
                str((preview_result.payload or {}).get("output") or "")
            )
            if available_versions is None:
                return BackendRunResult(
                    False,
                    context.translate(
                        "Flatpak returned an invalid transaction preview."
                    ),
                    changed=changed,
                    incomplete=changed,
                )
            actual_versions = {
                ref: available_versions[ref]
                for ref in refs
                if available_versions.get(ref)
            }
            approved_refs = refs
            if actual_versions != expected_versions:
                if not actual_versions:
                    approved_refs = []
                elif _confirm_plan_change(
                    context,
                    title=context.translate("Flatpak Update Changed"),
                    actual_versions=actual_versions,
                ):
                    approved_refs = list(actual_versions)
                else:
                    return BackendRunResult(
                        False,
                        context.translate("The changed Flatpak transaction was not approved."),
                        changed=changed,
                        incomplete=changed,
                    )
            if approved_refs:
                command_result = context.run_command(
                    [
                        "flatpak",
                        "update",
                        f"--{scope}",
                        "--assumeyes",
                        "--noninteractive",
                        "--",
                        *approved_refs,
                    ],
                    failure_message=context.translate("Flatpak update failed."),
                )
                verify_result = context.run_command(
                    [
                        "flatpak",
                        "remote-ls",
                        f"--{scope}",
                        "--updates",
                        "--json",
                        "--columns=ref,version,branch",
                    ],
                    failure_message=context.translate(
                        "Could not verify the Flatpak transaction."
                    ),
                )
                if not verify_result.success:
                    return BackendRunResult(
                        False,
                        command_result.message
                        if not command_result.success
                        else verify_result.message,
                        changed=changed,
                        incomplete=changed,
                    )
                verified_versions = _parse_flatpak_version_output(
                    str((verify_result.payload or {}).get("output") or "")
                )
                if verified_versions is None:
                    return BackendRunResult(
                        False,
                        context.translate(
                            "Flatpak returned an invalid verification result."
                        ),
                        changed=changed,
                        incomplete=True,
                    )
                remaining_refs = set(approved_refs).intersection(verified_versions)
                completed_refs = set(approved_refs).difference(remaining_refs)
                if completed_refs:
                    changed = True
                if not command_result.success:
                    if remaining_refs:
                        return BackendRunResult(
                            False,
                            command_result.message,
                            changed=changed,
                            incomplete=changed,
                        )
                    incomplete = True
                    context.print_line(
                        context.translate(
                            "All selected Flatpak refs were deployed, but Flatpak reported a follow-up error."
                        )
                    )
                if remaining_refs:
                    return BackendRunResult(
                        False,
                        context.translate(
                            "Flatpak finished without installing all selected updates."
                        ),
                        changed=changed,
                        incomplete=True,
                    )

        for scope in context.plan.cleanup_scopes(UpdateSource.FLATPAK):
            if scope not in {"system", "user"}:
                continue
            command_result = context.run_command(
                [
                    "flatpak",
                    "uninstall",
                    f"--{scope}",
                    "--unused",
                    "--assumeyes",
                    "--noninteractive",
                ],
                failure_message=context.translate("Flatpak cleanup failed."),
            )
            if not command_result.success:
                return BackendRunResult(
                    False,
                    command_result.message,
                    changed=changed,
                    incomplete=changed or incomplete,
                )
            changed = True

        return BackendRunResult(
            True,
            (
                context.translate(
                    "Selected Flatpak updates were installed, but Flatpak reported a follow-up error."
                )
                if incomplete
                else context.translate("Flatpak update completed successfully.")
            ),
            changed=changed,
            incomplete=incomplete,
        )


class FirmwareBackend:
    step_key = "firmware"
    exit_code = 5
    outcome = BatchOutcome.FAILED.value

    def should_run(self, plan: UpdatePlan) -> bool:
        return bool(plan.target_ids(UpdateSource.FIRMWARE))

    def label(self, context: BackendRunContext) -> str:
        return context.translate("Firmware")

    def start_message(self, context: BackendRunContext) -> str:
        return context.translate("Now installing the selected firmware updates.")

    def run(self, context: BackendRunContext) -> BackendRunResult:
        firmware_items = context.plan.update_items(UpdateSource.FIRMWARE)
        firmware_targets = [item.target_id for item in firmware_items]
        context.print_line(
            context.translate("Devices: {count}").format(
                count=len(firmware_targets)
            )
        )
        updated_devices: list[str] = []
        failed_devices: list[tuple[str, str]] = []
        for item in firmware_items:
            device_id = item.target_id
            command_result = context.run_privileged(
                HelperRequest(
                    action=HelperAction.RUN_FIRMWARE_UPDATE,
                    device_id=device_id,
                    expected_version=item.expected_version,
                ),
                failure_message=context.translate("Firmware update failed."),
            )
            if not command_result.success:
                failed_devices.append((device_id, command_result.message))
                context.print_line(
                    context.translate("Firmware device failed: {device}").format(
                        device=device_id
                    )
                )
                continue
            updated_devices.append(device_id)

        if failed_devices:
            failed_names = ", ".join(device for device, _message in failed_devices[:4])
            if len(failed_devices) > 4:
                failed_names = context.translate("{visible} (+{remaining} more)").format(
                    visible=failed_names,
                    remaining=len(failed_devices) - 4,
                )
            if updated_devices:
                message = context.translate(
                    "Updated {updated} firmware device(s). Failed: {failed}."
                ).format(updated=len(updated_devices), failed=failed_names)
            else:
                message = failed_devices[0][1]
            return BackendRunResult(
                False,
                message,
                changed=bool(updated_devices),
                incomplete=bool(updated_devices),
            )

        return BackendRunResult(
            True,
            context.translate("Firmware update completed successfully."),
            changed=bool(updated_devices),
        )


class PlasmaWidgetBackend:
    step_key = "plasma_widget"
    exit_code = 6
    outcome = BatchOutcome.FAILED.value

    def should_run(self, plan: UpdatePlan) -> bool:
        return bool(plan.update_items(UpdateSource.PLASMA_WIDGET))

    def label(self, context: BackendRunContext) -> str:
        return context.translate("KDE Store Add-ons")

    def start_message(self, context: BackendRunContext) -> str:
        return context.translate(
            "Now installing the selected KDE Store add-on updates."
        )

    def run(self, context: BackendRunContext) -> BackendRunResult:
        plasma_widgets = context.plan.update_items(UpdateSource.PLASMA_WIDGET)
        widget_names = [target.package_name for target in plasma_widgets if target.package_name]
        if widget_names:
            context.print_line(
                context.translate("Add-ons: {addons}").format(
                    addons=context.summarize_items(widget_names)
                )
            )

        def log_callback(message: str) -> None:
            if not message:
                return
            context.print_line(message)
            context.emit_log(message)

        result = context.service.plasma_widgets_update_service.update_widgets(
            plasma_widgets,
            log_callback=log_callback,
        )
        return BackendRunResult(
            result.success,
            result.message,
            changed=result.changed,
            incomplete=result.incomplete,
        )


def _expected_versions(items: list[UpdatePlanItem]) -> dict[str, str]:
    return {item.target_id: (item.expected_version or "").strip() for item in items}


def _parse_flatpak_version_output(output: str) -> dict[str, str] | None:
    stripped = output.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, list):
        versions: dict[str, str] = {}
        for entry in payload:
            if not isinstance(entry, dict):
                return None
            ref = entry.get("ref")
            version = entry.get("version")
            branch = entry.get("branch", "")
            if not isinstance(ref, str) or not ref:
                return None
            if not isinstance(version, str) or not isinstance(branch, str):
                return None
            versions[ref] = version.strip() or branch.strip()
        return versions

    versions: dict[str, str] = {}
    for raw_line in output.splitlines():
        columns = raw_line.split("\t")
        if len(columns) < 2:
            continue
        ref = columns[0].strip()
        version = columns[1].strip()
        branch = columns[2].strip() if len(columns) >= 3 else ""
        if ref:
            versions[ref] = version or branch
    return versions or None


_CHECKUPDATES_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9@._+-]+)\s+\S+\s+->\s+(?P<version>\S+)$"
)


def _parse_checkupdates_versions(output: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for raw_line in output.splitlines():
        match = _CHECKUPDATES_LINE_RE.fullmatch(raw_line.strip())
        if match:
            versions[match.group("name")] = match.group("version")
    return versions


def _payload_versions(result: CommandRunResult) -> dict[str, str] | None:
    payload = result.payload
    if not isinstance(payload, dict) or payload.get("reason") != "plan_changed":
        return None
    raw_versions = payload.get("actual_versions")
    if not isinstance(raw_versions, dict):
        return None
    versions: dict[str, str] = {}
    for raw_name, raw_version in raw_versions.items():
        if not isinstance(raw_name, str) or not isinstance(raw_version, str):
            return None
        name = raw_name.strip()
        version = raw_version.strip()
        if not name or not version or len(name) > 512 or len(version) > 512:
            return None
        versions[name] = version
    return versions


def _confirm_plan_change(
    context: BackendRunContext,
    *,
    title: str,
    actual_versions: dict[str, str],
) -> bool:
    response = context.request_question(
        {
            "question_type": "transaction_change",
            "title": title,
            "message": context.translate(
                "The available transaction changed after the original review. Review the new versions before continuing."
            ),
            "versions": actual_versions,
        }
    )
    return response is True


def _retry_changed_privileged_plan(
    context: BackendRunContext,
    result: CommandRunResult,
    *,
    action: HelperAction,
    title: str,
    failure_message: str,
    refs: list[str] | None = None,
) -> CommandRunResult:
    actual_versions = _payload_versions(result)
    if actual_versions is None:
        return result
    if not actual_versions:
        return CommandRunResult(
            True,
            context.translate("No reviewed updates remain available."),
            payload={"changed": False},
        )
    if not _confirm_plan_change(
        context,
        title=title,
        actual_versions=actual_versions,
    ):
        return result
    return context.run_privileged(
        HelperRequest(
            action=action,
            refs=list(actual_versions) if refs is not None else None,
            expected_versions=actual_versions,
        ),
        failure_message=failure_message,
    )


def _privileged_transaction_changed(result: CommandRunResult) -> bool:
    payload = result.payload or {}
    if result.success:
        return payload.get("changed") is not False
    return payload.get("reason") not in {"plan_changed", "preparation_failed"}
