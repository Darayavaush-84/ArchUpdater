from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QLocale

from archupdater.i18n.manager import iter_locale_candidates


class I18nManagerTests(unittest.TestCase):
    def test_explicit_empty_environment_does_not_fall_back_to_process_environment(self) -> None:
        with patch.dict(os.environ, {"LANGUAGE": "it"}, clear=True):
            candidates = list(
                iter_locale_candidates(env={}, system_locale=QLocale(QLocale.Language.C))
            )

        self.assertNotIn("it", candidates)


if __name__ == "__main__":
    unittest.main()
