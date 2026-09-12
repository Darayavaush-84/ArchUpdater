from __future__ import annotations

import os
import hashlib
import platform
import io
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.helper import privileged_helper
from archupdater.helper.actions import common, privileged_updates, support_packages
from archupdater.helper.privileged_helper import (
    HelperAuthorizationScope,
    HelperValidationError,
)
from archupdater.application.helper_protocol import HelperAction, HelperRequest
from archupdater.domain.aur import (
    AurInstallTarget,
    AurPkgbuildReview,
    AurReviewFile,
    AurVcsSource,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _review(
    package_name: str = "example",
    *,
    package_base: str | None = None,
    declared_names: tuple[str, ...] | None = None,
) -> AurPkgbuildReview:
    package_base = package_base or package_name
    declared_names = declared_names or (package_name,)
    contents = {
        ".SRCINFO": (
            f"pkgbase = {package_base}\n"
            + "".join(f"pkgname = {name}\n" for name in declared_names)
        ),
        "PKGBUILD": f"pkgname={package_name}\npkgver=1.0\npkgrel=1\n",
    }
    files: list[AurReviewFile] = []
    tree_digest = hashlib.sha256()
    for path, content in sorted(contents.items()):
        raw_content = content.encode("utf-8")
        digest = hashlib.sha256(raw_content).hexdigest()
        files.append(AurReviewFile(path, digest, len(raw_content), content))
        tree_digest.update(path.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(str(len(raw_content)).encode("ascii"))
        tree_digest.update(b"\0")
        tree_digest.update(digest.encode("ascii"))
        tree_digest.update(b"\0")
    return AurPkgbuildReview(
        package_name=package_name,
        package_base=package_base,
        pkgbuild=contents["PKGBUILD"],
        digest=tree_digest.hexdigest(),
        files=tuple(files),
    )


def _review_payload(review: AurPkgbuildReview) -> dict[str, object]:
    return {
        "package_name": review.package_name,
        "package_base": review.package_base,
        "digest": review.digest,
        "vcs_sources": [],
        "files": [
            {
                "path": item.path,
                "sha256": item.sha256,
                "size": item.size,
                "content": item.content,
            }
            for item in review.files
        ],
    }


class _ExistingPath:
    def __init__(self, value: str = "/usr/bin/pacman") -> None:
        self._value = value

    def exists(self) -> bool:
        return True

    def __str__(self) -> str:
        return self._value


class PrivilegedHelperTests(unittest.TestCase):
    def test_stream_command_emits_carriage_return_progress_while_running(self) -> None:
        logs: list[tuple[str, float]] = []
        started_at = time.monotonic()

        return_code, collected = common.stream_command(
            [
                sys.executable,
                "-c",
                (
                    "import sys, time; "
                    "sys.stdout.write('linux 10%\\r'); "
                    "sys.stdout.flush(); "
                    "time.sleep(0.5); "
                    "sys.stdout.write('linux 100%\\n'); "
                    "sys.stdout.flush()"
                ),
            ],
            emit_log=lambda line: logs.append((line, time.monotonic() - started_at)),
        )

        self.assertEqual(return_code, 0)
        self.assertEqual([line for line, _elapsed in logs], ["linux 10%", "linux 100%"])
        self.assertEqual(collected, ["linux 10%", "linux 100%"])
        self.assertLess(logs[0][1], 0.35)

    def test_stream_command_exposes_terminal_stdout(self) -> None:
        return_code, collected = common.stream_command(
            [
                sys.executable,
                "-c",
                "import sys; print(sys.stdout.isatty(), flush=True)",
            ],
            emit_log=lambda _line: None,
        )

        self.assertEqual(return_code, 0)
        self.assertEqual(collected, ["True"])

    def test_stream_subprocess_terminates_when_output_limit_is_exceeded(self) -> None:
        logs: list[str] = []

        with patch.object(common, "MAX_STREAM_LOG_BYTES", 8):
            return_code, collected = common.stream_subprocess(
                [sys.executable, "-c", "print('output beyond limit', flush=True)"],
                emit_log=logs.append,
                timeout_seconds=2,
            )

        self.assertEqual(return_code, 125)
        self.assertEqual(collected, ["output beyond limit"])
        self.assertIn("output safety limit", logs[-1])

    def test_validate_request_rejects_empty_package_list(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.INSTALL_SUPPORT_PACKAGES.value,
                    "package_names": [],
                }
            )

    def test_validate_request_rejects_unknown_fields(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.INSTALL_SUPPORT_PACKAGES.value,
                    "unexpected": True,
                    "package_names": ["flatpak"],
                }
            )

    def test_polkit_policy_has_only_support_and_update_session_scopes(self) -> None:
        policy_path = PROJECT_ROOT / "resources/polkit/io.github.archupdater.policy"
        root = ET.parse(policy_path).getroot()
        actions = root.findall("action")
        by_argv = {
            action.findtext("annotate[@key='org.freedesktop.policykit.exec.argv1']"): action
            for action in actions
        }

        expected_scopes = {
            "--archupdater-auth=update-session",
            "--archupdater-auth=support-packages",
        }
        self.assertEqual(len(actions), len(expected_scopes))
        self.assertEqual(set(by_argv), expected_scopes)
        self.assertNotIn(None, by_argv)

        update_session_message = by_argv[
            "--archupdater-auth=update-session"
        ].findtext("message")
        self.assertIn("update session", update_session_message or "")

        for marker, action in by_argv.items():
            self.assertEqual(
                action.findtext("annotate[@key='org.freedesktop.policykit.exec.path']"),
                "/usr/lib/archupdater/archupdater-helper",
            )
            defaults = action.find("defaults")
            self.assertIsNotNone(defaults)
            self.assertEqual(
                defaults.findtext("allow_active"),
                "auth_admin",
            )

    def test_support_scope_rejects_update_session_actions(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {"action": HelperAction.RUN_SYSTEM_UPDATE.value},
                authorization_scope=HelperAuthorizationScope.SUPPORT_PACKAGES,
            )

    def test_update_scope_rejects_support_package_actions(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.INSTALL_SUPPORT_PACKAGES.value,
                    "package_names": ["flatpak"],
                },
                authorization_scope=HelperAuthorizationScope.UPDATE_SESSION,
            )

    def test_authorization_scope_rejects_extra_or_duplicated_markers(self) -> None:
        for argv in (
            ["helper", "--archupdater-auth=support-packages", "extra"],
            [
                "helper",
                "--archupdater-auth=support-packages",
                "--archupdater-auth=update-session",
            ],
        ):
            with self.subTest(argv=argv), self.assertRaises(HelperValidationError):
                privileged_helper._authorization_scope(argv)

    def test_validate_request_rejects_option_like_package_names(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.INSTALL_SUPPORT_PACKAGES.value,
                    "package_names": ["-Syu"],
                }
            )

    def test_validate_request_rejects_unmanaged_package_names(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.INSTALL_SUPPORT_PACKAGES.value,
                    "package_names": ["linux"],
                }
            )

    def test_install_support_packages_uses_argument_separator(self) -> None:
        commands: list[list[str]] = []

        with (
            patch.object(support_packages, "PACMAN_PATH", _ExistingPath()),
            patch.object(common, "PACMAN_PATH", _ExistingPath()),
            patch.object(
                support_packages,
                "stream_command",
                lambda command, *, emit_log: commands.append(command) or (0, []),
            ),
        ):
            exit_code = support_packages.install_support_packages(
                ["flatpak"],
                emit_event=lambda *_args, **_kwargs: None,
                emit_log=lambda _message: None,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("--", commands[0])
        self.assertEqual(commands[0][1], "-Syu")
        self.assertEqual(commands[0][-2:], ["--", "flatpak"])

    def test_validate_request_rejects_aur_helper_bootstrap_without_confirmation(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.INSTALL_SUPPORT_PACKAGES.value,
                    "package_names": ["paru"],
                }
            )

    def test_validate_request_rejects_removed_aur_bootstrap_confirmation(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.INSTALL_SUPPORT_PACKAGES.value,
                    "package_names": ["flatpak"],
                    "aur_bootstrap_confirmed": True,
                }
            )

    def test_validate_request_accepts_system_update_manifest(self) -> None:
        request = privileged_helper.validate_request(
            {
                "action": HelperAction.RUN_SYSTEM_UPDATE.value,
                "expected_versions": {"linux": "6.9-1"},
            }
        )

        self.assertEqual(request.action, HelperAction.RUN_SYSTEM_UPDATE)
        self.assertEqual(request.expected_versions, {"linux": "6.9-1"})

    def test_validate_request_rejects_system_update_targets(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.RUN_SYSTEM_UPDATE.value,
                    "package_names": ["linux"],
                    "expected_versions": {"linux": "6.9-1"},
                }
            )

    def test_validate_request_accepts_strict_aur_session_targets(self) -> None:
        request = privileged_helper.validate_request(
            {
                "action": HelperAction.INITIALIZE_UPDATE_SESSION.value,
                "aur_targets": [
                    {
                        "package_name": "example-bin",
                        "package_base": "example",
                        "version": "1.0-1",
                        "current_version": "",
                        "dynamic_version": False,
                    }
                ],
            }
        )

        self.assertEqual(
            request.aur_targets,
            [AurInstallTarget("example-bin", "example", "1.0-1")],
        )

    def test_validate_request_accepts_dynamic_aur_target_and_vcs_lock(self) -> None:
        target = AurInstallTarget(
            "example-git",
            "example-git",
            "latest-commit",
            current_version="r1.aaaaaaa-1",
            dynamic_version=True,
        )
        request = privileged_helper.validate_request(
            {
                "action": HelperAction.INITIALIZE_UPDATE_SESSION.value,
                "aur_targets": [
                    {
                        "package_name": target.package_name,
                        "package_base": target.package_base,
                        "version": target.version,
                        "current_version": target.current_version,
                        "dynamic_version": target.dynamic_version,
                    }
                ],
            }
        )

        self.assertEqual(request.aur_targets, [target])

        review = _review("example-git")
        source = AurVcsSource(
            "example-git",
            "https://example.invalid/example.git",
            None,
            "b" * 40,
        )
        payload = _review_payload(review)
        payload["vcs_sources"] = [
            {
                "name": source.name,
                "url": source.url,
                "branch": source.branch,
                "commit": source.commit,
            }
        ]
        install_request = privileged_helper.validate_request(
            {
                "action": HelperAction.INSTALL_REVIEWED_AUR.value,
                "aur_review": payload,
                "expected_version": "latest-commit",
            }
        )
        self.assertEqual(install_request.aur_review.vcs_sources, (source,))

    def test_dynamic_aur_artifact_accepts_new_version_and_rejects_non_newer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "example-git.pkg.tar.zst").write_bytes(b"package")

            with patch.object(
                privileged_updates,
                "_package_file_identity",
                return_value=("example-git", "r2.bbbbbbb-1", platform.machine()),
            ):
                artifact, version = privileged_updates._verified_built_artifact(
                    output,
                    package_name="example-git",
                    expected_version="latest-commit",
                    current_version="r1.aaaaaaa-1",
                    dynamic_version=True,
                    private_directory=root / "verified",
                    emit_log=lambda _message: None,
                )

            self.assertEqual(version, "r2.bbbbbbb-1")
            self.assertTrue(artifact.is_file())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "example-git.pkg.tar.zst").write_bytes(b"package")
            with (
                patch.object(
                    privileged_updates,
                    "_package_file_identity",
                    return_value=("example-git", "r1.aaaaaaa-1", platform.machine()),
                ),
                self.assertRaisesRegex(
                    privileged_updates.PrivilegedUpdateValidationError,
                    "newer concrete version",
                ),
            ):
                privileged_updates._verified_built_artifact(
                    output,
                    package_name="example-git",
                    expected_version="latest-commit",
                    current_version="r1.aaaaaaa-1",
                    dynamic_version=True,
                    private_directory=root / "verified",
                    emit_log=lambda _message: None,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "example-git.pkg.tar.zst").write_bytes(b"package")
            with (
                patch.object(
                    privileged_updates,
                    "_package_file_identity",
                    return_value=("example-git", "r1.aaaaaaa-1", platform.machine()),
                ),
                self.assertRaisesRegex(
                    privileged_updates.PrivilegedUpdateValidationError,
                    "newer concrete version",
                ),
            ):
                privileged_updates._verified_built_artifact(
                    output,
                    package_name="example-git",
                    expected_version="latest-commit",
                    current_version="r2.bbbbbbb-1",
                    dynamic_version=True,
                    private_directory=root / "verified",
                    emit_log=lambda _message: None,
                )

    def test_dynamic_aur_version_revalidation_ignores_pty_cursor_sequences(self) -> None:
        target = AurInstallTarget(
            "nct6687d-dkms-git",
            "nct6687d-dkms-git",
            "latest-commit",
            current_version="r197.cd73522-1",
            dynamic_version=True,
        )
        with patch.object(
            privileged_updates,
            "stream_command",
            return_value=(
                0,
                [
                    "\x1b[?25lnct6687d-dkms-git r197.cd73522-1",
                    "\x1b[?25h",
                ],
            ),
        ):
            privileged_updates._validate_current_aur_versions(
                [target],
                emit_log=lambda _message: None,
            )

    def test_update_session_rejects_review_not_bound_to_planned_version(self) -> None:
        review = _review()
        requests = "".join(
            (
                HelperRequest(
                    action=HelperAction.INITIALIZE_UPDATE_SESSION,
                    aur_targets=[AurInstallTarget("example", "example", "1.0-1")],
                ).to_json_bytes().decode(),
                HelperRequest(
                    action=HelperAction.INSTALL_REVIEWED_AUR,
                    aur_review=review,
                    expected_version="2.0-1",
                ).to_json_bytes().decode(),
            )
        )
        events: list[tuple[object, dict[str, object]]] = []
        executed: list[HelperAction] = []
        translation_manager = type("Translations", (), {"install": lambda self, _value: None})()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(privileged_helper.sys, "stdin", io.StringIO(requests)),
            patch.object(
                privileged_helper,
                "emit_event",
                lambda event_type, **payload: events.append((event_type, payload)),
            ),
            patch.object(
                privileged_helper,
                "_execute_request",
                lambda request, **_kwargs: executed.append(request.action) or 0,
            ),
        ):
            exit_code = privileged_helper._run_initialized_session(
                translation_manager,
                initialized=False,
                allowed_aur_targets={},
                attempted_aur_targets=set(),
                aur_build_root=Path(directory),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(executed, [HelperAction.INITIALIZE_UPDATE_SESSION])
        self.assertTrue(
            any("authorized update plan" in str(payload.get("message")) for _, payload in events)
        )

    def test_resolve_aur_build_user_rejects_root(self) -> None:
        with self.assertRaisesRegex(
            privileged_updates.PrivilegedUpdateValidationError,
            "must not be built as root",
        ):
            privileged_updates.resolve_aur_build_user("0")

    def test_validate_request_accepts_reviewed_aur_install(self) -> None:
        review = _review()
        request = privileged_helper.validate_request(
            {
                "action": HelperAction.INSTALL_REVIEWED_AUR.value,
                "aur_review": _review_payload(review),
                "expected_version": "1.0-1",
            }
        )

        self.assertEqual(request.action, HelperAction.INSTALL_REVIEWED_AUR)
        self.assertEqual(request.aur_review, review)
        self.assertEqual(request.expected_version, "1.0-1")

    def test_validate_request_rejects_untyped_aur_pacman_arguments(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.INSTALL_REVIEWED_AUR.value,
                    "pacman_args": ["-U", "/tmp/example.pkg.tar.zst"],
                }
            )

    def test_validate_request_rejects_incomplete_review_manifest(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.INSTALL_REVIEWED_AUR.value,
                    "aur_review": {
                        "package_name": "example",
                        "package_base": "example",
                        "digest": "a" * 64,
                        "files": [],
                    },
                    "expected_version": "1.0-1",
                }
            )

    def test_validate_request_accepts_flatpak_system_update_refs(self) -> None:
        request = privileged_helper.validate_request(
            {
                "action": HelperAction.RUN_FLATPAK_SYSTEM_UPDATE.value,
                "refs": ["app/org.kde.Krita/x86_64/stable"],
                "expected_versions": {
                    "app/org.kde.Krita/x86_64/stable": "5.2.0"
                },
            }
        )

        self.assertEqual(request.action, HelperAction.RUN_FLATPAK_SYSTEM_UPDATE)
        self.assertEqual(request.refs, ["app/org.kde.Krita/x86_64/stable"])

    def test_validate_request_rejects_option_like_flatpak_refs(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.RUN_FLATPAK_SYSTEM_UPDATE.value,
                    "refs": ["--system"],
                }
            )

    def test_validate_request_accepts_firmware_device_id(self) -> None:
        request = privileged_helper.validate_request(
            {
                "action": HelperAction.RUN_FIRMWARE_UPDATE.value,
                "device_id": "2082b5e0-7a64-478a-b1b2-bb484fa8ad17",
                "expected_version": "1.2.0",
            }
        )

        self.assertEqual(request.action, HelperAction.RUN_FIRMWARE_UPDATE)
        self.assertEqual(request.device_id, "2082b5e0-7a64-478a-b1b2-bb484fa8ad17")

    def test_validate_request_rejects_option_like_firmware_version(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.RUN_FIRMWARE_UPDATE.value,
                    "device_id": "2082b5e0-7a64-478a-b1b2-bb484fa8ad17",
                    "expected_version": "--force",
                }
            )

    def test_validate_request_rejects_option_like_firmware_device_id(self) -> None:
        with self.assertRaises(HelperValidationError):
            privileged_helper.validate_request(
                {
                    "action": HelperAction.RUN_FIRMWARE_UPDATE.value,
                    "device_id": "--force",
                }
            )

    def test_remove_support_packages_uses_argument_separator(self) -> None:
        commands: list[list[str]] = []

        with (
            patch.object(support_packages, "PACMAN_PATH", _ExistingPath()),
            patch.object(common, "PACMAN_PATH", _ExistingPath()),
            patch.object(
                support_packages,
                "stream_command",
                lambda command, *, emit_log: commands.append(command) or (0, []),
            ),
        ):
            exit_code = support_packages.remove_support_packages(
                ["fwupd"],
                emit_event=lambda *_args, **_kwargs: None,
                emit_log=lambda _message: None,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("--", commands[0])
        self.assertEqual(commands[0][-2:], ["--", "fwupd"])

    def test_run_system_update_uses_fixed_full_upgrade_command(self) -> None:
        commands: list[list[str]] = []

        def run_command(command, *, emit_log, **_kwargs):  # noqa: ANN001
            commands.append(command)
            self.assertEqual(_kwargs["env"]["LC_ALL"], "C")
            self.assertTrue(_kwargs["survive_parent_exit"])
            self.assertEqual(
                _kwargs["input_handler"](":: Proceed with installation? [Y/n] "), "y\n"
            )
            return 0, []

        with (
            patch.object(privileged_updates, "PACMAN_PATH", _ExistingPath()),
            patch.object(privileged_updates, "SYSTEMD_INHIBIT_PATH", Path("/missing")),
            patch.object(
                privileged_updates,
                "stream_command",
                run_command,
            ),
        ):
            exit_code = privileged_updates.run_system_update(
                {"linux": "6.9-1"},
                emit_event=lambda *_args, **_kwargs: None,
                emit_log=lambda _message: None,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            commands[-1],
            [
                "/usr/bin/pacman",
                "-Syu",
                "--confirm",
                "--color",
                "never",
            ],
        )

    def test_system_update_does_not_refresh_for_a_separate_privileged_preview(self) -> None:
        commands: list[list[str]] = []

        with (
            patch.object(privileged_updates, "PACMAN_PATH", _ExistingPath()),
            patch.object(privileged_updates, "SYSTEMD_INHIBIT_PATH", Path("/missing")),
            patch.object(
                privileged_updates,
                "stream_command",
                lambda command, *, emit_log, **_kwargs: commands.append(command) or (0, []),
            ),
        ):
            exit_code = privileged_updates.run_system_update(
                {"linux": "6.9-1"},
                emit_event=lambda _event, **_payload: None,
                emit_log=lambda _message: None,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][1], "-Syu")
        self.assertNotIn("--print", commands[0])

    def test_install_reviewed_aur_builds_unprivileged_and_installs_private_copy(self) -> None:
        commands: list[list[str]] = []
        build_commands: list[list[str]] = []
        with tempfile.TemporaryDirectory() as directory:
            def run_command(command: list[str], *, emit_log, **_kwargs):  # noqa: ANN001
                commands.append(command)
                if "-Qip" in command:
                    return 0, [
                        "Name : example",
                        "Version : 1.0-1",
                        f"Architecture : {platform.machine()}",
                    ]
                return 0, []

            def run_build(command, *, env, preexec_fn, **_kwargs):  # noqa: ANN001
                build_commands.append(command)
                self.assertIsNotNone(preexec_fn)
                package_path = Path(env["PKGDEST"]) / "example-1.0-1-any.pkg.tar.zst"
                package_path.write_bytes(b"built package")
                source_dir = Path(command[command.index("--dir") + 1])
                self.assertEqual((source_dir / "PKGBUILD").read_text(), _review().pkgbuild)
                self.assertNotEqual((source_dir / "PKGBUILD").stat().st_mode & 0o200, 0)
                sealed_directories = [
                    path
                    for path in source_dir.parent.parent.iterdir()
                    if path.name != "workspace"
                ]
                self.assertEqual(len(sealed_directories), 1)
                self.assertEqual(
                    (sealed_directories[0] / "PKGBUILD").stat().st_mode & 0o222,
                    0,
                )
                return 0, []

            with (
                patch.object(privileged_updates, "PACMAN_PATH", _ExistingPath()),
                patch.object(privileged_updates, "SYSTEMD_INHIBIT_PATH", Path("/missing")),
                patch.object(privileged_updates, "stream_command", run_command),
                patch.object(privileged_updates, "stream_subprocess", run_build),
                patch.object(privileged_updates.os, "chown", lambda *_args: None),
            ):
                exit_code = privileged_updates.install_reviewed_aur(
                    _review(),
                    "1.0-1",
                    expected_package_base="example",
                    build_user=privileged_updates.AurBuildUser(
                        name="test-user",
                        uid=max(1, os.getuid()),
                        gid=os.getgid(),
                        home=Path("/tmp"),
                    ),
                    build_root=Path(directory),
                    emit_event=lambda *_args, **_kwargs: None,
                    emit_log=lambda _message: None,
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(build_commands[0][0], "/usr/bin/makepkg")
        install_command = commands[-1]
        self.assertEqual(
            install_command[:8],
            [
                "/usr/bin/pacman",
                "-U",
                "--confirm",
                "--needed",
                "--color",
                "never",
                "--",
                install_command[7],
            ],
        )
        self.assertIn("/verified/", install_command[-1])

    def test_install_reviewed_aur_rejects_identity_version_mismatch(self) -> None:
        commands: list[list[str]] = []
        with tempfile.TemporaryDirectory() as directory:
            def run_command(command: list[str], *, emit_log):  # noqa: ANN001
                commands.append(command)
                return 0, [
                    "Name : example",
                    "Version : 2.0-1",
                    f"Architecture : {platform.machine()}",
                ]

            def run_build(_command, *, env, **_kwargs):  # noqa: ANN001
                (Path(env["PKGDEST"]) / "example.pkg.tar.zst").write_bytes(b"package")
                return 0, []

            with (
                patch.object(privileged_updates, "PACMAN_PATH", _ExistingPath()),
                patch.object(privileged_updates, "stream_command", run_command),
                patch.object(privileged_updates, "stream_subprocess", run_build),
                patch.object(privileged_updates.os, "chown", lambda *_args: None),
            ):
                exit_code = privileged_updates.install_reviewed_aur(
                    _review(),
                    "1.0-1",
                    expected_package_base="example",
                    build_user=privileged_updates.AurBuildUser(
                        "test-user", max(1, os.getuid()), os.getgid(), Path("/tmp")
                    ),
                    build_root=Path(directory),
                    emit_event=lambda *_args, **_kwargs: None,
                    emit_log=lambda _message: None,
                )

        self.assertEqual(exit_code, 4)
        self.assertFalse(any("-U" in command for command in commands))

    def test_split_aur_artifacts_are_installed_in_one_pacman_transaction(self) -> None:
        commands: list[list[str]] = []
        targets = [
            AurInstallTarget("example-cli", "example", "1.0-1"),
            AurInstallTarget("example-gui", "example", "1.0-1"),
        ]
        review = _review(
            "example-cli",
            package_base="example",
            declared_names=("example-cli", "example-gui"),
        )

        with tempfile.TemporaryDirectory() as directory:
            def run_command(command, *, emit_log, **_kwargs):  # noqa: ANN001
                commands.append(command)
                if "-Qip" in command:
                    path = str(command[-1])
                    name = "example-gui" if "example-gui" in path else "example-cli"
                    return 0, [
                        f"Name : {name}",
                        "Version : 1.0-1",
                        f"Architecture : {platform.machine()}",
                    ]
                return 0, []

            def run_build(_command, *, env, **_kwargs):  # noqa: ANN001
                output = Path(env["PKGDEST"])
                for target in targets:
                    (output / f"{target.package_name}-1.0-1-any.pkg.tar.zst").write_bytes(
                        target.package_name.encode()
                    )
                return 0, []

            with (
                patch.object(privileged_updates, "PACMAN_PATH", _ExistingPath()),
                patch.object(privileged_updates, "SYSTEMD_INHIBIT_PATH", Path("/missing")),
                patch.object(privileged_updates, "stream_command", run_command),
                patch.object(privileged_updates, "stream_subprocess", run_build),
                patch.object(privileged_updates.os, "chown", lambda *_args: None),
            ):
                exit_code = privileged_updates.install_reviewed_aur_group(
                    review,
                    targets,
                    expected_package_base="example",
                    build_user=privileged_updates.AurBuildUser(
                        "test-user", max(1, os.getuid()), os.getgid(), Path("/tmp")
                    ),
                    build_root=Path(directory),
                    emit_event=lambda *_args, **_kwargs: None,
                    emit_log=lambda _message: None,
                )

        self.assertEqual(exit_code, 0)
        install_commands = [command for command in commands if "-U" in command]
        self.assertEqual(len(install_commands), 1)
        self.assertEqual(len(install_commands[0][install_commands[0].index("--") + 1 :]), 2)

    def test_install_reviewed_aur_rejects_symlink_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            def run_build(_command, *, env, **_kwargs):  # noqa: ANN001
                output = Path(env["PKGDEST"])
                target = output / "target"
                target.write_bytes(b"package")
                (output / "example.pkg.tar.zst").symlink_to(target)
                return 0, []

            with (
                patch.object(privileged_updates, "PACMAN_PATH", _ExistingPath()),
                patch.object(privileged_updates, "stream_subprocess", run_build),
                patch.object(privileged_updates.os, "chown", lambda *_args: None),
            ):
                exit_code = privileged_updates.install_reviewed_aur(
                    _review(),
                    "1.0-1",
                    expected_package_base="example",
                    build_user=privileged_updates.AurBuildUser(
                        "test-user", max(1, os.getuid()), os.getgid(), Path("/tmp")
                    ),
                    build_root=Path(directory),
                    emit_event=lambda *_args, **_kwargs: None,
                    emit_log=lambda _message: None,
                )

        self.assertEqual(exit_code, 4)

    def test_run_flatpak_system_update_uses_fixed_command_and_separator(self) -> None:
        commands: list[list[str]] = []
        remote_queries = 0

        def run_command(command, *, emit_log, **_kwargs):  # noqa: ANN001, ANN202
            nonlocal remote_queries
            commands.append(command)
            if "remote-ls" not in command:
                return 0, []
            remote_queries += 1
            if remote_queries == 1:
                return 0, ["app/org.kde.Krita/x86_64/stable\t5.2.0"]
            return 0, []

        with (
            patch.object(privileged_updates, "FLATPAK_PATH", _ExistingPath("/usr/bin/flatpak")),
            patch.object(privileged_updates, "SYSTEMD_INHIBIT_PATH", Path("/missing")),
            patch.object(
                privileged_updates,
                "stream_command",
                run_command,
            ),
        ):
            exit_code = privileged_updates.run_flatpak_system_update(
                ["app/org.kde.Krita/x86_64/stable"],
                {"app/org.kde.Krita/x86_64/stable": "5.2.0"},
                emit_event=lambda *_args, **_kwargs: None,
                emit_log=lambda _message: None,
            )

        self.assertEqual(exit_code, 0)
        update_command = next(command for command in commands if "update" in command)
        self.assertIn("--assumeyes", update_command)
        self.assertEqual(
            update_command[-2:], ["--", "app/org.kde.Krita/x86_64/stable"]
        )

    def test_run_flatpak_system_update_uses_branch_for_runtime_version(self) -> None:
        runtime_ref = "runtime/org.gnome.Platform/x86_64/49"
        commands: list[list[str]] = []
        remote_queries = 0

        def run_command(command, *, emit_log, **_kwargs):  # noqa: ANN001, ANN202
            nonlocal remote_queries
            commands.append(command)
            if "remote-ls" not in command:
                return 0, []
            remote_queries += 1
            return (0, [f"{runtime_ref}\t\t49"]) if remote_queries == 1 else (0, [])

        with (
            patch.object(privileged_updates, "FLATPAK_PATH", _ExistingPath("/usr/bin/flatpak")),
            patch.object(privileged_updates, "SYSTEMD_INHIBIT_PATH", Path("/missing")),
            patch.object(privileged_updates, "stream_command", run_command),
        ):
            exit_code = privileged_updates.run_flatpak_system_update(
                [runtime_ref],
                {runtime_ref: "49"},
                emit_event=lambda *_args, **_kwargs: None,
                emit_log=lambda _message: None,
            )

        self.assertEqual(exit_code, 0)
        preview_command = next(command for command in commands if "remote-ls" in command)
        self.assertIn("--columns=ref,version,branch", preview_command)

    def test_run_flatpak_system_update_fails_if_selected_ref_remains_available(self) -> None:
        events: list[tuple[object, dict[str, object]]] = []

        with (
            patch.object(privileged_updates, "FLATPAK_PATH", _ExistingPath("/usr/bin/flatpak")),
            patch.object(privileged_updates, "SYSTEMD_INHIBIT_PATH", Path("/missing")),
            patch.object(
                privileged_updates,
                "stream_command",
                lambda command, *, emit_log, **_kwargs: (
                    (0, ["app/org.kde.Krita/x86_64/stable\t5.2.0"])
                    if "remote-ls" in command
                    else (0, [])
                ),
            ),
        ):
            exit_code = privileged_updates.run_flatpak_system_update(
                ["app/org.kde.Krita/x86_64/stable"],
                {"app/org.kde.Krita/x86_64/stable": "5.2.0"},
                emit_event=lambda event, **payload: events.append((event, payload)),
                emit_log=lambda _message: None,
            )

        self.assertEqual(exit_code, 3)
        self.assertEqual(events[-1][1]["reason"], "postcondition_failed")

    def test_run_firmware_update_uses_fixed_fwupdmgr_command(self) -> None:
        commands: list[list[str]] = []

        with (
            patch.object(privileged_updates, "FWUPDMGR_PATH", _ExistingPath("/usr/bin/fwupdmgr")),
            patch.object(privileged_updates, "SYSTEMD_INHIBIT_PATH", Path("/missing")),
            patch.object(
                privileged_updates,
                "stream_command",
                lambda command, *, emit_log, **_kwargs: commands.append(command) or (0, []),
            ),
        ):
            exit_code = privileged_updates.run_firmware_update(
                "device-a",
                "1.2.0",
                emit_event=lambda *_args, **_kwargs: None,
                emit_log=lambda _message: None,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            commands[0],
            [
                "/usr/bin/fwupdmgr",
                "install",
                "--assume-yes",
                "--no-reboot-check",
                "--no-device-prompt",
                "--",
                "device-a",
                "1.2.0",
            ],
        )

    def test_critical_commands_are_wrapped_in_a_shutdown_inhibitor(self) -> None:
        with patch.object(
            privileged_updates,
            "SYSTEMD_INHIBIT_PATH",
            _ExistingPath("/usr/bin/systemd-inhibit"),
        ):
            command = privileged_updates._critical_command(["/usr/bin/pacman", "-Su"])

        self.assertEqual(command[0], "/usr/bin/systemd-inhibit")
        self.assertIn("--what=shutdown:sleep", command)
        self.assertEqual(command[-2:], ["/usr/bin/pacman", "-Su"])


if __name__ == "__main__":
    unittest.main()
