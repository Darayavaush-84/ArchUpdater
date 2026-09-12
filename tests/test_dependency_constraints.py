from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]


class DependencyConstraintTests(unittest.TestCase):
    def test_ci_pins_every_direct_dependency_inside_its_supported_range(self) -> None:
        project = tomllib.loads(ROOT.joinpath("pyproject.toml").read_text(encoding="utf-8"))
        requirements = [
            *project["build-system"]["requires"],
            *project["project"]["dependencies"],
            *project["project"]["optional-dependencies"]["dev"],
        ]
        constraints = self._constraints()

        for raw_requirement in requirements:
            requirement = Requirement(raw_requirement)
            with self.subTest(dependency=requirement.name):
                self.assertIn(requirement.name.casefold(), constraints)
                pinned = constraints[requirement.name.casefold()]
                self.assertIn(Version(pinned), requirement.specifier)

    def _constraints(self) -> dict[str, str]:
        constraints: dict[str, str] = {}
        for raw_line in ROOT.joinpath("constraints-ci.txt").read_text(
            encoding="utf-8"
        ).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            requirement = Requirement(line)
            self.assertEqual(len(requirement.specifier), 1)
            specifier = next(iter(requirement.specifier))
            self.assertEqual(specifier.operator, "==")
            constraints[requirement.name.casefold()] = specifier.version
        return constraints


if __name__ == "__main__":
    unittest.main()
