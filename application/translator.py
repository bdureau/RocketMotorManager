"""Translation of Qt's own widgets (standard buttons, file dialogs, print
preview...) with Qt's ``qtbase_<lang>.qm`` catalogues.

The application texts themselves are translated with GNU gettext ``.po``
files, see :mod:`localization`.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QCoreApplication, QLibraryInfo, QTranslator

logger = logging.getLogger(__name__)

#: Qt catalogues tried for each application language (Qt only ships
#: Brazilian Portuguese).
QT_CATALOGUES = {"pt": ("pt_PT", "pt", "pt_BR")}


class TranslationManager:
    """Install the Qt base translator matching the application language."""

    def __init__(self) -> None:
        self._translator: QTranslator | None = None

    def install(self, app: QCoreApplication, language: str) -> bool:
        """Install ``qtbase_<language>``; returns False when not available."""
        if self._translator is not None:
            app.removeTranslator(self._translator)
            self._translator = None
        if language == "en":
            return False
        folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        translator = QTranslator(app)
        for code in QT_CATALOGUES.get(language, (language,)):
            if translator.load(f"qtbase_{code}", folder):
                app.installTranslator(translator)
                self._translator = translator
                return True
        logger.info("No Qt base translation for '%s'", language)
        return False
