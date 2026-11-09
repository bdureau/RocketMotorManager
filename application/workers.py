"""Background execution of long operations without freezing the GUI.

Usage::

    worker = TaskWorker(heavy_function, arg1, arg2)
    worker.signals.finished.connect(on_result)
    worker.signals.failed.connect(on_error)
    QThreadPool.globalInstance().start(worker)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """Signals emitted by :class:`TaskWorker` (delivered in the GUI thread)."""

    finished = pyqtSignal(object)
    failed = pyqtSignal(object)


class TaskWorker(QRunnable):
    """Run a callable in the Qt thread pool and report its outcome."""

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:  # noqa: D401 - Qt override
        """Execute the task; exceptions are forwarded, never raised."""
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as exc:  # forwarded to the GUI thread
            logger.exception("Background task failed")
            self.signals.failed.emit(exc)
            return
        self.signals.finished.emit(result)
