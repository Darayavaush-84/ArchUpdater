from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QTranslator

SYSTEM_LANGUAGE = "system"
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "it": "Italiano",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
}


def iter_locale_candidates(
    *,
    env: Mapping[str, str] | None = None,
    system_locale: QLocale | None = None,
) -> Iterable[str]:
    locale = system_locale or QLocale.system()
    for tag in locale.uiLanguages():
        if not tag:
            continue
        normalized = tag.replace("-", "_").split("_", 1)[0].lower()
        if normalized:
            yield normalized

    normalized_name = locale.name().split("_", 1)[0].lower()
    if normalized_name:
        yield normalized_name

    environment = os.environ if env is None else env
    for env_key in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        raw_value = environment.get(env_key, "")
        if not raw_value:
            continue
        for chunk in raw_value.split(":"):
            normalized = chunk.split(".", 1)[0].replace("-", "_").split("_", 1)[0].lower()
            if normalized:
                yield normalized


def resolve_language_code(
    preference: str | None,
    *,
    env: Mapping[str, str] | None = None,
    system_locale: QLocale | None = None,
) -> str:
    if preference in SUPPORTED_LANGUAGES:
        return str(preference)
    for candidate in iter_locale_candidates(env=env, system_locale=system_locale):
        if candidate in SUPPORTED_LANGUAGES:
            return candidate
    return "en"


@dataclass(frozen=True, slots=True)
class LanguageOption:
    code: str
    label: str


class TranslationManager:
    def __init__(self, application: QCoreApplication) -> None:
        self._application = application
        self._translator = QTranslator(application)

    def available_language_options(self) -> list[LanguageOption]:
        options = [LanguageOption(SYSTEM_LANGUAGE, self._application.translate("TranslationManager", "Use System Language"))]
        options.extend(LanguageOption(code, label) for code, label in SUPPORTED_LANGUAGES.items())
        return options

    def display_name(self, code: str) -> str:
        if code == SYSTEM_LANGUAGE:
            return self._application.translate("TranslationManager", "Use System Language")
        return SUPPORTED_LANGUAGES.get(code, SUPPORTED_LANGUAGES["en"])

    def resolve_language(self, preference: str | None) -> str:
        return resolve_language_code(preference)

    def install(self, preference: str | None) -> str:
        resolved = self.resolve_language(preference)
        self._application.removeTranslator(self._translator)

        if resolved != "en":
            qm_path = self.translations_dir() / f"archupdater_{resolved}.qm"
            if self._translator.load(str(qm_path)):
                self._application.installTranslator(self._translator)
            else:
                resolved = "en"

        return resolved

    def translations_dir(self) -> Path:
        return Path(__file__).resolve().parent / "resources"
