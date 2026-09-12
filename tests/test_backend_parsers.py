from __future__ import annotations

import os
import re
import time
import json
from datetime import datetime
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import FlatpakRefKind, UpdateSource
from archupdater.domain.command_log import CommandLogEntry
from archupdater.domain.package_metadata import (
    AurPackageMetadata,
    FlatpakPackageMetadata,
    SystemPackageMetadata,
)
from archupdater.domain.packages import PackageUpdate
from archupdater.domain.aur import AurVcsSource
from archupdater.domain.update_plan import UpdatePlanItem
from archupdater.services.aur import (
    AurPkgbuildFetchError,
    AurUpdateService,
)
from archupdater.services.command_runner import CommandRunner
from archupdater.services.firmware import FirmwareUpdateService
from archupdater.services.flatpak import FlatpakUpdateService
from archupdater.services.pacman import PacmanServiceError, PacmanUpdateService


class BackendParserTests(unittest.TestCase):
    def setUp(self) -> None:
        runner = CommandRunner()
        self.pacman = PacmanUpdateService(runner=runner)
        self.flatpak = FlatpakUpdateService(runner=runner)
        self.aur = AurUpdateService(runner=runner)
        self.firmware = FirmwareUpdateService(runner=runner)

    def test_pacman_parse_update_lines_ignores_non_matching_lines(self) -> None:
        raw = "\n".join(
            [
                "linux 6.9.1.arch1-1 -> 6.9.2.arch1-1",
                "warning: transient issue",
                "mesa 24.0.7-1 -> 24.0.8-1",
                "",
            ]
        )

        packages, _unparsed = self.pacman._parse_update_output(raw)

        self.assertEqual([package.name for package in packages], ["linux", "mesa"])
        self.assertTrue(all(package.source is UpdateSource.SYSTEM for package in packages))
        _packages, unparsed_lines = self.pacman._parse_update_output(raw)
        self.assertEqual(unparsed_lines, ["warning: transient issue"])

    def test_aur_parse_update_output_reports_non_matching_lines(self) -> None:
        packages, unparsed_lines = self.aur._parse_update_output(
            "paru-bin 2.0-1 -> 2.1-1\nwarning: unexpected\n"
        )

        self.assertEqual([package.name for package in packages], ["paru-bin"])
        self.assertEqual(unparsed_lines, ["warning: unexpected"])

    def test_aur_parse_update_output_accepts_repository_prefixed_names(self) -> None:
        packages, unparsed_lines = self.aur._parse_update_output(
            "\x1b[1maur/paru-bin\x1b[0m 2.0-1 -> 2.1-1\n"
            "chaotic-aur/example-helper 1.0-1 -> 1.1-1\n"
        )

        self.assertEqual([package.name for package in packages], ["paru-bin", "example-helper"])
        self.assertEqual([package.backend_id for package in packages], ["paru-bin", "example-helper"])
        self.assertEqual(unparsed_lines, [])

    def test_aur_latest_commit_is_a_dynamic_version(self) -> None:
        package = self.aur._parse_update_lines(
            "nct6687d-dkms-git r197.cd73522-1 -> latest-commit"
        )[0]

        metadata = package.source_metadata
        self.assertIsInstance(metadata, AurPackageMetadata)
        self.assertTrue(metadata.dynamic_version)
        item = UpdatePlanItem.from_package(package)
        self.assertEqual(item.current_version, "r197.cd73522-1")
        self.assertEqual(item.expected_version, "latest-commit")
        self.assertTrue(item.dynamic_version)

    def test_aur_vcs_receipt_suppresses_only_unchanged_remote_commit(self) -> None:
        source = AurVcsSource(
            "example-git",
            "https://example.invalid/example.git",
            None,
            "a" * 40,
        )
        with tempfile.TemporaryDirectory() as directory:
            service = AurUpdateService(
                runner=CommandRunner(),
                vcs_state_path=Path(directory) / "aur-vcs.json",
            )
            service.record_vcs_install("example-git", "r2.aaaaaaa-1", (source,))
            packages = service._parse_update_lines(
                "example-git r2.aaaaaaa-1 -> latest-commit"
            )
            log = CommandLogEntry(
                command=["git", "ls-remote"],
                exit_code=0,
                stdout="",
                stderr="",
                started_at=datetime(2026, 8, 2),
                duration_ms=1,
            )

            with patch.object(
                AurUpdateService,
                "_remote_vcs_commit",
                return_value=("a" * 40, log),
            ):
                filtered = service._filter_stale_dynamic_updates(
                    packages,
                    local_output="Name : example-git\nVersion : r2.aaaaaaa-1\n",
                    logs=[],
                )
            self.assertEqual(filtered, [])

            with patch.object(
                AurUpdateService,
                "_remote_vcs_commit",
                return_value=("b" * 40, log),
            ):
                filtered = service._filter_stale_dynamic_updates(
                    packages,
                    local_output="Name : example-git\nVersion : r2.aaaaaaa-1\n",
                    logs=[],
                )
            self.assertEqual(filtered, packages)

    def test_aur_remote_vcs_commit_handles_empty_and_invalid_output(self) -> None:
        for exit_code in (0, 128, -124):
            for output in ("", "\n", " \t\n", "invalid\tHEAD\n"):
                with self.subTest(exit_code=exit_code, output=output):
                    log = CommandLogEntry(
                        command=["git", "ls-remote"],
                        exit_code=exit_code,
                        stdout=output,
                        stderr="Git diagnostic",
                        started_at=datetime.now(),
                        duration_ms=1,
                    )
                    with patch.object(CommandRunner, "run", return_value=log):
                        commit, actual_log = self.aur._remote_vcs_commit(
                            "https://example.invalid/repo.git", None
                        )
                    self.assertEqual(commit, "")
                    self.assertIs(actual_log, log)

    def test_aur_remote_vcs_commit_requires_successful_git_result(self) -> None:
        for exit_code in (0, 128):
            with self.subTest(exit_code=exit_code):
                log = CommandLogEntry(
                    command=["git", "ls-remote"],
                    exit_code=exit_code,
                    stdout=f"{'A' * 40}\tHEAD\n",
                    stderr="",
                    started_at=datetime.now(),
                    duration_ms=1,
                )
                with patch.object(CommandRunner, "run", return_value=log):
                    commit, _log = self.aur._remote_vcs_commit(
                        "https://example.invalid/repo.git", None
                    )
                self.assertEqual(commit, "a" * 40 if exit_code == 0 else "")

    def test_aur_vcs_sources_include_only_common_and_native_architecture(self) -> None:
        srcinfo = "\n".join(
            (
                "source = common::git+https://example.invalid/common.git",
                "source_x86_64 = amd::git+https://example.invalid/amd.git",
                "source_aarch64 = arm::git+https://example.invalid/arm.git",
            )
        )
        for architecture, native_source in (("x86_64", "amd"), ("aarch64", "arm")):
            with self.subTest(architecture=architecture):
                with (
                    patch("archupdater.services.aur.platform.machine", return_value=architecture),
                    patch.object(
                        AurUpdateService, "_remote_vcs_commit", return_value=("a" * 40, None)
                    ) as resolve_commit,
                ):
                    sources = self.aur._resolve_vcs_sources(srcinfo)
                self.assertEqual([source.name for source in sources], ["common", native_source])
                self.assertEqual(
                    [call.args[0] for call in resolve_commit.call_args_list],
                    [
                        "https://example.invalid/common.git",
                        f"https://example.invalid/{native_source}.git",
                    ],
                )

    def test_aur_vcs_state_ignores_receipts_from_older_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "aur-vcs.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "packages": {
                            "example-git": {
                                "version": "r1.aaaaaaa-1",
                                "sources": [],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            service = AurUpdateService(runner=CommandRunner(), vcs_state_path=state_path)

            self.assertEqual(service._load_vcs_state()["packages"], {})

    def test_aur_rpc_dates_are_formatted_in_utc(self) -> None:
        self.assertEqual(self.aur._format_timestamp(86_399), "1970-01-01")

    def test_pacman_load_metadata_uses_pacman_cli_details(self) -> None:
        class _Log:
            def __init__(self, stdout: str) -> None:
                self.exit_code = 0
                self.stdout = stdout
                self.stderr = ""

        class _Runner:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def run(self, command, *, timeout_seconds=None):  # noqa: ANN001
                self.commands.append(command)
                if command[:2] == ["pacman", "-Si"]:
                    return _Log(
                        "\n".join(
                            [
                                "Repository      : core",
                                "Name            : linux",
                                "Description     : Kernel",
                                "Architecture    : x86_64",
                                "URL             : https://archlinux.org",
                                "Download Size   : 120.00 MiB",
                                "Installed Size  : 130.00 MiB",
                                "Depends On      : coreutils  kmod",
                                "Licenses        : GPL-2.0-only",
                                "",
                            ]
                        )
                    )
                return _Log(
                    "\n".join(
                        [
                            "Name            : linux",
                            "Installed Size  : 110.00 MiB",
                            "Install Reason  : Explicitly installed",
                            "Required By     : None",
                            "",
                        ]
                    )
                )

        packages, _unparsed = self.pacman._parse_update_output(
            "linux 6.9.1.arch1-1 -> 6.9.2.arch1-1"
        )
        runner = _Runner()
        service = PacmanUpdateService(runner=runner)  # type: ignore[arg-type]

        service._load_metadata(packages, logs=[], ignore_patterns=[])

        metadata = packages[0].source_metadata
        self.assertIsInstance(metadata, SystemPackageMetadata)
        self.assertEqual(metadata.repository, "core")
        self.assertEqual(packages[0].size_diff, "+20.00 MiB")
        self.assertEqual(runner.commands, [["pacman", "-Si", "linux"], ["pacman", "-Qi", "linux"]])

    def test_pacman_load_metadata_keeps_packages_when_cli_metadata_is_empty(self) -> None:
        packages, _unparsed = self.pacman._parse_update_output(
            "linux 6.9.1.arch1-1 -> 6.9.2.arch1-1"
        )

        class _Runner:
            def run(self, command, *, timeout_seconds=None):  # noqa: ANN001
                return type("Log", (), {"exit_code": 1, "stdout": "", "stderr": "missing"})()

        service = PacmanUpdateService(runner=_Runner())  # type: ignore[arg-type]

        service._load_metadata(packages, logs=[], ignore_patterns=[])

        self.assertEqual(packages[0].name, "linux")

    def test_pacman_checkupdates_exit_2_means_no_updates(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self.calls: list[tuple[list[str], dict[str, str] | None]] = []

            def run(self, command, *, timeout_seconds=None, extra_env=None):  # noqa: ANN001
                self.calls.append((command, extra_env))
                if command[0] == "pacman":
                    return CommandLogEntry(
                        command=command,
                        exit_code=1,
                        stdout="",
                        stderr="",
                        started_at=datetime(2026, 5, 27),
                        duration_ms=1,
                    )
                return CommandLogEntry(
                    command=command,
                    exit_code=2,
                    stdout="",
                    stderr="",
                    started_at=datetime(2026, 5, 27),
                    duration_ms=1,
                )

        runner = _Runner()
        service = PacmanUpdateService(runner=runner)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmp:
            old_cache_home = os.environ.get("XDG_CACHE_HOME")
            os.environ["XDG_CACHE_HOME"] = tmp
            try:
                with patch.object(PacmanUpdateService, "_has_command", return_value=True):
                    result = service.check_updates()
            finally:
                if old_cache_home is None:
                    os.environ.pop("XDG_CACHE_HOME", None)
                else:
                    os.environ["XDG_CACHE_HOME"] = old_cache_home

        self.assertEqual(result.packages, [])
        self.assertEqual(runner.calls[0][0], ["checkupdates"])
        self.assertIsNotNone(runner.calls[0][1])
        checkupdates_env = runner.calls[0][1] or {}
        self.assertIn("CHECKUPDATES_DB", checkupdates_env)
        checkupdates_db = Path(checkupdates_env["CHECKUPDATES_DB"])
        self.assertTrue(checkupdates_db.name.startswith("run-"))
        self.assertTrue(str(checkupdates_db.parent).endswith("archupdater/checkupdates-db-runs"))
        self.assertEqual(
            runner.calls[1][0],
            [
                "pacman",
                "-Qu",
                "--dbpath",
                str(checkupdates_db),
                "--color",
                "never",
            ],
        )
        self.assertFalse(checkupdates_db.exists())

    def test_pacman_check_includes_ignorepkg_updates_from_temporary_database(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self.checkupdates_db: Path | None = None

            def run(self, command, *, timeout_seconds=None, extra_env=None):  # noqa: ANN001
                if command == ["checkupdates"]:
                    self.checkupdates_db = Path(extra_env["CHECKUPDATES_DB"])
                    return CommandLogEntry(
                        command=command,
                        exit_code=2,
                        stdout="",
                        stderr="",
                        started_at=datetime(2026, 5, 27),
                        duration_ms=1,
                    )
                if command[:2] == ["pacman", "-Qu"]:
                    return CommandLogEntry(
                        command=command,
                        exit_code=0,
                        stdout="linux 6.9.1.arch1-1 -> 6.9.2.arch1-1 [ignored]\n",
                        stderr="",
                        started_at=datetime(2026, 5, 27),
                        duration_ms=1,
                    )
                if command == ["pacman-conf", "IgnorePkg"]:
                    return CommandLogEntry(
                        command=command,
                        exit_code=0,
                        stdout="linux\n",
                        stderr="",
                        started_at=datetime(2026, 5, 27),
                        duration_ms=1,
                    )
                return CommandLogEntry(
                    command=command,
                    exit_code=1,
                    stdout="",
                    stderr="metadata unavailable",
                    started_at=datetime(2026, 5, 27),
                    duration_ms=1,
                )

        runner = _Runner()
        service = PacmanUpdateService(runner=runner)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmp:
            old_cache_home = os.environ.get("XDG_CACHE_HOME")
            os.environ["XDG_CACHE_HOME"] = tmp
            try:
                with patch.object(PacmanUpdateService, "_has_command", return_value=True):
                    result = service.check_updates()
            finally:
                if old_cache_home is None:
                    os.environ.pop("XDG_CACHE_HOME", None)
                else:
                    os.environ["XDG_CACHE_HOME"] = old_cache_home

        self.assertEqual([package.name for package in result.packages], ["linux"])
        package = result.packages[0]
        self.assertTrue(package.blocked_by_config)
        self.assertTrue(package.selection_locked)
        self.assertFalse(package.selected)
        self.assertEqual(package.blocked_reason, "Blocked by pacman.conf")
        self.assertIsNotNone(runner.checkupdates_db)
        assert runner.checkupdates_db is not None
        self.assertFalse(runner.checkupdates_db.exists())

    def test_pacman_metadata_queries_use_the_refreshed_temporary_database(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self.checkupdates_db: Path | None = None
                self.metadata_commands: list[list[str]] = []

            def run(self, command, *, timeout_seconds=None, extra_env=None):  # noqa: ANN001
                if command == ["checkupdates"]:
                    self.checkupdates_db = Path(extra_env["CHECKUPDATES_DB"])
                    return CommandLogEntry(
                        command=command,
                        exit_code=0,
                        stdout="linux 1.0-1 -> 1.1-1\n",
                        stderr="",
                        started_at=datetime(2026, 5, 27),
                        duration_ms=1,
                    )
                if command[:2] == ["pacman", "-Qu"]:
                    return CommandLogEntry(
                        command=command,
                        exit_code=0,
                        stdout="linux 1.0-1 -> 1.1-1\n",
                        stderr="",
                        started_at=datetime(2026, 5, 27),
                        duration_ms=1,
                    )
                if command == ["pacman-conf", "IgnorePkg"]:
                    return CommandLogEntry(
                        command=command,
                        exit_code=0,
                        stdout="",
                        stderr="",
                        started_at=datetime(2026, 5, 27),
                        duration_ms=1,
                    )
                self.metadata_commands.append(command)
                assert self.checkupdates_db is not None
                assert self.checkupdates_db.exists()
                return CommandLogEntry(
                    command=command,
                    exit_code=1,
                    stdout="",
                    stderr="metadata unavailable",
                    started_at=datetime(2026, 5, 27),
                    duration_ms=1,
                )

        runner = _Runner()
        service = PacmanUpdateService(runner=runner)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmp:
            old_cache_home = os.environ.get("XDG_CACHE_HOME")
            os.environ["XDG_CACHE_HOME"] = tmp
            try:
                with patch.object(PacmanUpdateService, "_has_command", return_value=True):
                    result = service.check_updates()
            finally:
                if old_cache_home is None:
                    os.environ.pop("XDG_CACHE_HOME", None)
                else:
                    os.environ["XDG_CACHE_HOME"] = old_cache_home

        self.assertEqual([package.name for package in result.packages], ["linux"])
        assert runner.checkupdates_db is not None
        expected_database_arguments = [
            "--dbpath",
            str(runner.checkupdates_db),
            "--color",
            "never",
        ]
        self.assertEqual(
            runner.metadata_commands,
            [
                ["pacman", "-Si", *expected_database_arguments, "linux"],
                ["pacman", "-Qi", *expected_database_arguments, "linux"],
            ],
        )
        self.assertFalse(runner.checkupdates_db.exists())

    def test_pacman_checkupdates_database_is_removed_when_refresh_fails(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self.checkupdates_db: Path | None = None

            def run(self, command, *, timeout_seconds=None, extra_env=None):  # noqa: ANN001
                self.checkupdates_db = Path(extra_env["CHECKUPDATES_DB"])
                self.assertTrue(self.checkupdates_db.exists())
                return CommandLogEntry(
                    command=command,
                    exit_code=1,
                    stdout="",
                    stderr="temporary sync failure",
                    started_at=datetime(2026, 5, 27),
                    duration_ms=1,
                )

            def assertTrue(self, value: bool) -> None:
                if not value:
                    raise AssertionError("expected truthy value")

        runner = _Runner()
        service = PacmanUpdateService(runner=runner)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmp:
            old_cache_home = os.environ.get("XDG_CACHE_HOME")
            os.environ["XDG_CACHE_HOME"] = tmp
            try:
                with patch.object(PacmanUpdateService, "_has_command", return_value=True):
                    with self.assertRaises(PacmanServiceError):
                        service.check_updates()
            finally:
                if old_cache_home is None:
                    os.environ.pop("XDG_CACHE_HOME", None)
                else:
                    os.environ["XDG_CACHE_HOME"] = old_cache_home

        self.assertIsNotNone(runner.checkupdates_db)
        assert runner.checkupdates_db is not None
        self.assertFalse(runner.checkupdates_db.exists())

    def test_pacman_checkupdates_database_prunes_stale_crash_leftovers(self) -> None:
        service = PacmanUpdateService(runner=self.pacman.runner)

        with tempfile.TemporaryDirectory() as tmp:
            old_cache_home = os.environ.get("XDG_CACHE_HOME")
            os.environ["XDG_CACHE_HOME"] = tmp
            try:
                root = service.checkupdates_workspace.root_path()
                root.mkdir(parents=True)
                stale = root / "run-stale"
                stale.mkdir()
                fresh = root / "run-fresh"
                fresh.mkdir()
                old_timestamp = time.time() - service.checkupdates_workspace.stale_seconds - 60
                os.utime(stale, (old_timestamp, old_timestamp))

                created = service._fresh_checkupdates_db_path()

                self.assertFalse(stale.exists())
                self.assertTrue(fresh.exists())
                self.assertTrue(created.exists())
                service._cleanup_checkupdates_db_path(created)
            finally:
                if old_cache_home is None:
                    os.environ.pop("XDG_CACHE_HOME", None)
                else:
                    os.environ["XDG_CACHE_HOME"] = old_cache_home

    def test_pacman_local_db_query_uses_pacman_qu(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self.calls: list[tuple[list[str], dict[str, str] | None]] = []

            def run(self, command, *, timeout_seconds=None, extra_env=None):  # noqa: ANN001
                self.calls.append((command, extra_env))
                return CommandLogEntry(
                    command=command,
                    exit_code=0,
                    stdout="linux 6.9.1.arch1-1 -> 6.9.2.arch1-1\n",
                    stderr="",
                    started_at=datetime(2026, 5, 27),
                    duration_ms=1,
                )

        runner = _Runner()
        service = PacmanUpdateService(runner=runner)  # type: ignore[arg-type]

        result = service.check_updates(use_local_db=True)

        self.assertEqual([package.name for package in result.packages], ["linux"])
        self.assertEqual(runner.calls[0], (["pacman", "-Qu"], None))

    def test_aur_metadata_combines_helper_local_and_rpc_details(self) -> None:
        packages = self.aur._parse_update_lines("paru-bin 2.0-1 -> 2.1-1")
        helper_metadata = "\n".join(
            [
                "Name            : paru-bin",
                "Repository      : aur",
                "Description     : AUR helper",
                "URL             : https://github.com/morganamilo/paru",
                "Installed Size  : 8.00 MiB",
                "Depends On      : pacman  git",
                "Make Deps       : rust",
                "",
            ]
        )
        local_metadata = "\n".join(
            [
                "Name            : paru-bin",
                "Installed Size  : 6.00 MiB",
                "",
            ]
        )

        self.aur._apply_metadata(packages, helper_metadata)
        self.aur._apply_local_metadata(packages, local_metadata)
        self.aur._apply_aur_rpc_metadata(
            packages,
            {
                "paru-bin": {
                    "Maintainer": "example",
                    "PackageBase": "paru",
                    "NumVotes": 123,
                    "Popularity": 4.56,
                    "OutOfDate": None,
                    "License": ["GPL-3.0-or-later"],
                    "CheckDepends": ["python-pytest"],
                }
            },
        )

        package = packages[0]
        metadata = package.source_metadata
        self.assertIsInstance(metadata, AurPackageMetadata)
        self.assertEqual(package.homepage, "https://github.com/morganamilo/paru")
        self.assertEqual(package.size_diff, "+2.00 MiB")
        self.assertEqual(metadata.maintainer, "example")
        self.assertEqual(metadata.package_base, "paru")
        self.assertEqual(metadata.votes, "123")
        self.assertEqual(metadata.popularity, "4.56")
        self.assertEqual(metadata.out_of_date, "No")
        self.assertEqual(metadata.licenses, ["GPL-3.0-or-later"])
        self.assertEqual(package.dependencies, ["pacman", "git"])
        self.assertEqual(metadata.make_dependencies, ["rust"])
        self.assertEqual(metadata.check_dependencies, ["python-pytest"])

    def test_aur_check_excludes_updates_without_resolved_package_base(self) -> None:
        class _Log:
            def __init__(self, stdout: str = "") -> None:
                self.exit_code = 0
                self.stdout = stdout
                self.stderr = ""

        class _Runner:
            def run(self, command, **_kwargs):  # noqa: ANN001, ANN201
                if "-Qua" in command:
                    return _Log("example 1.0-1 -> 2.0-1\n")
                if "-Si" in command:
                    return _Log("Name : example\nRepository : aur\n")
                return _Log("Name : example\nInstalled Size : 1 MiB\n")

        service = AurUpdateService(runner=_Runner())  # type: ignore[arg-type]
        with (
            patch.object(AurUpdateService, "detect_helper", return_value="paru"),
            patch.object(AurUpdateService, "_fetch_aur_rpc_metadata", return_value={}),
        ):
            result = service.check_updates()

        self.assertEqual(result.packages, [])
        self.assertTrue(any("package base" in warning for warning in result.warnings))

    def test_pacman_metadata_keeps_multiline_optional_dependencies_separate(self) -> None:
        sections = self.pacman._parse_sections(
            "\n".join(
                [
                    "Name            : git",
                    "Optional Deps   : git-zsh-completion: zsh completion",
                    "                  tk: gitk and git gui",
                    "                  openssh: ssh transport",
                    "",
                ]
            )
        )

        self.assertEqual(
            self.pacman._split_metadata_list(sections[0]["Optional Deps"]),
            [
                "git-zsh-completion: zsh completion",
                "tk: gitk and git gui",
                "openssh: ssh transport",
            ],
        )

    def test_aur_metadata_keeps_multiline_optional_dependencies_separate(self) -> None:
        sections = self.aur._parse_sections(
            "\n".join(
                [
                    "Name            : example",
                    "Optional Deps   : first: first integration",
                    "                  second: second integration",
                    "",
                ]
            )
        )

        self.assertEqual(
            self.aur._split_metadata_list(sections[0]["Optional Deps"]),
            ["first: first integration", "second: second integration"],
        )

    def test_aur_pkgbuild_review_uses_package_base(self) -> None:
        class _PkgbuildAurUpdateService(AurUpdateService):
            def __init__(self, runner: CommandRunner) -> None:
                super().__init__(runner=runner)
                self.fetched: list[str] = []

            def _clone_checkout(self, package_base: str, checkout_path: Path) -> None:
                self.fetched.append(package_base)
                checkout_path.mkdir()
                (checkout_path / "PKGBUILD").write_text(
                    "pkgbase=foo\npkgname=(libfoo)\npkgver=1.0\npkgrel=1\n",
                    encoding="utf-8",
                )
                (checkout_path / ".SRCINFO").write_text(
                    "pkgbase = foo\n\tmakedepends = cmake\n"
                    "pkgname = libfoo\n\tdepends = libbar\n",
                    encoding="utf-8",
                )
                (checkout_path / "libfoo.install").write_text(
                    "post_install() { :; }\n",
                    encoding="utf-8",
                )
                subprocess.run(
                    ["git", "-C", str(checkout_path), "init", "-q"],
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", str(checkout_path), "add", "--all"],
                    check=True,
                )
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(checkout_path),
                        "-c",
                        "user.name=ArchUpdater Tests",
                        "-c",
                        "user.email=tests@example.invalid",
                        "commit",
                        "-qm",
                        "fixture",
                    ],
                    check=True,
                )

        service = _PkgbuildAurUpdateService(runner=CommandRunner())

        review = service.fetch_pkgbuild_review("libfoo", "foo")

        self.assertEqual(service.fetched, ["foo"])
        self.assertEqual(review.package_name, "libfoo")
        self.assertEqual(review.package_base, "foo")
        self.assertIn("pkgname=(libfoo)", review.pkgbuild)
        self.assertRegex(review.commit, r"^[0-9a-f]{40}$")
        self.assertRegex(review.digest, r"^[0-9a-f]{64}$")
        self.assertEqual(
            [reviewed_file.path for reviewed_file in review.files],
            [".SRCINFO", "PKGBUILD", "libfoo.install"],
        )
        self.assertIn("post_install", review.rendered_content())
        service.discard_pkgbuild_review(review)

    def test_aur_review_rejects_binary_tracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            subprocess.run(["git", "-C", str(checkout), "init", "-q"], check=True)
            (checkout / "PKGBUILD").write_text("pkgname=example\n", encoding="utf-8")
            (checkout / "payload.bin").write_bytes(b"text\0binary")
            subprocess.run(
                ["git", "-C", str(checkout), "add", "--all"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "-c",
                    "user.name=ArchUpdater Tests",
                    "-c",
                    "user.email=tests@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )

            with self.assertRaisesRegex(AurPkgbuildFetchError, "not reviewable UTF-8"):
                self.aur._checkout_snapshot(checkout)

    def test_aur_rpc_metadata_uses_chunked_post_requests(self) -> None:
        class _ChunkedAurUpdateService(AurUpdateService):
            AUR_RPC_CHUNK_SIZE = 2

        service = _ChunkedAurUpdateService(runner=CommandRunner())
        calls: list[list[str]] = []

        def fetch_chunk(names: list[str]) -> dict[str, object]:
            calls.append(names)
            return {
                "results": [
                    {"Name": name, "Maintainer": f"{name}-maintainer"}
                    for name in names
                ]
            }

        service._fetch_aur_rpc_chunk = fetch_chunk  # type: ignore[method-assign]
        packages = [
            PackageUpdate(
                f"pkg-{index}",
                "1",
                "2",
                UpdateSource.AUR,
                AurPackageMetadata(),
            )
            for index in range(5)
        ]

        metadata = service._fetch_aur_rpc_metadata(packages)

        self.assertEqual(calls, [["pkg-0", "pkg-1"], ["pkg-2", "pkg-3"], ["pkg-4"]])
        self.assertEqual(metadata["pkg-4"]["Maintainer"], "pkg-4-maintainer")

    def test_pacman_selection_policy_marks_ignorepkg_matches_as_blocked(self) -> None:
        packages, _unparsed = self.pacman._parse_update_output(
            "linux 6.9.1.arch1-1 -> 6.9.2.arch1-1"
        )
        self.pacman._apply_selection_policy(packages[0], ignore_patterns=[re.compile(r"^linux$")])

        package = packages[0]
        self.assertTrue(package.blocked_by_config)
        self.assertTrue(package.selection_locked)
        self.assertEqual(package.blocked_reason, "Blocked by pacman.conf")
        self.assertFalse(package.selected)

    def test_pacman_parser_accepts_ignored_update_suffix(self) -> None:
        packages, unparsed = self.pacman._parse_update_output(
            "linux 6.9.1.arch1-1 -> 6.9.2.arch1-1 [ignored]\n"
        )

        self.assertEqual([package.name for package in packages], ["linux"])
        self.assertEqual(packages[0].new_version, "6.9.2.arch1-1")
        self.assertTrue(packages[0].blocked_by_config)
        self.assertTrue(packages[0].selection_locked)
        self.assertFalse(packages[0].selected)
        self.assertEqual(unparsed, [])

    def test_flatpak_parse_installed_versions_uses_ref_or_application(self) -> None:
        raw = "\n".join(
            [
                "com.github.tchx84.Flatseal\tFlatseal\t2.2.0\tuser\tapp/com.github.tchx84.Flatseal/x86_64/stable",
                "org.freedesktop.Platform\tFreedesktop Platform\t23.08\tsystem\t",
            ]
        )

        installed = self.flatpak._parse_installed_versions(raw, FlatpakRefKind.APP)

        self.assertEqual(
            installed["app/com.github.tchx84.Flatseal/x86_64/stable"],
            {
                "version": "2.2.0",
                "installation": "user",
                "installed_size": "",
                "origin": "",
                "branch": "",
                "runtime": "",
            },
        )
        self.assertEqual(installed["org.freedesktop.Platform"]["version"], "23.08")
        self.assertEqual(installed["org.freedesktop.Platform"]["installation"], "system")

    def test_flatpak_check_scope_builds_packages_with_installed_versions(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self.calls = 0

            def run(self, command, *, timeout_seconds=None):  # noqa: ANN001
                self.calls += 1
                if "remote-ls" in command:
                    return type(
                        "Log",
                        (),
                        {
                            "exit_code": 0,
                            "stdout": (
                                "com.github.tchx84.Flatseal\tFlatseal\t2.3.0\tstable\t"
                                "Manage Flatpak permissions\tflathub\t"
                                "app/com.github.tchx84.Flatseal/x86_64/stable\t10 MB\t20 MB\t\n"
                            ),
                        },
                    )()
                return type(
                    "Log",
                    (),
                    {
                        "exit_code": 0,
                        "stdout": (
                            "com.github.tchx84.Flatseal\tFlatseal\t2.2.0\tuser\t"
                            "app/com.github.tchx84.Flatseal/x86_64/stable\t18 MB\t"
                            "flathub\tstable\torg.gnome.Platform\n"
                        ),
                    },
                )()

        service = FlatpakUpdateService(runner=_Runner())  # type: ignore[arg-type]
        packages, logs, warnings = service._check_scope("user", FlatpakRefKind.APP)

        self.assertEqual(len(packages), 1)
        package = packages[0]
        metadata = package.source_metadata
        self.assertIsInstance(metadata, FlatpakPackageMetadata)
        self.assertEqual(package.name, "Flatseal")
        self.assertEqual(package.current_version, "2.2.0")
        self.assertEqual(package.new_version, "2.3.0")
        self.assertEqual(metadata.installation_scope, "user")
        self.assertEqual(package.backend_id, "app/com.github.tchx84.Flatseal/x86_64/stable")
        self.assertEqual(metadata.ref_kind, FlatpakRefKind.APP)
        self.assertEqual(package.source, UpdateSource.FLATPAK)
        self.assertEqual(metadata.remote, "flathub")
        self.assertEqual(metadata.branch, "stable")
        self.assertEqual(metadata.runtime, "org.gnome.Platform")
        self.assertEqual(package.download_size, "10 MB")
        self.assertEqual(package.installed_size, "20 MB")
        self.assertEqual(package.current_installed_size, "18 MB")
        self.assertEqual(package.size_diff, "+1.91 MiB")
        self.assertEqual(len(logs), 2)
        self.assertEqual(warnings, [])

    def test_flatpak_check_scope_matches_installed_ref_without_kind_prefix(self) -> None:
        class _Runner:
            def run(self, command, *, timeout_seconds=None):  # noqa: ANN001
                if "remote-ls" in command:
                    return type(
                        "Log",
                        (),
                        {
                            "exit_code": 0,
                            "stdout": (
                                "com.bitwarden.desktop\tBitwarden\t2026.6.0\tstable\t"
                                "A secure and free password manager\tflathub\t"
                                "app/com.bitwarden.desktop/x86_64/stable\t225.4 MB\t711.6 MB\t"
                                "org.freedesktop.Platform/x86_64/25.08\n"
                            ),
                        },
                    )()
                return type(
                    "Log",
                    (),
                    {
                        "exit_code": 0,
                        "stdout": (
                            "com.bitwarden.desktop\tBitwarden\t2026.5.0\tsystem\t"
                            "com.bitwarden.desktop/x86_64/stable\t711.6 MB\t"
                            "flathub\tstable\torg.freedesktop.Platform/x86_64/25.08\n"
                        ),
                    },
                )()

        service = FlatpakUpdateService(runner=_Runner())  # type: ignore[arg-type]
        packages, _logs, warnings = service._check_scope("system", FlatpakRefKind.APP)

        self.assertEqual(warnings, [])
        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0].current_version, "2026.5.0")
        self.assertEqual(packages[0].new_version, "2026.6.0")

    def test_flatpak_check_scope_accepts_runtime_updates_without_runtime_column(self) -> None:
        class _Runner:
            def run(self, command, *, timeout_seconds=None):  # noqa: ANN001
                if "remote-ls" in command:
                    return type(
                        "Log",
                        (),
                        {
                            "exit_code": 0,
                            "stdout": (
                                "org.freedesktop.Platform.GL.nvidia-595-71-05\t"
                                "nvidia-595-71-05\t\t1.4\t\tflathub\t"
                                "runtime/org.freedesktop.Platform.GL.nvidia-595-71-05/x86_64/1.4\t"
                                "304.3 MB\t820.1 MB\n"
                            ),
                        },
                    )()
                return type(
                    "Log",
                    (),
                    {
                        "exit_code": 0,
                        "stdout": (
                            "org.freedesktop.Platform.GL.nvidia-595-71-05\t"
                            "nvidia-595-71-05\t\tsystem\t"
                            "runtime/org.freedesktop.Platform.GL.nvidia-595-71-05/x86_64/1.4\t"
                            "819.7 MB\tflathub\t1.4\t\n"
                        ),
                    },
                )()

        service = FlatpakUpdateService(runner=_Runner())  # type: ignore[arg-type]
        packages, _logs, warnings = service._check_scope("system", FlatpakRefKind.RUNTIME)

        self.assertEqual(warnings, [])
        self.assertEqual(len(packages), 1)
        package = packages[0]
        metadata = package.source_metadata
        self.assertIsInstance(metadata, FlatpakPackageMetadata)
        self.assertEqual(package.name, "nvidia-595-71-05")
        self.assertEqual(package.backend_id, "runtime/org.freedesktop.Platform.GL.nvidia-595-71-05/x86_64/1.4")
        self.assertEqual(metadata.ref_kind, FlatpakRefKind.RUNTIME)
        self.assertEqual(metadata.installation_scope, "system")
        self.assertEqual(metadata.remote, "flathub")

    def test_flatpak_check_scope_warns_about_unparseable_update_lines(self) -> None:
        class _Runner:
            def run(self, command, *, timeout_seconds=None):  # noqa: ANN001
                if "remote-ls" in command:
                    return type(
                        "Log",
                        (),
                        {
                            "exit_code": 0,
                            "stdout": "not-enough\tcolumns\n",
                        },
                    )()
                return type("Log", (), {"exit_code": 0, "stdout": ""})()

        service = FlatpakUpdateService(runner=_Runner())  # type: ignore[arg-type]
        packages, _logs, warnings = service._check_scope("system", FlatpakRefKind.APP)

        self.assertEqual(packages, [])
        self.assertEqual(
            warnings,
            ["Some Flatpak update lines could not be parsed: not-enough\tcolumns"],
        )

    def test_firmware_helpers_extract_target_name_size_and_warning(self) -> None:
        device = {
            "Vendor": "Framework",
            "Name": "Laptop 13 BIOS",
            "Version": "3.03",
            "DeviceId": "device-1",
            "NeedsReboot": True,
        }
        release = {
            "Version": "3.05",
            "Summary": "Firmware improvements",
            "RemoteId": "lvfs",
            "Size": 2097152,
            "Flags": ["is-upgrade"],
        }

        self.assertEqual(self.firmware._device_target_id(device), "device-1")
        self.assertEqual(self.firmware._device_name(device), "Framework Laptop 13 BIOS")
        self.assertEqual(self.firmware._format_bytes(release["Size"]), "2.00 MiB")
        needs_reboot, needs_shutdown = self.firmware._restart_requirement(device, release)
        self.assertEqual(
            self.firmware._device_warnings(
                needs_reboot=needs_reboot,
                needs_shutdown=needs_shutdown,
            ),
            ["A reboot may be required after installing this firmware update."],
        )

    def test_firmware_release_flags_do_not_imply_reboot_warning(self) -> None:
        device = {
            "Vendor": "Framework",
            "Name": "Laptop 13 BIOS",
            "Version": "3.03",
            "DeviceId": "device-1",
            "NeedsReboot": False,
        }
        release = {
            "Version": "3.05",
            "Summary": "Firmware improvements",
            "RemoteId": "lvfs",
            "Size": 2097152,
            "Flags": ["is-upgrade"],
        }

        needs_reboot, needs_shutdown = self.firmware._restart_requirement(device, release)
        self.assertEqual(
            self.firmware._device_warnings(
                needs_reboot=needs_reboot,
                needs_shutdown=needs_shutdown,
            ),
            [],
        )

    def test_firmware_string_false_does_not_imply_restart_requirement(self) -> None:
        needs_reboot, needs_shutdown = self.firmware._restart_requirement(
            {"NeedsReboot": "false", "NeedsShutdown": "false"},
            {},
        )

        self.assertFalse(needs_reboot)
        self.assertFalse(needs_shutdown)

    def test_firmware_device_needs_reboot_flag_adds_warning(self) -> None:
        device = {
            "DeviceId": "device-1",
            "Flags": ["internal", "needs-reboot", "updatable"],
        }

        needs_reboot, needs_shutdown = self.firmware._restart_requirement(device, {})
        self.assertEqual(
            self.firmware._device_warnings(
                needs_reboot=needs_reboot,
                needs_shutdown=needs_shutdown,
            ),
            ["A reboot may be required after installing this firmware update."],
        )

    def test_firmware_needs_shutdown_takes_precedence_over_reboot(self) -> None:
        device = {
            "DeviceId": "device-1",
            "NeedsReboot": True,
            "Flags": ["internal", "needs-shutdown", "updatable"],
        }

        needs_reboot, needs_shutdown = self.firmware._restart_requirement(device, {})
        self.assertEqual(
            self.firmware._device_warnings(
                needs_reboot=needs_reboot,
                needs_shutdown=needs_shutdown,
            ),
            ["A full shutdown is required after installing this firmware update."],
        )

    def test_firmware_skips_devices_without_release_version(self) -> None:
        device = {
            "Vendor": "Framework",
            "Name": "Laptop 13 BIOS",
            "Version": "3.03",
            "DeviceId": "device-1",
            "Releases": [{"Summary": "Missing version"}],
        }

        self.assertIsNone(self.firmware._first_release_with_version(device))

    def test_firmware_get_updates_exit_code_2_without_stdout_is_not_warning(self) -> None:
        service = FirmwareUpdateService(
            runner=self._firmware_runner(
                [
                    self._command_log(["fwupdmgr", "refresh", "--force"], exit_code=0),
                    self._command_log(
                        ["fwupdmgr", "get-updates", "--json", "--no-authenticate"],
                        exit_code=2,
                        stdout="",
                    ),
                ]
            )
        )

        with patch("archupdater.services.firmware.shutil.which", return_value="/usr/bin/fwupdmgr"):
            result = service.check_updates()

        self.assertEqual(result.packages, [])
        self.assertEqual(result.warnings, [])

    def test_firmware_check_updates_reads_nested_child_devices(self) -> None:
        payload = {
            "Devices": [
                {
                    "Name": "Parent device",
                    "Children": [
                        {
                            "Vendor": "Framework",
                            "Name": "Laptop 13 BIOS",
                            "Version": "3.03",
                            "DeviceId": "device-1",
                            "Releases": [
                                {
                                    "Version": "3.05",
                                    "Summary": "Firmware improvements",
                                    "RemoteId": "lvfs",
                                    "Size": 2097152,
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        service = FirmwareUpdateService(
            runner=self._firmware_runner(
                [
                    self._command_log(["fwupdmgr", "refresh", "--force"], exit_code=0),
                    self._command_log(
                        ["fwupdmgr", "get-updates", "--json", "--no-authenticate"],
                        exit_code=0,
                        stdout=json.dumps(payload),
                    ),
                ]
            )
        )

        with patch("archupdater.services.firmware.shutil.which", return_value="/usr/bin/fwupdmgr"):
            result = service.check_updates()

        self.assertEqual([package.backend_id for package in result.packages], ["device-1"])
        self.assertEqual(result.packages[0].name, "Framework Laptop 13 BIOS")

    def _firmware_runner(self, logs: list[CommandLogEntry]):
        class _Runner:
            def __init__(self, entries: list[CommandLogEntry]) -> None:
                self.entries = entries

            def run(
                self,
                _command: list[str],
                *,
                timeout_seconds: float | None = None,
            ) -> CommandLogEntry:
                return self.entries.pop(0)

        return _Runner(logs)

    def _command_log(
        self,
        command: list[str],
        *,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
    ) -> CommandLogEntry:
        return CommandLogEntry(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            started_at=datetime.now(),
            duration_ms=1,
        )


if __name__ == "__main__":
    unittest.main()
