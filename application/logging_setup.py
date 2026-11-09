"""Technical log configuration (rotating file + console)."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

from application.paths import log_dir

LOG_FILE = "rocket_motor_manager.log"
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO, directory: Optional[Path] = None) -> Path:
    """Configure the root logger and return the log file path.

    Levels used across the application: DEBUG, INFO, WARNING and ERROR.
    The file rotates at 1 MB and keeps 5 backups.
    """
    folder = directory or log_dir()
    log_path = folder / LOG_FILE
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = logging.Formatter(LOG_FORMAT)
    try:
        file_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        log_path = Path()
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    return log_path
