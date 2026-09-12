from __future__ import annotations

import argparse
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.batch.runner import BatchRunner
from archupdater.batch_update_runner import main as batch_main
from archupdater.application.helper_protocol import HelperAction, HelperRequest
from archupdater.domain.aur import AurPkgbuildReview, AurReviewFile, AurVcsSource
from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import (
    UpdatePlan,
    UpdatePlanAction,
    UpdatePlanItem,
)
from archupdater.application.update_session.plan import BatchPlanInspector
from archupdater.application.update_session.protocol import BatchEventType, BatchOutcome
from archupdater.application.update_session.messages import UpdateSessionMessages
from archupdater.application.update_session.backend import BackendRunResult
from archupdater.application.update_session.backend import CommandRunResult
from archupdater.application.update_session.errors import (
    BatchAuthenticationCancelled,
    BatchCancelled,
)
from archupdater.application.update_session.step_backends import (
    AurBackend,
    FirmwareBackend,
    FlatpakBackend,
    PacmanBackend,
    _parse_flatpak_version_output,
)


def _plan(*items: UpdatePlanItem) -> UpdatePlan:
    return UpdatePlan(items=list(items))


def _system(name: str) -> UpdatePlanItem:
    return UpdatePlanItem(UpdateSource.SYSTEM, name, expected_version="2.0-1")


def _aur(name: str) -> UpdatePlanItem:
    return UpdatePlanItem(
        UpdateSource.AUR,
        name,
        package_name=name,
        package_base=name,
        expected_version="1.0-1",
    )


def _flatpak(ref: str, scope: str = "system") -> UpdatePlanItem:
    return UpdatePlanItem(
        UpdateSource.FLATPAK,
        ref,
        installation_scope=scope,
        expected_version="2.0",
    )


def _flatpak_cleanup(scope: str) -> UpdatePlanItem:
    return UpdatePlanItem(
        UpdateSource.FLATPAK,
        scope,
        action=UpdatePlanAction.CLEANUP,
        installation_scope=scope,
    )


def _firmware(device_id: str) -> UpdatePlanItem:
    return UpdatePlanItem(UpdateSource.FIRMWARE, device_id, expected_version="1.2.0")


def _widget(content_id: str, package_name: str = "Panel Colorizer") -> UpdatePlanItem:
    return UpdatePlanItem(
        UpdateSource.PLASMA_WIDGET,
        content_id,
        package_name=package_name,
        package_kind="Plasma/Applet",
    )


