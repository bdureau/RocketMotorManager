"""Internationalisation based on Qt's QTranslator.

All UI strings are written in English and wrapped with ``self.tr()``.
Adding a language:

1. ``pylupdate6 ui widgets application -ts resources/translations/rmm_fr.ts``
2. Translate with Qt Linguist and compile with ``lrelease`` to
   ``resources/translations/rmm_fr.qm``.
3. The language appears automatically in Preferences (restart required).
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

from application.paths import resource_path

logger = logging.getLogger(__name__)

TRANSLATION_PREFIX = "rmm_"
LANGUAGE_NAMES = {"en": "English", "fr": "Français", "de": "Deutsch", "es": "Español", "it": "Italiano"}


def available_languages() -> dict[str, str]:
    """Return ``{code: display name}`` for English and each compiled translation."""
    languages = {"en": "English"}
    folder = resource_path("resources", "translations")
    if folder.is_dir():
        for file in sorted(folder.glob(f"{TRANSLATION_PREFIX}*.qm")):
            code = file.stem[len(TRANSLATION_PREFIX):]
            languages[code] = LANGUAGE_NAMES.get(code, code)
    return languages


class TranslationManager:
    """Install the application and Qt translators for a language."""

    def __init__(self) -> None:
        self._translators: list[QTranslator] = []

    def install(self, app: QCoreApplication, language: str) -> bool:
        """Install translators for ``language``; return False when English
        (built-in) or when no translation file was found."""
        for translator in self._translators:
            app.removeTranslator(translator)
        self._translators.clear()
        if language == "en":
            return False
        loaded = False
        app_translator = QTranslator(app)
        file = resource_path("resources", "translations", f"{TRANSLATION_PREFIX}{language}.qm")
        if app_translator.load(str(file)):
            app.installTranslator(app_translator)
            self._translators.append(app_translator)
            loaded = True
        else:
            logger.warning("Translation file not found: %s", file)
        qt_translator = QTranslator(app)
        qt_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if qt_translator.load(QLocale(language), "qtbase", "_", qt_path):
            app.installTranslator(qt_translator)
            self._translators.append(qt_translator)
        return loaded

    @staticmethod
    def system_language() -> Optional[str]:
        """Two-letter code of the operating system language."""
        return QLocale.system().name().split("_")[0] or None
