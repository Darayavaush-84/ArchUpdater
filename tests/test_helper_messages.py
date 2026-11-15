from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QCoreApplication

from archupdater.application.helper_protocol import (
    HelperEventType,
    HelperText,
    translate,
    translated_helper_message,
)
from archupdater.helper import privileged_helper
from archupdater.helper.actions.common import exception_message
from archupdater.i18n.manager import TranslationManager
from archupdater.presentation.privileged_client import PrivilegedUpdateClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class HelperTextTests(unittest.TestCase):
    def test_text_is_english_and_keeps_its_catalog_key(self) -> None:
        text = translate("PrivilegedHelper", "pacman exited with code {code}.").format(code=3)

        self.assertIsInstance(text, HelperText)
        self.assertEqual(text, "pacman exited with code 3.")
        self.assertEqual(
            text.translation_payload(),
            {
                "context": "PrivilegedHelper",
                "source": "pacman exited with code {code}.",
                "arguments": {"code": "3"},
            },
        )

    def test_unformatted_template_stays_unchanged_until_formatted(self) -> None:
        template = translate("PrivilegedHelper", "flatpak exited with code {code}.")

        self.assertEqual(template, "flatpak exited with code {code}.")
        self.assertEqual(template.format(code=1), "flatpak exited with code 1.")

    def test_exception_message_keeps_the_catalog_key(self) -> None:
        with self.assertRaises(privileged_helper.HelperValidationError) as raised:
            privileged_helper.validate_request(
                {"action": "run_firmware_update", "device_id": 5, "expected_version": "1"}
            )

        message = exception_message(raised.exception)

        self.assertIsInstance(message, HelperText)
        self.assertEqual(message.source, "`device_id` must be a string.")
        self.assertEqual(exception_message(OSError("disk full")), "disk full")

    def test_emitted_event_carries_english_message_and_catalog_key(self) -> None:
        output = io.StringIO()
        with patch.object(privileged_helper.sys, "stdout", output):
            privileged_helper.emit_event(
                HelperEventType.COMPLETED,
                success=False,
                message=translate("PrivilegedHelper", "pacman exited with code {code}.").format(
                    code=1
                ),
            )
            privileged_helper.emit_log("raw pacman output")

        completed, log = (json.loads(line) for line in output.getvalue().splitlines())
        self.assertEqual(completed["message"], "pacman exited with code 1.")
        self.assertEqual(
            completed["message_translation"]["source"], "pacman exited with code {code}."
        )
        self.assertEqual(log, {"event": "log", "message": "raw pacman output"})


class TranslatedHelperMessageTests(unittest.TestCase):
    def test_translates_and_formats_with_the_catalog_key(self) -> None:
        payload = {
            "message": "pacman exited with code 1.",
            "message_translation": {
                "context": "PrivilegedHelper",
                "source": "pacman exited with code {code}.",
                "arguments": {"code": "1"},
            },
        }

        message = translated_helper_message(payload, lambda _context, _source: "Codice {code}")

        self.assertEqual(message, "Codice 1")

    def test_falls_back_to_english_text(self) -> None:
        def key(**changes: object) -> dict[str, object]:
            return {
                "context": "PrivilegedHelper",
                "source": "Done {code}",
                "arguments": {"code": "1"},
                **changes,
            }

        for translation in (
            None,
            "Done 1",
            key(arguments={"code": 1}),
            key(context=None),
            {**key(), "extra": True},
        ):
            with self.subTest(translation=translation):
                payload = {"message": "Done 1", "message_translation": translation}
                self.assertEqual(
                    translated_helper_message(payload, lambda _context, _source: "Fatto"),
                    "Done 1",
                )
        broken_catalog = {"message": "Done 1", "message_translation": key()}
        self.assertEqual(
            translated_helper_message(broken_catalog, lambda _context, _source: "Fatto {other}"),
            "Done 1",
        )
        self.assertEqual(translated_helper_message({}, lambda _context, source: source), "")

    def test_gui_client_translates_with_the_installed_catalog(self) -> None:
        app = QCoreApplication.instance() or QCoreApplication([])
        translations = TranslationManager(app)
        self.assertEqual(translations.install("it"), "it")
        self.addCleanup(translations.install, "en")
        message = translate("PrivilegedHelper", "pacman exited with code {code}.").format(code=2)
        client = PrivilegedUpdateClient()

        client._handle_stdout_line(json.dumps({
            "event": "completed",
            "success": False,
            "message": message,
            "message_translation": message.translation_payload(),
        }))

        self.assertEqual(client._completed_payload, (False, "pacman è terminato con codice 2."))


class HelperRuntimeTests(unittest.TestCase):
    def test_privileged_entrypoints_do_not_load_qt(self) -> None:
        code = (
            "import sys\n"
            "import archupdater.helper.privileged_helper\n"
            "import archupdater.helper.self_update\n"
            "print(sorted(name for name in sys.modules if name.startswith('PySide6')))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )

        self.assertEqual(result.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