class _StaticAurBackend:
    step_key = "aur"
    exit_code = 3
    outcome = BatchOutcome.FAILED.value

    def __init__(
        self,
        *,
        result: BackendRunResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._result = result
        self._error = error

    def should_run(self, _plan: UpdatePlan) -> bool:
        return True

    def label(self, _context) -> str:  # noqa: ANN001
        return "AUR"

    def start_message(self, _context) -> str:  # noqa: ANN001
        return "Now installing the selected AUR updates with makepkg."

    def run(self, _context) -> BackendRunResult:  # noqa: ANN001
        if self._error is not None:
            raise self._error
        if self._result is None:
            raise AssertionError("Static backend result was not configured.")
        return self._result


class BatchRunnerTests(unittest.TestCase):
    def test_flatpak_json_versions_are_parsed_without_tty_table_ambiguity(self) -> None:
        self.assertEqual(
            _parse_flatpak_version_output(
                '[{"ref":"app/org.example.App/x86_64/stable","version":"2.0"}]'
            ),
            {"app/org.example.App/x86_64/stable": "2.0"},
        )
        self.assertIsNone(
            _parse_flatpak_version_output(
                "Ref                                      Version\n"
                "app/org.example.App/x86_64/stable        2.0\n"
            )
        )

    def test_flatpak_runtime_version_falls_back_to_branch(self) -> None:
        self.assertEqual(
            _parse_flatpak_version_output(
                '[{"ref":"runtime/org.gnome.Platform/x86_64/49",'
                '"version":"","branch":"49"}]'
            ),
            {"runtime/org.gnome.Platform/x86_64/49": "49"},
        )

    def _runner(self, plan: UpdatePlan | None = None) -> BatchRunner:
        runner = object.__new__(BatchRunner)
        runner._plan = plan or UpdatePlan()
        runner._step_results = {}
        runner._t = lambda value: value  # type: ignore[method-assign]
        runner._service = types.SimpleNamespace()
        runner._plan_inspector = BatchPlanInspector(
            runner._plan,
            translate=runner._t,
        )
        runner._session_messages = UpdateSessionMessages(runner._t)
        runner._session_log = types.SimpleNamespace(
            path=Path("/tmp/archupdater-test.log"),
            write_line=lambda _line: None,
        )
        runner._interaction = types.SimpleNamespace(request_question=lambda _payload: True)
        runner._privileged_helper = types.SimpleNamespace(
            authorize=lambda: CommandRunResult(True, ""),
            run=lambda _request, *, failure_message: CommandRunResult(True, ""),
            close=lambda: None,
        )
        runner._run_command = lambda command, **_kwargs: CommandRunResult(  # type: ignore[method-assign]
            True,
            payload={
                "output": "\n".join(
                    f"{item.target_id} 1.0-1 -> {item.expected_version}"
                    for item in runner._plan.update_items(UpdateSource.SYSTEM)
                )
                if command and command[0] == "checkupdates"
                else ""
            },
        )
        return runner

    def _run_static_aur_backend(
        self,
        backend: _StaticAurBackend,
    ) -> tuple[
        int,
        list[tuple[str, dict[str, object]]],
        list[str],
    ]:
        runner = self._runner(_plan(_aur("spotify")))
        runner._print_banner = lambda: None  # type: ignore[method-assign]
        runner._print_summary = lambda *, success: None  # type: ignore[method-assign]
        printed: list[str] = []
        runner._print_line = printed.append  # type: ignore[method-assign]
        runner._backends = [backend]
        emitted: list[tuple[str, dict[str, object]]] = []
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )
        return runner.run(), emitted, printed

    def test_main_uses_saved_language_preference(self) -> None:
        install_calls: list[object] = []
        runner_calls: list[tuple[UpdatePlan, object]] = []
        app_metadata_calls: list[tuple[str, object]] = []

        class _FakeApplication:
            def setApplicationName(self, value: str) -> None:
                app_metadata_calls.append(("app_name", value))

            def setOrganizationName(self, value: str) -> None:
                app_metadata_calls.append(("org_name", value))

        class _FakeTranslationManager:
            def __init__(self, _app) -> None:  # noqa: ANN001
                pass

            def install(self, preference: object) -> None:
                install_calls.append(preference)

        class _FakeSettingsService:
            def language_preference(self) -> str:
                return "it"

        class _FakeBatchRunner:
            def __init__(self, plan: UpdatePlan, events) -> None:  # noqa: ANN001
                runner_calls.append((plan, events))

            def run(self) -> int:
                return 0

        with (
            patch("archupdater.batch_update_runner.QCoreApplication", return_value=_FakeApplication()),
            patch("archupdater.batch_update_runner.TranslationManager", _FakeTranslationManager),
            patch("archupdater.batch_update_runner.SettingsService", _FakeSettingsService),
            patch(
                "archupdater.batch_update_runner._parse_args",
                return_value=argparse.Namespace(plan="/tmp/plan.json", events="/tmp/events.jsonl"),
            ),
            patch(
                "archupdater.batch_update_runner._load_plan",
                return_value=_plan(_system("linux")),
            ),
            patch("archupdater.batch_update_runner.BatchRunner", _FakeBatchRunner),
        ):
            exit_code = batch_main([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(install_calls, ["it"])
        self.assertEqual(
            app_metadata_calls,
            [
                ("app_name", "ArchUpdater"),
                ("org_name", "ArchUpdater"),
            ],
        )
        self.assertEqual(len(runner_calls), 1)

    def test_main_emits_structured_failure_when_runner_construction_fails(self) -> None:
        emitted: list[tuple[str, dict[str, object]]] = []

        class _FakeApplication:
            def setApplicationName(self, _value: str) -> None:
                pass

            def setOrganizationName(self, _value: str) -> None:
                pass

        class _FakeTranslationManager:
            def __init__(self, _app) -> None:  # noqa: ANN001
                pass

            def install(self, _preference: object) -> None:
                pass

        class _FakeSettingsService:
            def language_preference(self) -> str:
                return "en"

        class _FakeEventWriter:
            def __init__(self, _path: Path) -> None:
                pass

            def emit(self, event_type: str, **payload: object) -> None:
                emitted.append((event_type, payload))

        with (
            patch("archupdater.batch_update_runner.QCoreApplication", return_value=_FakeApplication()),
            patch("archupdater.batch_update_runner.TranslationManager", _FakeTranslationManager),
            patch("archupdater.batch_update_runner.SettingsService", _FakeSettingsService),
            patch("archupdater.batch_update_runner.EventWriter", _FakeEventWriter),
            patch(
                "archupdater.batch_update_runner._parse_args",
                return_value=argparse.Namespace(plan="/tmp/plan.json", events="/tmp/events.jsonl"),
            ),
            patch("archupdater.batch_update_runner._load_plan", return_value=UpdatePlan()),
            patch("archupdater.batch_update_runner.BatchRunner", side_effect=OSError("disk full")),
        ):
            exit_code = batch_main([])

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            emitted,
            [
                (
                    BatchEventType.BATCH_COMPLETED.value,
                    {
                        "success": False,
                        "message": "disk full",
                        "outcome": BatchOutcome.FAILED.value,
                        "completed": [],
                        "incomplete": [],
                        "failed": [],
                        "not_executed": [],
                    },
                )
            ],
        )

    def test_print_banner_lists_selected_update_targets(self) -> None:
        printed: list[str] = []
        runner = self._runner(
            _plan(
                _system("python-more-itertools"),
                _aur("spotify"),
                _flatpak("app/org.kde.Krita/x86_64/stable"),
                _flatpak("app/com.spotify.Client/x86_64/stable", "user"),
                _firmware("device-a"),
                _firmware("device-b"),
                _widget("widget-1"),
            )
        )
        runner._print_line = printed.append  # type: ignore[attr-defined]

        runner._print_banner()

        joined = "\n".join(printed)
        self.assertIn("ArchUpdater update session", joined)
        self.assertIn("The following updates will be installed:", joined)
        self.assertIn("Pacman: 1 package", joined)
        self.assertIn("AUR: 1 package", joined)
        self.assertIn("Flatpak (system): 1 update", joined)
        self.assertIn("Flatpak (user): 1 update", joined)
        self.assertIn("Firmware: 2 devices", joined)
        self.assertIn("KDE Store Add-ons: 1 add-on", joined)
        self.assertIn("You may be asked to authorize privileged update steps.", joined)
        self.assertGreaterEqual(joined.count("-" * 56), 3)

    def test_print_banner_includes_password_message_for_aur_plan(self) -> None:
        printed: list[str] = []
        runner = self._runner(
            _plan(
                _aur("spotify"),
                _flatpak("app/com.spotify.Client/x86_64/stable", "user"),
            )
        )
        runner._print_line = printed.append  # type: ignore[attr-defined]

        runner._print_banner()

        joined = "\n".join(printed)
        self.assertIn("AUR: 1 package", joined)
        self.assertIn("Flatpak (user): 1 update", joined)
        self.assertIn("You may be asked to authorize privileged update steps.", joined)

    def test_print_banner_skips_password_message_for_user_flatpak_plan(self) -> None:
        printed: list[str] = []
        runner = self._runner(_plan(_flatpak("app/com.spotify.Client/x86_64/stable", "user")))
        runner._print_line = printed.append  # type: ignore[attr-defined]

        runner._print_banner()

        joined = "\n".join(printed)
        self.assertIn("Flatpak (user): 1 update", joined)
        self.assertNotIn("You may be asked to authorize privileged update steps.", joined)

    def test_privileged_auth_is_required_for_selected_privileged_sources(self) -> None:
        inspector = BatchPlanInspector(
            _plan(
                _system("linux"),
                _aur("spotify"),
                _flatpak("app/com.bitwarden.desktop/x86_64/stable"),
            ),
            translate=lambda value: value,
        )

        self.assertTrue(inspector.requires_privileged_auth())

    def test_start_step_prints_numbered_header_and_emits_event(self) -> None:
        printed: list[str] = []
        emitted: list[tuple[str, dict[str, str]]] = []
        runner = self._runner(
            _plan(
                _system("python-more-itertools"),
                _flatpak("app/org.kde.Krita/x86_64/stable"),
            )
        )
        runner._print_line = printed.append  # type: ignore[attr-defined]
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )

        runner._start_step(
            "flatpak",
            "Flatpak",
            "Now installing the selected Flatpak updates.",
        )

        joined = "\n".join(printed)
        self.assertIn("[2/2] Flatpak", joined)
        self.assertIn("Now installing the selected Flatpak updates.", joined)
        self.assertGreaterEqual(joined.count("-" * 56), 2)
        self.assertEqual(
            emitted,
            [
                (
                    "step_started",
                    {
                        "step": "flatpak",
                        "message": "Now installing the selected Flatpak updates.",
                    },
                )
            ],
        )

    def test_start_step_prints_transition_message_for_following_steps(self) -> None:
        printed: list[str] = []
        emitted: list[tuple[str, dict[str, str]]] = []
        runner = self._runner(
            _plan(_system("python-more-itertools"), _aur("spotify"))
        )
        runner._print_line = printed.append  # type: ignore[attr-defined]
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )

        runner._start_step(
            "aur",
            "AUR",
            "Now installing the selected AUR updates with yay.",
        )

        joined = "\n".join(printed)
        self.assertIn("Continuing with AUR package updates.", joined)
        self.assertIn("[2/2] AUR", joined)
        self.assertGreaterEqual(joined.count("-" * 56), 2)
        self.assertEqual(
            emitted,
            [
                (
                    "step_started",
                    {
                        "step": "aur",
                        "message": "Now installing the selected AUR updates with yay.",
                    },
                )
            ],
        )

    def test_flatpak_step_runs_optional_unused_runtime_cleanup(self) -> None:
        commands: list[list[str]] = []
        runner = self._runner(
            _plan(
                _flatpak("app/org.kde.Krita/x86_64/stable", "user"),
                _flatpak_cleanup("user"),
            )
        )
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        remote_queries = 0

        def run_command(command, **_kwargs):  # noqa: ANN001, ANN202
            nonlocal remote_queries
            commands.append(command)
            output = ""
            if "remote-ls" in command:
                remote_queries += 1
                if remote_queries == 1:
                    output = "app/org.kde.Krita/x86_64/stable\t2.0\n"
            return CommandRunResult(True, "ok", payload={"output": output})

        runner._run_command = run_command  # type: ignore[method-assign]

        result = runner._run_backend_step(FlatpakBackend())

        self.assertTrue(result.success)
        self.assertEqual(result.message, "Flatpak update completed successfully.")
        self.assertIn(
            [
                "flatpak",
                "uninstall",
                "--user",
                "--unused",
                "--assumeyes",
                "--noninteractive",
            ],
            commands,
        )
        self.assertIn(
            [
                "flatpak",
                "update",
                "--user",
                "--assumeyes",
                "--noninteractive",
                "--",
                "app/org.kde.Krita/x86_64/stable",
            ],
            commands,
        )

    def test_user_flatpak_step_fails_if_selected_ref_remains_available(self) -> None:
        runner = self._runner(
            _plan(_flatpak("app/org.kde.Krita/x86_64/stable", "user"))
        )
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._run_command = lambda command, **_kwargs: CommandRunResult(  # type: ignore[method-assign]
            True,
            "ok",
            payload={"output": "app/org.kde.Krita/x86_64/stable\t2.0\n"}
            if "remote-ls" in command
            else {"output": ""},
        )

        result = runner._run_backend_step(FlatpakBackend())

        self.assertFalse(result.success)
        self.assertTrue(result.incomplete)
        self.assertIn("without installing", result.message)

    def test_flatpak_step_accepts_deployed_refs_after_follow_up_error(self) -> None:
        runner = self._runner(
            _plan(_flatpak("app/org.kde.Krita/x86_64/stable", "system"))
        )
        printed: list[str] = []
        remote_queries = 0
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = printed.append  # type: ignore[method-assign]

        def run_command(command, **_kwargs):  # noqa: ANN001, ANN202
            nonlocal remote_queries
            if "remote-ls" in command:
                remote_queries += 1
                output = (
                    '[{"ref":"app/org.kde.Krita/x86_64/stable","version":"2.0"}]'
                    if remote_queries == 1
                    else "[]"
                )
                return CommandRunResult(True, payload={"output": output})
            return CommandRunResult(False, "Error deploying: Directory not empty")

        runner._run_command = run_command  # type: ignore[method-assign]

        result = runner._run_backend_step(FlatpakBackend())

        self.assertTrue(result.success)
        self.assertTrue(result.changed)
        self.assertTrue(result.incomplete)
        self.assertIn("follow-up error", result.message)
        self.assertTrue(any("were deployed" in line for line in printed))

    def test_flatpak_runtime_branch_matches_reviewed_version(self) -> None:
        runtime_ref = "runtime/org.gnome.Platform/x86_64/49"
        runner = self._runner(
            _plan(
                UpdatePlanItem(
                    UpdateSource.FLATPAK,
                    runtime_ref,
                    installation_scope="system",
                    expected_version="49",
                )
            )
        )
        commands: list[list[str]] = []
        questions: list[dict[str, object]] = []
        remote_queries = 0
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._request_question = lambda question: questions.append(question) or False  # type: ignore[method-assign]

        def run_command(command, **_kwargs):  # noqa: ANN001, ANN202
            nonlocal remote_queries
            commands.append(command)
            if "remote-ls" in command:
                remote_queries += 1
                output = (
                    '[{"ref":"runtime/org.gnome.Platform/x86_64/49",'
                    '"version":"","branch":"49"}]'
                    if remote_queries == 1
                    else "[]"
                )
                return CommandRunResult(True, payload={"output": output})
            return CommandRunResult(True, "ok", payload={"output": ""})

        runner._run_command = run_command  # type: ignore[method-assign]

        result = runner._run_backend_step(FlatpakBackend())

        self.assertTrue(result.success)
        self.assertEqual(questions, [])
        self.assertIn(
            [
                "flatpak",
                "update",
                "--system",
                "--assumeyes",
                "--noninteractive",
                "--",
                runtime_ref,
            ],
            commands,
        )

    def test_aur_step_sends_reviewed_manifest_to_typed_privileged_request(self) -> None:
        requests: list[HelperRequest] = []
        discarded: list[str] = []
        plan = _plan(_aur("spotify"))
        runner = self._runner(plan)
        review = AurPkgbuildReview(
            "spotify",
            "spotify",
            "pkgname=spotify",
            commit="a" * 40,
            digest="b" * 64,
            files=(AurReviewFile("PKGBUILD", "c" * 64, 15, "pkgname=spotify"),),
            preparation_id="prepared",
        )
        runner._service = types.SimpleNamespace(
            aur_pkgbuild_review=lambda package_name, package_base=None: review,
            aur_missing_build_dependencies=lambda candidate: [],
            discard_aur_pkgbuild_review=lambda candidate: discarded.append(
                candidate.preparation_id
            ),
        )
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._command_available = lambda _command: True  # type: ignore[method-assign]
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            requests.append(request) or CommandRunResult(True, "")
        )

        result = runner._run_backend_step(AurBackend())

        self.assertTrue(result.success)
        self.assertEqual(requests[0].action, HelperAction.INSTALL_REVIEWED_AUR)
        self.assertEqual(requests[0].aur_review, review)
        self.assertEqual(requests[0].expected_version, "1.0-1")
        self.assertEqual(discarded, ["prepared"])

    def test_aur_split_packages_are_built_and_installed_as_one_group(self) -> None:
        items = [
            UpdatePlanItem(
                UpdateSource.AUR,
                name,
                package_name=name,
                package_base="example",
                expected_version="1.0-1",
            )
            for name in ("example-cli", "example-gui")
        ]
        runner = self._runner(UpdatePlan(items))
        review_calls: list[tuple[str, str | None]] = []
        requests: list[HelperRequest] = []
        review = AurPkgbuildReview(
            "example-cli",
            "example",
            "pkgbase=example",
            preparation_id="split-review",
        )
        runner._service = types.SimpleNamespace(
            aur_pkgbuild_review=lambda name, package_base=None: (
                review_calls.append((name, package_base)) or review
            ),
            aur_missing_build_dependencies=lambda _review: [],
            discard_aur_pkgbuild_review=lambda _review: None,
        )
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._command_available = lambda _command: True  # type: ignore[method-assign]
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            requests.append(request) or CommandRunResult(True)
        )

        result = runner._run_backend_step(AurBackend())

        self.assertTrue(result.success)
        self.assertEqual(review_calls, [("example-cli", "example")])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].action, HelperAction.INSTALL_REVIEWED_AUR_GROUP)
        self.assertEqual(
            [target.package_name for target in requests[0].aur_targets or []],
            ["example-cli", "example-gui"],
        )

    def test_aur_dynamic_update_locks_commit_and_records_concrete_version(self) -> None:
        item = UpdatePlanItem(
            UpdateSource.AUR,
            "example-git",
            package_name="example-git",
            package_base="example-git",
            expected_version="latest-commit",
            current_version="r1.aaaaaaa-1",
            dynamic_version=True,
        )
        runner = self._runner(UpdatePlan([item]))
        source = AurVcsSource(
            "example-git",
            "https://example.invalid/example.git",
            None,
            "b" * 40,
        )
        review = AurPkgbuildReview(
            "example-git",
            "example-git",
            "pkgname=example-git",
            vcs_sources=(source,),
            preparation_id="dynamic-review",
        )
        review_calls: list[tuple[str, str | None, bool]] = []
        receipts: list[tuple[str, str, tuple[AurVcsSource, ...]]] = []

        def review_package(name, package_base=None, *, lock_vcs_sources=False):  # noqa: ANN001
            review_calls.append((name, package_base, lock_vcs_sources))
            return review

        runner._service = types.SimpleNamespace(
            aur_pkgbuild_review=review_package,
            aur_missing_build_dependencies=lambda _review: [],
            discard_aur_pkgbuild_review=lambda _review: None,
            record_aur_vcs_install=lambda name, version, sources: receipts.append(
                (name, version, sources)
            ),
        )
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._command_available = lambda _command: True  # type: ignore[method-assign]
        requests: list[HelperRequest] = []
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            requests.append(request)
            or CommandRunResult(
                True,
                payload={"actual_versions": {"example-git": "r2.bbbbbbb-1"}},
            )
        )

        result = runner._run_backend_step(AurBackend())

        self.assertTrue(result.success)
        self.assertEqual(review_calls, [("example-git", "example-git", True)])
        self.assertEqual(requests[0].expected_version, "latest-commit")
        self.assertEqual((requests[0].aur_review or review).vcs_sources, (source,))
        self.assertEqual(
            receipts,
            [("example-git", "r2.bbbbbbb-1", (source,))],
        )

    def test_aur_step_skips_package_when_pkgbuild_review_is_cancelled(self) -> None:
        calls: list[HelperRequest] = []
        runner = self._runner(_plan(_aur("spotify")))
        discarded: list[str] = []
        runner._service = types.SimpleNamespace(
            aur_pkgbuild_review=lambda package_name, package_base=None: AurPkgbuildReview(
                package_name,
                package_base or package_name,
                "pkgname=spotify",
                preparation_id="prepared",
            ),
            discard_aur_pkgbuild_review=lambda review: discarded.append(
                review.preparation_id
            ),
        )
        emitted: list[tuple[str, dict[str, object]]] = []
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )
        runner._interaction = types.SimpleNamespace(request_question=lambda _payload: False)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._command_available = lambda _command: True  # type: ignore[method-assign]
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            calls.append(request) or CommandRunResult(True, "")
        )

        result = runner._run_backend_step(AurBackend())

        self.assertTrue(result.success)
        self.assertFalse(result.changed)
        self.assertTrue(result.incomplete)
        self.assertEqual(result.message, "AUR updates were skipped after PKGBUILD review.")
        self.assertEqual(calls, [])
        self.assertEqual(discarded, ["prepared"])
        self.assertIn(
            (
                BatchEventType.PROGRESS.value,
                {
                    "kind": "aur_pkgbuild_review_skipped",
                    "target_id": "spotify",
                    "package_name": "spotify",
                    "reason": "PKGBUILD review was cancelled.",
                },
            ),
            emitted,
        )
        step_completed = next(
            payload
            for event_type, payload in emitted
            if event_type == BatchEventType.STEP_COMPLETED.value
        )
        self.assertTrue(step_completed["success"])
        self.assertFalse(step_completed["changed"])
        self.assertTrue(step_completed["incomplete"])

    def test_aur_step_installs_confirmed_packages_one_at_a_time(self) -> None:
        requests: list[HelperRequest] = []
        questions: list[dict[str, object]] = []
        runner = self._runner(_plan(_aur("spotify"), _aur("visual-studio-code-bin")))
        runner._service = types.SimpleNamespace(
            aur_pkgbuild_review=lambda package_name, package_base=None: AurPkgbuildReview(
                package_name,
                package_base or package_name,
                f"pkgname={package_name}",
                preparation_id=package_name,
            ),
            aur_missing_build_dependencies=lambda review: [],
            discard_aur_pkgbuild_review=lambda review: None,
        )
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._interaction = types.SimpleNamespace(
            request_question=lambda payload: questions.append(payload) or True
        )
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._command_available = lambda _command: True  # type: ignore[method-assign]
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            requests.append(request) or CommandRunResult(True, "")
        )

        result = runner._run_backend_step(AurBackend())

        self.assertTrue(result.success)
        self.assertTrue(result.changed)
        self.assertFalse(result.incomplete)
        self.assertEqual(
            [request.action for request in requests],
            [
                HelperAction.INSTALL_REVIEWED_AUR,
                HelperAction.INSTALL_REVIEWED_AUR,
            ],
        )
        self.assertEqual(
            [question["package_name"] for question in questions],
            ["spotify", "visual-studio-code-bin"],
        )

    def test_aur_step_reports_changed_and_incomplete_when_only_some_reviews_continue(
        self,
    ) -> None:
        decisions = iter((True, False))
        install_requests: list[HelperRequest] = []
        runner = self._runner(_plan(_aur("spotify"), _aur("visual-studio-code-bin")))
        runner._service = types.SimpleNamespace(
            aur_pkgbuild_review=lambda package_name, package_base=None: AurPkgbuildReview(
                package_name,
                package_base or package_name,
                f"pkgname={package_name}",
                preparation_id=package_name,
            ),
            aur_missing_build_dependencies=lambda review: [],
            discard_aur_pkgbuild_review=lambda review: None,
        )
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._interaction = types.SimpleNamespace(
            request_question=lambda _payload: next(decisions)
        )
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._command_available = lambda _command: True  # type: ignore[method-assign]
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            install_requests.append(request) or CommandRunResult(True, "")
        )

        result = runner._run_backend_step(AurBackend())

        self.assertTrue(result.success)
        self.assertTrue(result.changed)
        self.assertTrue(result.incomplete)
        self.assertEqual(result.message, "AUR update completed with skipped packages.")
        self.assertEqual(len(install_requests), 1)
        self.assertEqual(install_requests[0].action, HelperAction.INSTALL_REVIEWED_AUR)

    def test_aur_step_fails_explicitly_when_build_dependencies_are_missing(self) -> None:
        install_requests: list[HelperRequest] = []
        runner = self._runner(_plan(_aur("spotify")))
        runner._service = types.SimpleNamespace(
            aur_pkgbuild_review=lambda package_name, package_base=None: AurPkgbuildReview(
                package_name,
                package_base or package_name,
                "pkgname=spotify",
                preparation_id="prepared",
            ),
            aur_missing_build_dependencies=lambda review: ["libfoo>=2", "cmake"],
            discard_aur_pkgbuild_review=lambda review: None,
        )
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._command_available = lambda _command: True  # type: ignore[method-assign]
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            install_requests.append(request) or CommandRunResult(True, "")
        )

        result = runner._run_backend_step(AurBackend())

        self.assertFalse(result.success)
        self.assertIn("libfoo>=2", result.message)
        self.assertIn("Install them explicitly", result.message)
        self.assertEqual(install_requests, [])

    def test_flatpak_system_update_and_cleanup_use_flatpak_polkit_flow(self) -> None:
        requests: list[HelperRequest] = []
        commands: list[list[str]] = []
        remote_queries = 0
        runner = self._runner(
            _plan(
                _flatpak("app/org.kde.Krita/x86_64/stable", "system"),
                _flatpak_cleanup("system"),
            )
        )
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            requests.append(request) or CommandRunResult(True, "")
        )

        def run_command(command, **_kwargs):  # noqa: ANN001, ANN202
            nonlocal remote_queries
            commands.append(command)
            output = ""
            if "remote-ls" in command:
                remote_queries += 1
                if remote_queries == 1:
                    output = "app/org.kde.Krita/x86_64/stable\t2.0\n"
            return CommandRunResult(True, "ok", payload={"output": output})

        runner._run_command = run_command  # type: ignore[method-assign]

        result = runner._run_backend_step(FlatpakBackend())

        self.assertTrue(result.success)
        self.assertEqual(requests, [])
        self.assertIn(
            [
                "flatpak",
                "update",
                "--system",
                "--assumeyes",
                "--noninteractive",
                "--",
                "app/org.kde.Krita/x86_64/stable",
            ],
            commands,
        )
        self.assertIn(
            [
                "flatpak",
                "uninstall",
                "--system",
                "--unused",
                "--assumeyes",
                "--noninteractive",
            ],
            commands,
        )

    def test_flatpak_cleanup_failure_fails_flatpak_step(self) -> None:
        runner = self._runner(_plan(_flatpak_cleanup("user")))
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._run_command = lambda _command, **_kwargs: CommandRunResult(  # type: ignore[method-assign]
            False, "Flatpak cleanup failed. (exit code 1)"
        )

        result = runner._run_backend_step(FlatpakBackend())

        self.assertFalse(result.success)
        self.assertEqual(result.message, "Flatpak cleanup failed. (exit code 1)")

    def test_transition_message_is_specific_for_firmware_step(self) -> None:
        printed: list[str] = []
        emitted: list[tuple[str, dict[str, str]]] = []
        runner = self._runner(
            _plan(_system("python-more-itertools"), _firmware("device-a"))
        )
        runner._print_line = printed.append  # type: ignore[attr-defined]
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )

        runner._start_step(
            "firmware",
            "Firmware",
            "Now installing the selected firmware updates.",
        )

        joined = "\n".join(printed)
        self.assertIn("Continuing with firmware updates.", joined)
        self.assertIn("[2/2] Firmware", joined)
        self.assertGreaterEqual(joined.count("-" * 56), 2)
        self.assertEqual(
            emitted,
            [
                (
                    "step_started",
                    {
                        "step": "firmware",
                        "message": "Now installing the selected firmware updates.",
                    },
                )
            ],
        )

    def test_firmware_step_attempts_remaining_devices_after_device_failure(self) -> None:
        runner = self._runner(_plan(_firmware("device-a"), _firmware("device-b")))
        requests: list[HelperRequest] = []
        results = [
            CommandRunResult(False, "Firmware update failed. (exit code 1)"),
            CommandRunResult(True),
        ]
        completed: list[tuple[str, BackendRunResult]] = []
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            requests.append(request) or results.pop(0)
        )
        runner._finish_step = lambda step, result: completed.append(  # type: ignore[method-assign]
            (step, result)
        )

        result = runner._run_backend_step(FirmwareBackend())

        self.assertFalse(result.success)
        self.assertIn("Updated 1 firmware device", result.message)
        self.assertIn("device-a", result.message)
        self.assertEqual([request.device_id for request in requests], ["device-a", "device-b"])
        self.assertEqual(
            [request.action for request in requests],
            [HelperAction.RUN_FIRMWARE_UPDATE, HelperAction.RUN_FIRMWARE_UPDATE],
        )
        self.assertEqual(completed[-1][0], "firmware")
        self.assertFalse(completed[-1][1].success)

    def test_fail_prints_guided_footer_and_emits_batch_completed(self) -> None:
        printed: list[str] = []
        emitted: list[tuple[str, dict[str, object]]] = []
        runner = self._runner(_plan(_aur("yay")))
        runner._print_line = printed.append  # type: ignore[attr-defined]
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )
        runner._step_results = {"aur": "failed"}

        exit_code = runner._fail("AUR update failed. (exit code 1)", exit_code=3)

        joined = "\n".join(printed)
        self.assertEqual(exit_code, 3)
        self.assertIn("No further update steps will be executed.", joined)
        self.assertIn("Update summary", joined)
        self.assertIn("Failed", joined)
        self.assertIn("- AUR", joined)
        self.assertIn("Next step", joined)
        self.assertIn("Failed: AUR update failed. (exit code 1)", joined)
        self.assertIn("Review the update log above before closing this window.", joined)
        self.assertGreaterEqual(joined.count("-" * 56), 4)
        self.assertEqual(
            emitted,
            [
                (
                    "batch_completed",
                    {
                        "success": False,
                        "message": "AUR update failed. (exit code 1)",
                        "outcome": "failed",
                        "completed": [],
                        "incomplete": [],
                        "failed": ["AUR"],
                        "not_executed": [],
                    },
                )
            ],
        )

    def test_print_summary_lists_completed_failed_and_not_executed_steps(self) -> None:
        printed: list[str] = []
        runner = self._runner(
            _plan(
                _system("linux"),
                _aur("spotify"),
                _flatpak("app/org.kde.Krita/x86_64/stable"),
            )
        )
        runner._print_line = printed.append  # type: ignore[attr-defined]
        runner._step_results = {
            "system": "completed",
            "aur": "failed",
        }

        runner._print_summary(success=False)

        joined = "\n".join(printed)
        self.assertIn("Update summary", joined)
        self.assertIn("Completed", joined)
        self.assertIn("- Pacman", joined)
        self.assertIn("Failed", joined)
        self.assertIn("- AUR", joined)
        self.assertIn("Not executed", joined)
        self.assertIn("- Flatpak", joined)
        self.assertIn("Review the live activity log, then run the remaining updates again.", joined)

    def test_print_summary_marks_skipped_aur_step_as_incomplete(self) -> None:
        printed: list[str] = []
        runner = self._runner(_plan(_aur("spotify")))
        runner._print_line = printed.append  # type: ignore[method-assign]
        runner._step_results = {"aur": "incomplete"}

        runner._print_summary(success=True)

        joined = "\n".join(printed)
        self.assertIn("Incomplete", joined)
        self.assertIn("- AUR", joined)
        self.assertIn("Skipped AUR updates remain available and can be retried later.", joined)
        self.assertNotIn("No further action is required.", joined)

    def test_print_command_uses_shell_join_and_emits_log_and_command_event(self) -> None:
        printed: list[str] = []
        emitted: list[tuple[str, dict[str, str]]] = []
        runner = self._runner()
        runner._print_line = printed.append  # type: ignore[attr-defined]
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )

        runner._print_command(["echo", "hello world"])

        self.assertTrue(printed)
        self.assertIn("Command: echo 'hello world'", printed[0])
        self.assertEqual(
            emitted,
            [
                ("log", {"message": "Command: echo 'hello world'"}),
                ("command_started", {"command": "Command: echo 'hello world'"}),
            ],
        )

    def test_system_step_runs_full_pacman_upgrade(self) -> None:
        runner = self._runner(_plan(_system("linux"), _system("mesa")))
        calls: list[tuple[HelperRequest, dict[str, object]]] = []
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._run_privileged = lambda request, **kwargs: (  # type: ignore[method-assign]
            calls.append((request, kwargs))
            or CommandRunResult(True, "")
        )

        result = runner._run_backend_step(PacmanBackend())

        self.assertTrue(result.success)
        self.assertEqual(result.message, "")
        self.assertEqual(calls[0][0].action, HelperAction.RUN_SYSTEM_UPDATE)
        self.assertIsNone(calls[0][0].package_names)
        self.assertEqual(calls[0][1]["failure_message"], "System update failed.")

    def test_system_step_does_not_pass_selected_packages_to_pacman(self) -> None:
        runner = self._runner(_plan(_system("linux"), _system("mesa")))
        requests: list[HelperRequest] = []
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            requests.append(request) or CommandRunResult(True, "")
        )

        result = runner._run_backend_step(PacmanBackend())

        self.assertTrue(result.success)
        self.assertIsNone(requests[0].package_names)
        self.assertEqual(
            requests[0].expected_versions,
            {"linux": "2.0-1", "mesa": "2.0-1"},
        )

    def test_system_step_requires_confirmation_when_manifest_changes(self) -> None:
        runner = self._runner(_plan(_system("linux")))
        requests: list[HelperRequest] = []
        decisions: list[dict[str, object]] = []
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._interaction = types.SimpleNamespace(
            request_question=lambda payload: decisions.append(payload) or True
        )
        runner._run_command = lambda _command, **_kwargs: CommandRunResult(  # type: ignore[method-assign]
            True,
            payload={"output": "linux 2.0-1 -> 2.1-1\nglibc 1.0-1 -> 2.0-1"},
        )
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            requests.append(request) or CommandRunResult(True)
        )

        result = runner._run_backend_step(PacmanBackend())

        self.assertTrue(result.success)
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            requests[0].expected_versions,
            {"linux": "2.1-1", "glibc": "2.0-1"},
        )
        self.assertEqual(decisions[0]["question_type"], "transaction_change")

    def test_system_step_succeeds_without_change_when_no_updates_remain(self) -> None:
        runner = self._runner(_plan(_system("linux")))
        requests: list[HelperRequest] = []
        decisions: list[dict[str, object]] = []
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._interaction = types.SimpleNamespace(
            request_question=lambda payload: decisions.append(payload) or True
        )
        runner._run_command = lambda _command, **_kwargs: CommandRunResult(  # type: ignore[method-assign]
            True,
            payload={"output": ""},
        )
        runner._run_privileged = lambda request, **_kwargs: (  # type: ignore[method-assign]
            requests.append(request) or CommandRunResult(True)
        )

        result = runner._run_backend_step(PacmanBackend())

        self.assertTrue(result.success)
        self.assertFalse(result.changed)
        self.assertEqual(len(requests), 0)
        self.assertEqual(decisions, [])

    def test_user_flatpak_step_skips_refs_that_are_no_longer_updates(self) -> None:
        runner = self._runner(
            _plan(_flatpak("app/org.kde.Krita/x86_64/stable", "user"))
        )
        commands: list[list[str]] = []
        decisions: list[dict[str, object]] = []
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._interaction = types.SimpleNamespace(
            request_question=lambda payload: decisions.append(payload) or True
        )
        runner._run_command = lambda command, **_kwargs: (  # type: ignore[method-assign]
            commands.append(command)
            or CommandRunResult(True, payload={"output": ""})
        )

        result = runner._run_backend_step(FlatpakBackend())

        self.assertTrue(result.success)
        self.assertFalse(result.changed)
        self.assertEqual(len(commands), 1)
        self.assertIn("remote-ls", commands[0])
        self.assertEqual(decisions, [])

    def test_system_step_failure_uses_system_transaction_outcome(self) -> None:
        runner = self._runner(_plan(_system("linux")))
        runner._print_banner = lambda: None  # type: ignore[method-assign]
        runner._print_summary = lambda *, success: None  # type: ignore[method-assign]
        runner._print_footer = (  # type: ignore[method-assign]
            lambda *, success, message, refresh_expected=True: None
        )
        runner._print_line = lambda _line: None  # type: ignore[method-assign]

        class _FailingSystemBackend:
            step_key = "system"
            exit_code = 2
            outcome = BatchOutcome.SYSTEM_TRANSACTION_FAILED.value

            def should_run(self, _plan: UpdatePlan) -> bool:
                return True

            def label(self, _context) -> str:  # noqa: ANN001
                return "Pacman"

            def start_message(self, _context) -> str:  # noqa: ANN001
                return "Now running a full system upgrade with pacman."

            def run(self, _context) -> BackendRunResult:  # noqa: ANN001
                return BackendRunResult(False, "could not satisfy dependencies")

        runner._backends = [_FailingSystemBackend()]
        emitted: list[tuple[str, dict[str, object]]] = []
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )

        exit_code = runner.run()

        self.assertEqual(exit_code, 2)
        self.assertEqual(emitted[-1][0], BatchEventType.BATCH_COMPLETED.value)
        self.assertEqual(emitted[-1][1]["outcome"], BatchOutcome.SYSTEM_TRANSACTION_FAILED.value)

    def test_independent_backend_failure_does_not_skip_later_backend(self) -> None:
        calls: list[str] = []

        class _Backend:
            exit_code = 3
            outcome = BatchOutcome.FAILED.value

            def __init__(self, step_key: str, result: BackendRunResult) -> None:
                self.step_key = step_key
                self._result = result

            def should_run(self, _plan: UpdatePlan) -> bool:
                return True

            def label(self, _context) -> str:  # noqa: ANN001
                return self.step_key

            def start_message(self, _context) -> str:  # noqa: ANN001
                return self.step_key

            def run(self, _context) -> BackendRunResult:  # noqa: ANN001
                calls.append(self.step_key)
                return self._result

        runner = self._runner(_plan(_aur("example"), _flatpak("app/org.example.App/x86_64/stable")))
        runner._backends = [
            _Backend("aur", BackendRunResult(False, "AUR failed")),
            _Backend("flatpak", BackendRunResult(True, changed=True)),
        ]
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._print_banner = lambda: None  # type: ignore[method-assign]
        runner._print_footer = lambda **_kwargs: None  # type: ignore[method-assign]
        runner._print_summary = lambda **_kwargs: None  # type: ignore[method-assign]
        emitted: list[tuple[str, dict[str, object]]] = []
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )

        exit_code = runner.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["aur", "flatpak"])
        self.assertEqual(emitted[-1][1]["outcome"], BatchOutcome.PARTIAL_SUCCESS.value)
        self.assertEqual(emitted[-1][1]["failed"], ["AUR"])
        self.assertEqual(emitted[-1][1]["completed"], ["Flatpak"])

    def test_run_emits_no_changes_when_all_aur_reviews_are_skipped(self) -> None:
        exit_code, emitted, printed = self._run_static_aur_backend(
            _StaticAurBackend(
                result=BackendRunResult(
                    True,
                    "AUR updates were skipped after PKGBUILD review.",
                    changed=False,
                    incomplete=True,
                )
            )
        )

        completed = emitted[-1]
        self.assertEqual(exit_code, 0)
        self.assertEqual(completed[0], BatchEventType.BATCH_COMPLETED.value)
        self.assertTrue(completed[1]["success"])
        self.assertEqual(completed[1]["outcome"], BatchOutcome.NO_CHANGES.value)
        self.assertEqual(completed[1]["message"], "No selected updates were installed.")
        self.assertEqual(completed[1]["completed"], [])
        self.assertEqual(completed[1]["incomplete"], ["AUR"])
        self.assertEqual(completed[1]["failed"], [])
        self.assertEqual(completed[1]["not_executed"], [])
        self.assertIn("No package status refresh is required.", printed)
        self.assertNotIn("ArchUpdater will refresh package status automatically.", printed)

    def test_run_emits_no_changes_when_a_successful_transaction_evaporates(self) -> None:
        exit_code, emitted, printed = self._run_static_aur_backend(
            _StaticAurBackend(
                result=BackendRunResult(
                    True,
                    "No reviewed updates remain available.",
                    changed=False,
                )
            )
        )

        completed = emitted[-1]
        self.assertEqual(exit_code, 0)
        self.assertEqual(completed[1]["outcome"], BatchOutcome.NO_CHANGES.value)
        self.assertIn("No package status refresh is required.", printed)

    def test_run_emits_partial_success_when_some_aur_updates_changed(self) -> None:
        exit_code, emitted, printed = self._run_static_aur_backend(
            _StaticAurBackend(
                result=BackendRunResult(
                    True,
                    "AUR update completed with skipped packages.",
                    changed=True,
                    incomplete=True,
                )
            )
        )

        completed = emitted[-1]
        self.assertEqual(exit_code, 0)
        self.assertEqual(completed[0], BatchEventType.BATCH_COMPLETED.value)
        self.assertTrue(completed[1]["success"])
        self.assertEqual(completed[1]["outcome"], BatchOutcome.PARTIAL_SUCCESS.value)
        self.assertEqual(
            completed[1]["message"],
            "Selected updates completed with incomplete or failed steps.",
        )
        self.assertEqual(completed[1]["completed"], [])
        self.assertEqual(completed[1]["incomplete"], ["AUR"])
        self.assertEqual(completed[1]["failed"], [])
        self.assertEqual(completed[1]["not_executed"], [])
        self.assertIn("ArchUpdater will refresh package status automatically.", printed)

    def test_run_maps_batch_cancellation_to_cancelled_outcome(self) -> None:
        exit_code, emitted, _printed = self._run_static_aur_backend(
            _StaticAurBackend(error=BatchCancelled())
        )

        completed = emitted[-1]
        self.assertEqual(exit_code, 130)
        self.assertEqual(completed[0], BatchEventType.BATCH_COMPLETED.value)
        self.assertFalse(completed[1]["success"])
        self.assertEqual(completed[1]["outcome"], BatchOutcome.CANCELLED.value)
        self.assertEqual(completed[1]["incomplete"], ["AUR"])
        self.assertEqual(completed[1]["not_executed"], [])

    def test_no_changes_footer_does_not_claim_a_refresh(self) -> None:
        printed: list[str] = []
        runner = self._runner(_plan(_aur("spotify")))
        runner._print_line = printed.append  # type: ignore[method-assign]

        runner._print_footer(
            success=True,
            message="No selected updates were installed.",
            refresh_expected=False,
        )

        joined = "\n".join(printed)
        self.assertIn("No package status refresh is required.", joined)
        self.assertNotIn("ArchUpdater will refresh package status automatically.", joined)

    def test_partial_success_footer_still_claims_a_refresh(self) -> None:
        printed: list[str] = []
        runner = self._runner(_plan(_aur("spotify")))
        runner._print_line = printed.append  # type: ignore[method-assign]

        runner._print_footer(
            success=True,
            message="Selected updates completed with skipped items.",
            refresh_expected=True,
        )

        joined = "\n".join(printed)
        self.assertIn("ArchUpdater will refresh package status automatically.", joined)

    def test_run_authorizes_privileged_session_before_update_steps(self) -> None:
        runner = self._runner(_plan(_aur("spotify")))
        calls: list[str] = []
        runner._print_banner = lambda: None  # type: ignore[method-assign]
        runner._print_summary = lambda *, success: None  # type: ignore[method-assign]
        runner._print_footer = (  # type: ignore[method-assign]
            lambda *, success, message, refresh_expected=True: None
        )
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._privileged_helper = types.SimpleNamespace(
            authorize=lambda: calls.append("authorize") or CommandRunResult(True, ""),
            run=lambda _request, *, failure_message: CommandRunResult(True, ""),
            close=lambda: calls.append("close"),
        )

        class _SuccessfulAurBackend:
            step_key = "aur"
            exit_code = 3
            outcome = BatchOutcome.FAILED.value

            def should_run(self, _plan: UpdatePlan) -> bool:
                return True

            def label(self, _context) -> str:  # noqa: ANN001
                return "AUR"

            def start_message(self, _context) -> str:  # noqa: ANN001
                return "Now installing the selected AUR updates with paru."

            def run(self, _context) -> BackendRunResult:  # noqa: ANN001
                calls.append("backend")
                return BackendRunResult(True, "")

        runner._backends = [_SuccessfulAurBackend()]
        runner._events = types.SimpleNamespace(emit=lambda _event_type, **_payload: None)

        exit_code = runner.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["authorize", "backend", "close"])

    def test_run_privileged_delegates_to_helper_invoker(self) -> None:
        runner = self._runner()
        calls: list[tuple[HelperRequest, str]] = []
        runner._privileged_helper = types.SimpleNamespace(
            run=lambda request, *, failure_message: (
                calls.append((request, failure_message)) or CommandRunResult(True, "")
            )
        )
        request = HelperRequest(action=HelperAction.RUN_SYSTEM_UPDATE)

        result = runner._run_privileged(
            request,
            failure_message="System update failed.",
        )

        self.assertTrue(result.success)
        self.assertEqual(calls, [(request, "System update failed.")])

    def test_command_failure_message_detects_pacman_database_error(self) -> None:
        runner = self._runner()

        message = runner._command_failure_message(
            failure_message="AUR update failed.",
            return_code=1,
            output="error: database 'cachyos' is not valid (invalid or corrupted database (PGP signature))",
        )

        self.assertIn("Pacman package databases are not valid", message)
        self.assertIn("exit code 1", message)
        self.assertIn("database 'cachyos' is not valid", message)

    def test_fail_can_emit_auth_cancelled_outcome(self) -> None:
        runner = self._runner(_plan(_system("linux")))
        emitted: list[tuple[str, dict[str, object]]] = []
        runner._print_line = lambda _line: None  # type: ignore[method-assign]
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )

        exit_code = runner._fail(
            "Authentication cancelled.",
            exit_code=130,
            outcome=BatchOutcome.AUTH_CANCELLED.value,
        )

        self.assertEqual(exit_code, 130)
        self.assertEqual(emitted[-1][0], BatchEventType.BATCH_COMPLETED.value)
        self.assertEqual(emitted[-1][1]["outcome"], "auth_cancelled")

    def test_run_maps_authentication_cancelled_exception_to_auth_outcome(self) -> None:
        runner = self._runner(_plan(_system("linux")))
        runner._print_banner = lambda: None  # type: ignore[method-assign]
        runner._print_summary = lambda *, success: None  # type: ignore[method-assign]
        runner._print_footer = (  # type: ignore[method-assign]
            lambda *, success, message, refresh_expected=True: None
        )
        runner._print_line = lambda _line: None  # type: ignore[method-assign]

        class _AuthCancelledBackend:
            step_key = "system"
            exit_code = 2
            outcome = BatchOutcome.SYSTEM_TRANSACTION_FAILED.value

            def should_run(self, _plan: UpdatePlan) -> bool:
                return True

            def label(self, _context) -> str:  # noqa: ANN001
                return "Pacman"

            def start_message(self, _context) -> str:  # noqa: ANN001
                return "Now running a full system upgrade with pacman."

            def run(self, _context) -> BackendRunResult:  # noqa: ANN001
                raise BatchAuthenticationCancelled("Password is required to continue.")

        emitted: list[tuple[str, dict[str, object]]] = []
        runner._backends = [_AuthCancelledBackend()]
        runner._events = types.SimpleNamespace(
            emit=lambda event_type, **payload: emitted.append((event_type, payload))
        )

        exit_code = runner.run()

        self.assertEqual(exit_code, 130)
        self.assertEqual(emitted[-1][0], BatchEventType.BATCH_COMPLETED.value)
        self.assertEqual(emitted[-1][1]["message"], "Password is required to continue.")
        self.assertEqual(emitted[-1][1]["outcome"], BatchOutcome.AUTH_CANCELLED.value)

if __name__ == "__main__":
    unittest.main()
