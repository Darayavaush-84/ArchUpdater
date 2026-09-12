from __future__ import annotations

import ast
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "archupdater"


def _python_files(package: str) -> list[Path]:
    return sorted((PACKAGE_ROOT / package).rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _imported_names(path: Path, module_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            names.update(alias.name for alias in node.names)
    return names


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_domain_is_pure(self) -> None:
        forbidden_prefixes = (
            "PySide6",
            "archupdater.infrastructure",
            "archupdater.services",
            "archupdater.presentation",
            "archupdater.helper",
            "subprocess",
        )
        offenders = self._imports_with_forbidden_prefixes("domain", forbidden_prefixes)
        self.assertEqual(offenders, [])

    def test_services_do_not_import_presentation_or_helper(self) -> None:
        offenders = self._imports_with_forbidden_prefixes(
            "services",
            (
                "archupdater.application",
                "archupdater.infrastructure",
                "archupdater.presentation",
                "archupdater.helper",
            ),
        )
        self.assertEqual(offenders, [])

    def test_application_does_not_import_presentation_helper_qt_or_system_adapters(self) -> None:
        offenders = self._imports_with_forbidden_prefixes(
            "application",
            (
                "PySide6",
                "os",
                "shutil",
                "subprocess",
                "archupdater.infrastructure",
                "archupdater.presentation",
                "archupdater.helper",
            ),
        )
        self.assertEqual(offenders, [])

    def test_infrastructure_does_not_import_application_presentation_or_helper(self) -> None:
        offenders = self._imports_with_forbidden_prefixes(
            "infrastructure",
            ("archupdater.application", "archupdater.presentation", "archupdater.helper"),
        )
        self.assertEqual(offenders, [])

    def test_services_do_not_own_qt_process_or_object_adapters(self) -> None:
        forbidden_names = {"QObject", "QProcess", "QProcessEnvironment", "QTimer", "Signal", "Slot"}
        offenders: list[str] = []
        for path in _python_files("services"):
            imported_names = _imported_names(path, "PySide6.QtCore")
            forbidden_imports = sorted(imported_names & forbidden_names)
            if forbidden_imports:
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)} imports {', '.join(forbidden_imports)}"
                )
        self.assertEqual(offenders, [])

    def test_presentation_does_not_import_helper(self) -> None:
        offenders = self._imports_with_forbidden_prefixes(
            "presentation",
            ("archupdater.helper", "archupdater.services"),
        )
        self.assertEqual(offenders, [])

    def test_helper_does_not_import_presentation(self) -> None:
        offenders = self._imports_with_forbidden_prefixes(
            "helper",
            ("archupdater.presentation",),
        )
        self.assertEqual(offenders, [])

    def _imports_with_forbidden_prefixes(
        self,
        package: str,
        forbidden_prefixes: tuple[str, ...],
    ) -> list[str]:
        offenders: list[str] = []
        for path in _python_files(package):
            for module in sorted(_imported_modules(path)):
                if module.startswith(forbidden_prefixes):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
        return offenders
