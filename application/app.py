"""Application bootstrap: logging, error hooks, Qt application, theme,
translations and main window."""

from __future__ import annotations

import logging
import sys
from typing import Optional, Sequence

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from application.application_controller import ApplicationController
from application.error_handler import install_exception_hook
from application.logging_setup import setup_logging
from application.paths import resource_path
from application.translator import TranslationManager
from application.version import APP_AUTHOR, APP_ID, APP_NAME, APP_VERSION
import localization

logger = logging.getLogger(__name__)


class RocketMotorManagerApp:
    """Owns the QApplication, the controller and the main window."""

    def __init__(self, argv: Optional[Sequence[str]] = None) -> None:
        self.argv = list(argv if argv is not None else sys.argv)
        self.log_path = setup_logging()
        install_exception_hook()
        logger.info("Starting %s %s", APP_NAME, APP_VERSION)
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        self.qt_app = QApplication.instance() or QApplication(self.argv)
        self.qt_app.setApplicationName(APP_NAME)
        self.qt_app.setApplicationVersion(APP_VERSION)
        self.qt_app.setOrganizationName(APP_AUTHOR)
        self.qt_app.setWindowIcon(QIcon(str(resource_path("resources", "icons", "app.ico"))))
        self._set_windows_app_id()
        self.controller = ApplicationController()
        language = self.controller.preferences.language
        localization.install(language)  # application texts (gettext .po/.mo)
        self.translations = TranslationManager()
        self.translations.install(self.qt_app, language)  # Qt standard dialogs
        from ui.main_window import MainWindow  # imported after QApplication creation

        self.window = MainWindow(self.controller)

    @staticmethod
    def _set_windows_app_id() -> None:
        """Give the process its own taskbar identity on Windows."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"BorisDuReau.{APP_ID}.{APP_VERSION}")
        except (AttributeError, OSError):
            logger.debug("Cannot set the Windows AppUserModelID")

    def run(self) -> int:
        """Show the main window, open a file given on the command line and
        enter the Qt event loop."""
        self.window.show()
        files = [arg for arg in self.argv[1:] if not arg.startswith("-")]
        if files:
            QTimer.singleShot(0, lambda: self.window.open_path(files[0]))
        code = self.qt_app.exec()
        logger.info("Exit code %s", code)
        return code
