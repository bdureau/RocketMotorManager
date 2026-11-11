"""Centralised error handling.

* :func:`install_exception_hook` routes every uncaught exception (main
  thread and worker threads) to the log and to a dialog, so the application
  never terminates abruptly.
* :class:`ErrorReporter` is the single place where user-facing error,
  warning and information messages are built and displayed.
"""

from __future__ import annotations

from localization import _

import logging
import sys
import threading
import traceback
from types import TracebackType
from typing import Optional, Type

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from models.errors import FileAccessError, FileFormatError, RocketMotorError, ValidationError

logger = logging.getLogger(__name__)


def describe_exception(exc: BaseException) -> tuple[str, str]:
    """Return a ``(title, message)`` pair suitable for the user."""
    if isinstance(exc, FileFormatError):
        location = "\n\n" + _("File: {path}").format(path=exc.file_path) if exc.file_path else ""
        return _("Invalid file"), f"{exc}{location}"
    if isinstance(exc, FileAccessError):
        return _("File access error"), str(exc)
    if isinstance(exc, ValidationError):
        return _("Invalid data"), str(exc)
    if isinstance(exc, RocketMotorError):
        return _("Error"), str(exc)
    if isinstance(exc, MemoryError):
        return _("Out of memory"), _("The operation needs more memory than available.")
    return _("Unexpected error"), f"{type(exc).__name__}: {exc}"


class ErrorReporter(QObject):
    """Display messages to the user and log them consistently.

    A signal is used so that errors raised in worker threads are displayed
    from the GUI thread.
    """

    _show_requested = pyqtSignal(str, str, str)

    def __init__(self) -> None:
        super().__init__()
        self._show_requested.connect(self._show, Qt.ConnectionType.QueuedConnection)

    def error(self, parent: Optional[QWidget], exc: BaseException, context: str = "") -> None:
        """Log and display an exception."""
        title, message = describe_exception(exc)
        if context:
            message = f"{context}\n\n{message}"
        expected = isinstance(exc, RocketMotorError)
        if expected:
            logger.warning("%s: %s", title, message)
        else:
            logger.error("%s: %s", title, message, exc_info=(type(exc), exc, exc.__traceback__))
        self._display(parent, QMessageBox.Icon.Critical if not expected else QMessageBox.Icon.Warning, title, message)

    def warning(self, parent: Optional[QWidget], title: str, message: str) -> None:
        """Log and display a warning."""
        logger.warning("%s: %s", title, message)
        self._display(parent, QMessageBox.Icon.Warning, title, message)

    def info(self, parent: Optional[QWidget], title: str, message: str) -> None:
        """Display an information message."""
        logger.info("%s: %s", title, message)
        self._display(parent, QMessageBox.Icon.Information, title, message)

    def _display(self, parent: Optional[QWidget], icon: QMessageBox.Icon, title: str, message: str) -> None:
        if threading.current_thread() is threading.main_thread():
            self._message_box(parent, icon, title, message)
        else:
            self._show_requested.emit(icon.name, title, message)

    def _show(self, icon_name: str, title: str, message: str) -> None:
        self._message_box(QApplication.activeWindow(), QMessageBox.Icon[icon_name], title, message)

    @staticmethod
    def _message_box(parent: Optional[QWidget], icon: QMessageBox.Icon, title: str, message: str) -> None:
        if QApplication.instance() is None:
            return
        box = QMessageBox(icon, title, message, QMessageBox.StandardButton.Ok, parent)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.exec()


_reporter: Optional[ErrorReporter] = None


def reporter() -> ErrorReporter:
    """Return the application-wide :class:`ErrorReporter`."""
    global _reporter  # single instance created lazily once the QApplication exists
    if _reporter is None:
        _reporter = ErrorReporter()
    return _reporter


def _handle_uncaught(exc_type: Type[BaseException], exc: BaseException, tb: Optional[TracebackType]) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logger.critical("Uncaught exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
    try:
        reporter().error(QApplication.activeWindow(), exc, _("An unexpected error occurred. The details were written to the log file."))
    except Exception:  # last line of defence: never raise from the hook
        pass


def install_exception_hook() -> None:
    """Install the global handlers for uncaught exceptions."""
    sys.excepthook = _handle_uncaught

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        _handle_uncaught(args.exc_type, args.exc_value or Exception("unknown"), args.exc_traceback)

    threading.excepthook = thread_hook
