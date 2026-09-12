from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "validate_kde_addon_id_map.py"
MAP_PATH = ROOT / "src" / "archupdater" / "resources" / "data" / "plasma_widgets_id_map.txt"

spec = importlib.util.spec_from_file_location("validate_kde_addon_id_map", SCRIPT_PATH)
assert spec is not None
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
assert spec.loader is not None
spec.loader.exec_module(validator)


class KdeAddonIdMapTests(unittest.TestCase):
    def test_project_id_map_is_valid(self) -> None:
        self.assertEqual(validator.validate_id_map(MAP_PATH), [])

    def test_ignored_entries_do_not_count_as_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.txt"
            path.write_text(
                "1000 org.example.addon\n"
                "1001 org.example.addon #Ignored, not a unique ID\n",
                encoding="utf-8",
            )

            self.assertEqual(validator.validate_id_map(path), [])


if __name__ == "__main__":
    unittest.main()
