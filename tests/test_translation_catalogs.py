from __future__ import annotations

import ast
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QApplication, QWidget

from archupdater.container import ApplicationContainer
from archupdater.domain.enums import PreflightSeverity
from archupdater.domain.preflight import PreflightIssue
from archupdater.presentation.main_window.check_presenter import MainWindowCheckPresenter
from archupdater.presentation.main_window.state import MainWindowState
from archupdater.presentation.preflight_dialogs import confirm_preflight_issues
from archupdater.presentation.widgets.action_bar import ActionBarWidget


ROOT = Path(__file__).resolve().parents[1]


class TranslationCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_all_compiled_catalog_entries_match_sources_and_preserve_placeholders(self) -> None:
        for language in ("en", "it", "de", "fr", "es"):
            translator = QTranslator()
            self.assertTrue(
                translator.load(
                    str(ROOT / f"src/archupdater/i18n/resources/archupdater_{language}.qm")
                )
            )
            catalog = ET.parse(ROOT / f"i18n/ts/archupdater_{language}.ts").getroot()
            for context in catalog.findall("context"):
                name = context.findtext("name")
                self.assertNotIn(name, {"parent", "view", "self._window"})
                for message in context.findall("message"):
                    source = message.findtext("source")
                    translated = message.findtext("translation")
                    with self.subTest(language=language, context=name, source=source):
                        self.assertNotEqual(message.find("translation").get("type"), "unfinished")
                        self.assertTrue(translated)
                        self.assertEqual(
                            Counter(re.findall(r"\{[^{}]+\}|%[1-9n]", source)),
                            Counter(re.findall(r"\{[^{}]+\}|%[1-9n]", translated)),
                        )
                        self.assertEqual(
                            translator.translate(name, source, message.findtext("comment")),
                            translated,
                        )

    def test_gui_and_injected_services_use_the_runtime_language(self) -> None:
        expected = {
            "it": (
                "Aggiorna 2 elementi",
                "Aggiornamento dello stato dei pacchetti...",
                "Impossibile avviare l’aggiornamento",
            ),
            "de": (
                "2 Elemente aktualisieren",
                "Paketstatus wird aktualisiert...",
                "Aktualisierung kann nicht gestartet werden",
            ),
            "fr": (
                "Mettre à jour 2 éléments",
                "Actualisation de l’état des paquets...",
                "Impossible de démarrer la mise à jour",
            ),
            "es": (
                "Actualizar 2 elementos",
                "Actualizando el estado de los paquetes...",
                "No se puede iniciar la actualización",
            ),
        }
        for language, (button_text, status_text, dialog_title) in expected.items():
            with self.subTest(language=language):
                translator = QTranslator()
                self.assertTrue(
                    translator.load(
                        str(ROOT / f"src/archupdater/i18n/resources/archupdater_{language}.qm")
                    )
                )
                self.app.installTranslator(translator)
                try:
                    bar = ActionBarWidget()
                    bar.set_update_selection(2)
                    self.assertEqual(bar.update_button.text(), button_text)
                    window = Mock()
                    presenter = MainWindowCheckPresenter(window, MainWindowState())
                    presenter.show_post_update_refreshing_state()
                    window.header_widget.set_system_status.assert_called_once_with(status_text)
                    parent = QWidget()
                    with patch(
                        "archupdater.presentation.preflight_dialogs.QMessageBox.warning"
                    ) as warning:
                        confirm_preflight_issues(
                            parent, [PreflightIssue(PreflightSeverity.BLOCKING, "Test", "Test")]
                        )
                    self.assertEqual(warning.call_args.args[1], dialog_title)
                    container = ApplicationContainer()
                    self.assertNotEqual(
                        container.preflight.translate("Required tool is missing"),
                        "Required tool is missing",
                    )
                    self.assertNotEqual(
                        container.updates().check_updates_use_case.translate(
                            "Checking AUR updates..."
                        ),
                        "Checking AUR updates...",
                    )
                    bar.close()
                    parent.close()
                finally:
                    self.app.removeTranslator(translator)

    def test_callback_messages_are_present_in_their_runtime_contexts(self) -> None:
        catalog = ET.parse(ROOT / "i18n/ts/archupdater_en.ts").getroot()
        entries = {
            (context.findtext("name"), message.findtext("source"))
            for context in catalog.findall("context")
            for message in context.findall("message")
        }
        contexts = {
            "services/optional_sources.py": "OptionalSourcesService",
            "services/plasma_widgets_store.py": "PlasmaWidgetsStoreClient",
            "services/plasma_widgets.py": "PlasmaWidgetsUpdateService",
            "services/plasma_widgets_update.py": "PlasmaWidgetsUpdateService",
            "services/plasma_widget_archive.py": "PlasmaWidgetsUpdateService",
            "services/preflight.py": "UpdatePreflightService",
            "application/preflight.py": "UpdatePreflightService",
            "services/batch_process.py": "BatchUpdateRunner",
            "services/update_diagnostics.py": "BatchUpdateRunner",
        }
        source_root = ROOT / "src/archupdater"
        for path in source_root.rglob("*.py"):
            relative = path.relative_to(source_root).as_posix()
            for call in ast.walk(ast.parse(path.read_text())):
                if not isinstance(call, ast.Call) or not call.args:
                    continue
                method = (
                    call.func.attr
                    if isinstance(call.func, ast.Attribute)
                    else call.func.id
                    if isinstance(call.func, ast.Name)
                    else ""
                )
                if method not in {"_t", "_translate", "translate"}:
                    continue
                if method == "translate" and len(call.args) > 1:
                    continue  # Explicit Qt context: handled by lupdate.
                if not isinstance(call.args[0], ast.Constant) or not isinstance(
                    call.args[0].value, str
                ):
                    continue
                context = contexts.get(relative)
                if relative.startswith(("application/update_session/", "batch/")):
                    context = "BatchUpdateRunner"
                elif relative.startswith("application/update_sources/"):
                    context = (
                        "UpdatePreflightService"
                        if ast.unparse(call.func).startswith("context.")
                        else "UpdateService"
                    )
                elif relative.startswith(("presentation/", "domain/")):
                    context = "MainWindow"
                with self.subTest(file=relative, line=call.lineno):
                    self.assertIsNotNone(
                        context, "Register the callback's runtime translation context"
                    )
                    self.assertIn((context, call.args[0].value), entries)
