from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_translation_sources.py"

spec = importlib.util.spec_from_file_location("check_translation_sources", SCRIPT_PATH)
assert spec is not None
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
assert spec.loader is not None
spec.loader.exec_module(checker)


class TranslationSourceCheckTests(unittest.TestCase):
    def test_catalog_debt_reports_missing_stale_and_unfinished_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fresh = root / "fresh.ts"
            catalog = root / "catalog.ts"
            fresh.write_text(
                self._catalog_xml(
                    '<message><source>Kept</source><translation type="unfinished" /></message>'
                    '<message><source>New</source><translation type="unfinished" /></message>'
                ),
                encoding="utf-8",
            )
            catalog.write_text(
                self._catalog_xml(
                    '<message><source>Kept</source><translation type="unfinished" /></message>'
                    '<message><source>Old</source><translation>Translated</translation></message>'
                ),
                encoding="utf-8",
            )

            debt = checker.catalog_debt(catalog, fresh)

        self.assertEqual({key[1] for key in debt["missing"]}, {"New"})
        self.assertEqual({key[1] for key in debt["stale"]}, {"Old"})
        self.assertEqual({key[1] for key in debt["unfinished"]}, {"Kept"})

    def test_synchronized_finished_catalog_has_no_debt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fresh = root / "fresh.ts"
            catalog = root / "catalog.ts"
            fresh.write_text(
                self._catalog_xml(
                    '<message><source>Ready</source><translation type="unfinished" /></message>'
                ),
                encoding="utf-8",
            )
            catalog.write_text(
                self._catalog_xml(
                    "<message><source>Ready</source><translation>Pronto</translation></message>"
                ),
                encoding="utf-8",
            )

            debt = checker.catalog_debt(catalog, fresh)

        self.assertTrue(all(not keys for keys in debt.values()))

    def _catalog_xml(self, messages: str) -> str:
        return f"<TS version='2.1'><context><name>Example</name>{messages}</context></TS>"


if __name__ == "__main__":
    unittest.main()
